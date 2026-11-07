import Combine
import Foundation
import SwiftUI

/// One point of a day's cumulative bottle intake.
struct IntakePoint: Identifiable {
    let id: Int
    let hour: Double
    let ml: Int
}

/// One day of the Trends screen.
struct DayStat: Identifiable {
    let day: String           // YYYY-MM-DD
    let label: String         // "11/6"
    let isToday: Bool
    let feeds: Int
    let ml: Int
    let wet: Int
    let dirty: Int
    let feedHours: [Double]   // start times as hours since local midnight
    let wetHours: [Double]
    let dirtyHours: [Double]
    let intake: [IntakePoint] // cumulative ml through the day, (0, 0) first; a past day ends at 24
    var id: String { day }
}

/// What the intake chart says about today.
struct IntakeForecast {
    let soFar: Int
    let typicalShare: Double   // 0...1: the mean share of a past day's total drunk by this hour
    let projectedTotal: Int?   // soFar / typicalShare, when both are big enough to mean something
    let averageTotal: Int
    let pastDays: Int
}

/// Everything the screens read: the resolved journal, the sync engine and this phone's own
/// settings (label, quick-amount range, language). Writes go through here so every one is
/// stamped the same way and followed by a sync.
@MainActor
final class AppModel: ObservableObject {
    /// One instance for the app and its Siri intents, so both see the same index.
    static let shared = AppModel()

    let journal: Journal
    let sync: SyncEngine
    let auth = Auth.shared
    let device: String

    @Published private(set) var events: [Record] = []
    @Published private(set) var child: Record? = nil
    @Published var signedIn = false
    @Published var lastMessage: String? = nil
    @Published var undoable: Record? = nil         // the last one-tap diaper, while its toast shows
    @Published var day = Names.dayOf(Date())
    @Published var label: String {
        didSet { UserDefaults.standard.set(label, forKey: "bl.label") }
    }
    @Published var language: String {
        didSet {
            UserDefaults.standard.set(language, forKey: "bl.language")
            L10n.override = language
        }
    }
    @Published var quickFrom: Int {
        didSet { UserDefaults.standard.set(quickFrom, forKey: "bl.quick_from") }
    }
    @Published var quickTo: Int {
        didSet { UserDefaults.standard.set(quickTo, forKey: "bl.quick_to") }
    }
    @Published var quickStep: Int {
        didSet { UserDefaults.standard.set(quickStep, forKey: "bl.quick_step") }
    }

    @Published private(set) var loading = true
    private var syncTask: Task<Void, Never>? = nil
    private var loadTask: Task<Void, Never>? = nil
    private var bag = Set<AnyCancellable>()

    init() {
        let d = UserDefaults.standard
        label = d.string(forKey: "bl.label") ?? ""
        language = d.string(forKey: "bl.language") ?? ""
        quickFrom = d.object(forKey: "bl.quick_from") == nil ? 60 : d.integer(forKey: "bl.quick_from")
        quickTo = d.object(forKey: "bl.quick_to") == nil ? 120 : d.integer(forKey: "bl.quick_to")
        quickStep = d.object(forKey: "bl.quick_step") == nil ? 10 : d.integer(forKey: "bl.quick_step")
        // The device id of this install, "d-xxxx" like the web app's: a resolve tie-break only.
        let dev = d.string(forKey: "bl.device") ?? ("d-" + Names.rand4())
        d.set(dev, forKey: "bl.device")
        device = dev
        // The index is built off the main thread: a thousand files parsed at launch would
        // otherwise freeze the first screen.
        let j = Journal(load: false)
        journal = j
        sync = SyncEngine(journal: j, graph: Graph(token: { try await Auth.shared.accessToken() }))
        L10n.override = language
        signedIn = auth.isSignedIn
        sync.onChange = { [weak self] in self?.refresh() }
        sync.objectWillChange.sink { [weak self] _ in self?.objectWillChange.send() }.store(in: &bag)
        WatchBridge.shared.start()
        let root = j.root
        loadTask = Task { [weak self] in
            let scanned = await Task.detached(priority: .userInitiated) { Journal.scan(root: root) }.value
            guard let self = self else { return }
            self.journal.install(scanned)
            self.loading = false
            self.refresh()
            self.requestSync(after: 0)
        }
    }

    /// Waits for the index; Siri intents call this before reading or writing.
    func ready() async {
        await loadTask?.value
    }

    func refresh() {
        if loading { return }
        events = journal.events
        child = journal.child
        signedIn = auth.isSignedIn
        pushWatchSummary()
    }
    func pushWatchSummary() {
        if loading { return }
        WatchBridge.shared.push(watchSummary())
    }
    /// What the watch shows: the last feed and diaper as instants and texts, today's totals,
    /// the quick amounts, and every label in this phone's language.
    func watchSummary() -> [String: Any] {
        var out: [String: Any] = [
            "child": child?.string("name") ?? "",
            "totals": todayTotals,
            "quick": quickAmounts,
            "lastMl": lastFeed.map { Int($0.bottleMl.rounded()) } ?? 0,
        ]
        if let feed = lastFeed, let at = feed.instant {
            out["lastFeedAt"] = at.timeIntervalSince1970
            out["lastFeedText"] = describe(feed)
        }
        if let diaper = lastDiaper, let at = diaper.instant {
            out["lastDiaperAt"] = at.timeIntervalSince1970
            out["lastDiaperText"] = describe(diaper)
        }
        out["labels"] = [
            "feed": S("log.feed"), "wet": S("log.wet"), "dirty": S("log.dirty"), "both": S("log.both"),
            "lastFeed": S("now.lastFeed"), "lastDiaper": S("now.lastDiaper"),
            "noFeed": S("now.noFeedYet"), "noDiaper": S("now.noDiaperYet"),
            "minutes": S("since.minutes"), "hoursMinutes": S("since.hoursMinutes"),
            "daysHours": S("since.daysHours"), "ago": S("since.ago"),
            "queued": S("watch.queued"), "noPhone": S("watch.noPhone"), "sent": S("watch.sent"),
        ] as [String: String]
        return out
    }
    /// A tap or a Siri phrase on the watch: a diaper or a feed, at the time it was made
    /// (a queued one arrives late). Returns the summary plus the text the watch shows or speaks.
    func handleWatch(_ message: [String: Any]) async -> [String: Any] {
        await ready()
        guard child != nil else { return ["ok": false, "text": S("siri.noChildYet")] }
        let at = (message["at"] as? Double).map { Date(timeIntervalSince1970: $0) } ?? Date()
        let type = (message["type"] as? String) ?? ""
        // The watch re-sends a tap through transferUserInfo when the answer to its message was
        // lost (usual while this app is cold-launched and still scanning): same tap, same time,
        // same device, so the second copy answers with the record already written.
        let timeString = Names.isoLocal(at)
        if let dup = events.last(where: { $0.type == type && $0.time == timeString && $0.device == device }) {
            var reply = watchSummary()
            reply["ok"] = true
            reply["text"] = type == "feed"
                ? S("siri.loggedFeed", ["amount": S("amount.ml", ["n": String(Int(dup.bottleMl.rounded()))]), "time": timeText(dup.instant)])
                : S("siri.loggedDiaper", ["description": describe(dup), "time": timeText(dup.instant)])
            return reply
        }
        var written: Record? = nil
        var text = ""
        switch type {
        case "diaper":
            written = logDiaper(wet: (message["wet"] as? Bool) ?? true, dirty: (message["dirty"] as? Bool) ?? false,
                                time: at, note: "")
            if let rec = written {
                text = S("siri.loggedDiaper", ["description": describe(rec), "time": timeText(rec.instant)])
            }
        case "feed":
            let ml = (message["ml"] as? Int) ?? 0
            guard ml > 0 else { return ["ok": false, "text": S("amount.ml", ["n": "0"])] }
            written = logFeed(ml: ml, formula: formulaChoices.first ?? "", made: nil, time: at, note: "")
            if let rec = written {
                text = S("siri.loggedFeed", ["amount": S("amount.ml", ["n": String(ml)]), "time": timeText(rec.instant)])
            }
        default:
            return ["ok": false, "text": "?"]
        }
        guard written != nil else { return ["ok": false, "text": S("error.notSavedStorageFull")] }
        var reply = watchSummary()
        reply["ok"] = true
        reply["text"] = text
        return reply
    }
    func becameActive() {
        if loading { return }
        refresh()
        requestSync(after: 0)
    }
    /// Once a minute: the "2 h ago" texts re-render; nothing is recomputed.
    func tickMinute() {
        objectWillChange.send()
    }
    /// One sync after a pause, so a burst of taps becomes one upload.
    func requestSync(after seconds: Double) {
        syncTask?.cancel()
        syncTask = Task { [weak self] in
            if seconds > 0 { try? await Task.sleep(nanoseconds: UInt64(seconds * 1_000_000_000)) }
            if Task.isCancelled { return }
            await self?.sync.sync()
        }
    }
    func signIn() {
        Task { [weak self] in
            guard let self = self else { return }
            do {
                try await self.auth.signIn()
                self.signedIn = true
                await self.sync.sync()
            } catch {
                self.lastMessage = error.localizedDescription
            }
        }
    }
    func signOut() {
        auth.signOut()
        signedIn = false
    }
    func checkEverything() {
        sync.forgetDelta()
        requestSync(after: 0)
    }
    var statusText: String { sync.statusText(signedIn: signedIn, pending: journal.pending.count) }

    // -- what the screens show

    var dayEvents: [Record] { events.filter { $0.day == day } }
    var lastFeed: Record? { events.last(where: { $0.type == "feed" }) }
    var lastDiaper: Record? { events.last(where: { $0.type == "diaper" }) }
    var formulaChoices: [String] {
        Record.formulaChoices(events.filter { $0.type == "feed" }.reversed().compactMap { $0.formula })
    }
    var quickAmounts: [Int] {
        guard quickStep > 0, quickTo >= quickFrom else { return [] }
        return Array(stride(from: quickFrom, through: quickTo, by: quickStep))
    }
    var todayTotals: String {
        let today = Names.dayOf(Date())
        let todays = events.filter { $0.day == today }
        let ml = Int(todays.filter { $0.type == "feed" }.reduce(0.0) { $0 + $1.bottleMl }.rounded())
        let wet = todays.filter { $0.type == "diaper" && $0.wet }.count
        let dirty = todays.filter { $0.type == "diaper" && $0.dirty }.count
        return [S("now.bottleTotal", ["amount": S("amount.ml", ["n": String(ml)])]),
                S("now.wetTotal", ["n": String(wet)]),
                S("now.dirtyTotal", ["n": String(dirty)])].joined(separator: " · ")
    }
    var ageText: String {
        guard let born = child?.string("born"), let b = Names.dateOfDay(born) else { return "" }
        let days = max(0, Int(Date().timeIntervalSince(b) / 86400))
        if days < 14 { return SP("age.daysOld", days) }
        if days < 91 { return S("age.weeksDays", ["w": String(days / 7), "d": String(days % 7)]) }
        return S("age.monthsWeeks", ["m": String(days / 30), "w": String((days % 30) / 7)])
    }

    /// Hours since local midnight of a record's start, read off the time string itself (the
    /// writer's clock, never re-zoned).
    private func hourOf(_ rec: Record) -> Double? {
        guard let time = rec.time, time.count >= 16,
              let h = Int(time.dropFirst(11).prefix(2)), let m = Int(time.dropFirst(14).prefix(2)) else { return nil }
        return Double(h) + Double(m) / 60
    }
    var hourNow: Double {
        let c = Calendar.current.dateComponents([.hour, .minute], from: Date())
        return Double(c.hour ?? 0) + Double(c.minute ?? 0) / 60
    }
    /// The last `n` local days, oldest first, for the Trends charts.
    func dailyStats(days n: Int) -> [DayStat] {
        let today = Names.dayOf(Date())
        let now = hourNow
        var out: [DayStat] = []
        for back in stride(from: n - 1, through: 0, by: -1) {
            let day = Names.shiftDay(today, -back)
            let isToday = day == today
            let todays = events.filter { $0.day == day }
            let feeds = todays.filter { $0.type == "feed" }
            let diapers = todays.filter { $0.type == "diaper" }
            let timed = feeds.compactMap { rec -> (hour: Double, ml: Int)? in
                guard let h = hourOf(rec) else { return nil }
                return (hour: h, ml: Int(rec.bottleMl.rounded()))
            }.sorted { $0.hour < $1.hour }
            var intake = [IntakePoint(id: 0, hour: 0, ml: 0)]
            var running = 0
            for (i, feed) in timed.enumerated() {
                running += feed.ml
                intake.append(IntakePoint(id: i + 1, hour: feed.hour, ml: running))
            }
            let lastHour = intake.last?.hour ?? 0
            intake.append(IntakePoint(id: timed.count + 1, hour: isToday ? max(now, lastHour) : 24, ml: running))
            let parts = day.split(separator: "-")
            let label = parts.count == 3 ? "\(Int(parts[1]) ?? 0)/\(Int(parts[2]) ?? 0)" : day
            out.append(DayStat(day: day, label: label, isToday: isToday, feeds: feeds.count, ml: running,
                               wet: diapers.filter { $0.wet }.count, dirty: diapers.filter { $0.dirty }.count,
                               feedHours: timed.map { $0.hour },
                               wetHours: diapers.filter { $0.wet }.compactMap { hourOf($0) },
                               dirtyHours: diapers.filter { $0.dirty }.compactMap { hourOf($0) },
                               intake: intake))
        }
        return out
    }
    /// Today against the past days' pace: how much of a day's milk is usually drunk by this
    /// hour, and what that says about the rest of today. Nil until a past day has feeds.
    func intakeForecast(_ stats: [DayStat]) -> IntakeForecast? {
        guard let today = stats.last, today.isToday else { return nil }
        let past = stats.dropLast().filter { $0.ml > 0 }
        guard !past.isEmpty else { return nil }
        let now = hourNow
        var shares: [Double] = []
        for d in past {
            let byNow = d.intake.last(where: { $0.hour <= now })?.ml ?? 0
            shares.append(Double(byNow) / Double(d.ml))
        }
        let share = shares.reduce(0, +) / Double(shares.count)
        let average = Int((Double(past.reduce(0) { $0 + $1.ml }) / Double(past.count)).rounded())
        let projected = share >= 0.1 && today.ml > 0 ? Int((Double(today.ml) / share).rounded()) : nil
        return IntakeForecast(soFar: today.ml, typicalShare: share, projectedTotal: projected,
                              averageTotal: average, pastDays: past.count)
    }

    /// "made 120 ml / left 40 ml" for a feed that recorded its bottle, else nil.
    func madeLeftText(_ rec: Record) -> String? {
        guard let made = rec.madeMl, made > 0 else { return nil }
        let left = rec.leftoverMl ?? max(0, made - rec.bottleMl)
        return S("day.madeLeft", ["made": S("amount.ml", ["n": String(Int(made.rounded()))]),
                                "left": S("amount.ml", ["n": String(Int(left.rounded()))])])
    }
    func typeName(_ type: String) -> String {
        switch type {
        case "feed": return S("log.feed")
        case "diaper": return S("type.diaper")
        case "note": return S("log.note")
        case "sleep": return S("log.sleep")
        case "pump": return S("log.pump")
        case "growth": return S("tab.growth")
        case "health": return S("tab.health")
        default: return type
        }
    }
    func timeText(_ date: Date?) -> String {
        date.map { $0.formatted(date: .omitted, time: .shortened) } ?? ""
    }
    func describe(_ rec: Record) -> String {
        switch rec.type {
        case "feed":
            let ml = Int(rec.bottleMl.rounded())
            var text = ml > 0 ? S("amount.ml", ["n": String(ml)]) : S("log.feed")
            if let f = rec.formula { text += " · " + f }
            return text
        case "diaper":
            if rec.wet && rec.dirty { return S("describe.wetDirty") }
            return rec.dirty ? S("log.dirty") : S("log.wet")
        case "note":
            return rec.note.isEmpty ? S("log.note") : rec.note
        case "growth":
            var parts: [String] = []
            if let g = rec.number("weight_g"), g > 0 {
                parts.append(S("describe.weight", ["weight": S("amount.kg", ["n": String(format: "%.2f", (g / 10).rounded() / 100)])]))
            }
            if let l = rec.number("length_cm"), l > 0 { parts.append(S("describe.length", ["length": S("amount.cm", ["n": EntryDraft.trim(l)])])) }
            if let h = rec.number("head_cm"), h > 0 { parts.append(S("describe.head", ["head": S("amount.cm", ["n": EntryDraft.trim(h)])])) }
            return parts.isEmpty ? S("tab.growth") : parts.joined(separator: " · ")
        default:
            return typeName(rec.type)
        }
    }
    func sinceText(_ date: Date?) -> String {
        guard let date = date else { return "" }
        let minutes = max(0, Int(-date.timeIntervalSinceNow / 60))
        let since: String
        if minutes < 60 {
            since = S("since.minutes", ["m": String(minutes)])
        } else if minutes < 1440 {
            since = S("since.hoursMinutes", ["h": String(minutes / 60), "m": String(minutes % 60)])
        } else {
            since = S("since.daysHours", ["d": String(minutes / 1440), "h": String((minutes % 1440) / 60)])
        }
        return S("since.ago", ["since": since])
    }
    func icon(for rec: Record) -> String {
        switch rec.type {
        case "feed": return "drop.fill"
        case "diaper": return rec.dirty ? "cloud.fill" : "drop"
        case "note": return "note.text"
        case "sleep": return "moon.zzz.fill"
        case "pump": return "arrow.down.circle"
        case "growth": return "scalemass"
        default: return "cross.case"
        }
    }
    func color(for rec: Record) -> Color {
        switch rec.type {
        case "feed": return .blue
        case "diaper": return rec.dirty ? .brown : .teal
        case "sleep": return .indigo
        default: return .secondary
        }
    }

    // -- writes: every one a new revision file, stamped alike (SPEC §3.1)

    /// `made` is the bottle prepared; the leftover is what was not drunk. Both optional.
    @discardableResult
    func logFeed(ml: Int, formula: String, made: Int?, time: Date, note: String, editing: Record? = nil) -> Record? {
        let portion: [String: Any] = ["kind": "formula", "ml": ml, "formula": orNull(formula)]
        var data: [String: Any] = ["bottles": [portion]]
        if let made = made, made > 0 {
            data["made_ml"] = made
            data["leftover_ml"] = max(0, made - ml)
        } else {
            data["made_ml"] = NSNull()
            data["leftover_ml"] = NSNull()
        }
        return write(type: "feed", time: time, data: data, note: note, editing: editing)
    }
    func logGrowth(weightG: Int?, lengthCm: Double?, headCm: Double?, time: Date, note: String, editing: Record? = nil) {
        let data: [String: Any] = ["weight_g": orNull(weightG.map { Double($0) }),
                                   "length_cm": orNull(lengthCm), "head_cm": orNull(headCm)]
        write(type: "growth", time: time, data: data, note: note, editing: editing)
    }
    @discardableResult
    func logDiaper(wet: Bool, dirty: Bool, time: Date, note: String, editing: Record? = nil) -> Record? {
        write(type: "diaper", time: time, data: ["wet": wet, "dirty": dirty], note: note, editing: editing)
    }
    /// The log bar's one tap: written now, undoable while the toast shows. A mis-tap at 3 a.m.
    /// is one more tap to take back; the journal keeps the tombstone with reason "undo".
    func logDiaperQuick(wet: Bool, dirty: Bool) {
        undoable = logDiaper(wet: wet, dirty: dirty, time: Date(), note: "")
    }
    func undo() {
        guard let rec = undoable else { return }
        undoable = nil
        delete(rec, reason: "undo")
    }
    func logNote(text: String, time: Date, editing: Record? = nil) {
        write(type: "note", time: time, data: [:], note: text, editing: editing)
    }
    /// A time or note change on a type this app has no editor for (sleep, pump, growth...).
    func saveOther(time: Date, note: String, editing: Record) {
        write(type: editing.type, time: time, data: [:], note: note, editing: editing)
    }
    func delete(_ rec: Record, reason: String = "swipe") {
        guard let id = rec.eventId else { return }
        var body = rec.body
        body["revision"] = journal.highestRevision(of: id) + 1
        body["deleted"] = true
        body["reason"] = reason
        body["edited_by"] = orNull(label)
        stampAndWrite(&body)
        lastMessage = S("toast.deletedType", ["type": typeName(rec.type), "time": timeText(rec.instant)])
    }

    @discardableResult
    private func write(type: String, time: Date, data: [String: Any], note: String, editing: Record?) -> Record? {
        guard let childId = child?.childId else {
            lastMessage = S("now.childCreatedOnPc")
            return nil
        }
        var body: [String: Any]
        var merged: [String: Any]
        if let old = editing, let id = old.eventId {
            // A revision keeps everything it does not change, breast minutes and timers included.
            body = old.body
            body["revision"] = journal.highestRevision(of: id) + 1
            body["edited_by"] = orNull(label)
            if (body["logged_by"] as? String) == nil { body["logged_by"] = label.isEmpty ? "phone" : label }
            merged = old.type == type ? old.data : AppModel.defaults(for: type)
            if let endDate = Names.parseIso(old.end), endDate < time { body["end"] = NSNull() }
        } else {
            body = ["event_id": Names.newId("E"), "revision": 1, "deleted": false, "reason": NSNull(),
                    "logged_by": label.isEmpty ? "phone" : label, "edited_by": NSNull(), "end": NSNull()]
            merged = AppModel.defaults(for: type)
        }
        for (k, v) in data { merged[k] = v }
        body["child_id"] = childId
        body["type"] = type
        body["time"] = Names.isoLocal(time)
        body["data"] = merged
        body["note"] = note
        let written = stampAndWrite(&body)
        lastMessage = S("toast.saved", ["type": typeName(type), "time": timeText(time)])
        return written
    }
    @discardableResult
    private func stampAndWrite(_ body: inout [String: Any]) -> Record? {
        body["device"] = device
        body["entered_from"] = "phone"
        body["created_at"] = Names.nowIso()
        var written: Record? = nil
        do {
            let rel = try journal.write(event: body)
            written = journal.records[rel]
        } catch {
            lastMessage = error.localizedDescription
        }
        refresh()
        requestSync(after: 2)
        return written
    }
    /// The fixture's defaults for the types this app writes (tests/fixtures/data_cases.json).
    private static func defaults(for type: String) -> [String: Any] {
        switch type {
        case "feed":
            return ["breast": ["left_s": NSNull(), "right_s": NSNull(), "total_s": NSNull(),
                               "last_side": NSNull(), "approx": false] as [String: Any],
                    "bottles": [[String: Any]](), "made_ml": NSNull(), "leftover_ml": NSNull(), "timer": NSNull()]
        case "diaper":
            return ["wet": false, "dirty": false, "color": NSNull(), "texture": NSNull(), "size": NSNull(),
                    "rash": false, "blowout": false]
        case "note":
            return ["milestone": false]
        case "growth":
            return ["weight_g": NSNull(), "length_cm": NSNull(), "head_cm": NSNull()]
        default:
            return [:]
        }
    }
    private func orNull(_ s: String) -> Any {
        if s.isEmpty { return NSNull() }
        return s
    }
    private func orNull(_ x: Double?) -> Any {
        if let x = x, x > 0 { return x }
        return NSNull()
    }
}
