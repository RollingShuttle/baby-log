import Combine
import Foundation
import SwiftUI

/// Everything the screens read: the resolved journal, the sync engine and this phone's own
/// settings (label, quick-amount range, language). Writes go through here so every one is
/// stamped the same way and followed by a sync.
@MainActor
final class AppModel: ObservableObject {
    let journal: Journal
    let sync: SyncEngine
    let auth = Auth.shared
    let device: String

    @Published private(set) var events: [Record] = []
    @Published private(set) var child: Record? = nil
    @Published var signedIn = false
    @Published var lastMessage: String? = nil
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

    private var syncTask: Task<Void, Never>? = nil
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
        let j = Journal()
        journal = j
        sync = SyncEngine(journal: j, graph: Graph(token: { try await Auth.shared.accessToken() }))
        L10n.override = language
        signedIn = auth.isSignedIn
        sync.onChange = { [weak self] in self?.refresh() }
        sync.objectWillChange.sink { [weak self] _ in self?.objectWillChange.send() }.store(in: &bag)
        refresh()
    }

    func refresh() {
        events = journal.events
        child = journal.child
        signedIn = auth.isSignedIn
    }
    func becameActive() {
        refresh()
        requestSync(after: 0)
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

    func logFeed(ml: Int, formula: String, time: Date, note: String, editing: Record? = nil) {
        let portion: [String: Any] = ["kind": "formula", "ml": ml, "formula": orNull(formula)]
        write(type: "feed", time: time, data: ["bottles": [portion]], note: note, editing: editing)
    }
    func logDiaper(wet: Bool, dirty: Bool, time: Date, note: String, editing: Record? = nil) {
        write(type: "diaper", time: time, data: ["wet": wet, "dirty": dirty], note: note, editing: editing)
    }
    func logNote(text: String, time: Date, editing: Record? = nil) {
        write(type: "note", time: time, data: [:], note: text, editing: editing)
    }
    /// A time or note change on a type this app has no editor for (sleep, pump, growth...).
    func saveOther(time: Date, note: String, editing: Record) {
        write(type: editing.type, time: time, data: [:], note: note, editing: editing)
    }
    func delete(_ rec: Record) {
        guard let id = rec.eventId else { return }
        var body = rec.body
        body["revision"] = journal.highestRevision(of: id) + 1
        body["deleted"] = true
        body["reason"] = "swipe"
        body["edited_by"] = orNull(label)
        stampAndWrite(&body)
        lastMessage = S("toast.deletedType", ["type": typeName(rec.type), "time": timeText(rec.instant)])
    }

    private func write(type: String, time: Date, data: [String: Any], note: String, editing: Record?) {
        guard let childId = child?.childId else {
            lastMessage = S("now.childCreatedOnPc")
            return
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
        stampAndWrite(&body)
        lastMessage = S("toast.saved", ["type": typeName(type), "time": timeText(time)])
    }
    private func stampAndWrite(_ body: inout [String: Any]) {
        body["device"] = device
        body["entered_from"] = "phone"
        body["created_at"] = Names.nowIso()
        do {
            try journal.write(event: body)
        } catch {
            lastMessage = error.localizedDescription
        }
        refresh()
        requestSync(after: 2)
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
        default:
            return [:]
        }
    }
    private func orNull(_ s: String) -> Any {
        if s.isEmpty { return NSNull() }
        return s
    }
}
