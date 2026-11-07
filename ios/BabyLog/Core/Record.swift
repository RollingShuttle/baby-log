import Foundation

/// One journal file as read: the JSON body plus the filename it came from (the w tie-break).
/// Fields are read leniently, as core.js reads them; JSON nulls arrive as NSNull and count as
/// absent. The instant, the day and the w are parsed once here, because sorting and
/// resolving read them thousands of times.
struct Record {
    let body: [String: Any]
    let file: String
    let instant: Date?
    let day: String
    let w: String

    init(body: [String: Any], file: String) {
        self.body = body
        self.file = file
        let time = body["time"] as? String
        instant = Names.parseIso(time)
        day = Names.localDate(time)
        w = Names.wSuffix(file)
    }

    func string(_ key: String) -> String? { body[key] as? String }
    func int(_ key: String) -> Int? {
        if let n = body[key] as? Int { return n }
        if let n = body[key] as? Double { return Int(n) }
        return nil
    }
    func bool(_ key: String) -> Bool { (body[key] as? Bool) ?? false }

    var eventId: String? { string("event_id") }
    var childId: String? { string("child_id") }
    var type: String { string("type") ?? "" }
    var time: String? { string("time") }
    var end: String? { string("end") }
    var revision: Int { int("revision") ?? 0 }
    var deleted: Bool { bool("deleted") }
    var note: String { string("note") ?? "" }
    var data: [String: Any] { (body["data"] as? [String: Any]) ?? [:] }
    var createdAt: String { string("created_at") ?? "" }
    var device: String { string("device") ?? "" }
    var loggedBy: String? { string("logged_by") }
    var editedBy: String? { string("edited_by") }

    var bottles: [[String: Any]] { (data["bottles"] as? [[String: Any]]) ?? [] }
    var bottleMl: Double {
        bottles.reduce(0.0) { sum, b in sum + ((b["ml"] as? Double) ?? 0) }
    }
    /// The first portion's formula name, or nil: what the feed sheet preselects.
    var formula: String? {
        guard let first = bottles.first, let f = first["formula"] as? String, !f.isEmpty else { return nil }
        return f
    }
    func number(_ key: String) -> Double? { data[key] as? Double }
    var madeMl: Double? { number("made_ml") }
    var leftoverMl: Double? { number("leftover_ml") }
    var wet: Bool { (data["wet"] as? Bool) ?? false }
    var dirty: Bool { (data["dirty"] as? Bool) ?? false }

    // -- resolution (SPEC §3.4): the one rule, the same five-part key as store._rank and
    // Core.rank: revision, then (feed/sleep/pump) stopped beats running, then created_at,
    // device, and the filename's w.
    static let endTypes: Set<String> = ["feed", "sleep", "pump"]
    var rank: (Int, Int, String, String, String) {
        (revision, Record.endTypes.contains(type) && end != nil ? 1 : 0, createdAt, device, w)
    }
    func beats(_ other: Record) -> Bool { rank > other.rank }

    /// Map id -> the winning record, tombstones included.
    static func resolve(_ records: [Record], key: (Record) -> String?) -> [String: Record] {
        var out: [String: Record] = [:]
        for rec in records {
            guard let id = key(rec) else { continue }
            if let held = out[id], !rec.beats(held) { continue }
            out[id] = rec
        }
        return out
    }
    /// The resolved records that are not deleted, by time as an instant, ties by id.
    static func live(_ records: [Record], key: (Record) -> String?) -> [Record] {
        resolve(records, key: key).values.filter { !$0.deleted }.sorted { a, b in
            let ta = a.instant?.timeIntervalSince1970 ?? 0
            let tb = b.instant?.timeIntervalSince1970 ?? 0
            if ta != tb { return ta < tb }
            return (key(a) ?? "") < (key(b) ?? "")
        }
    }
    /// The formula chips: the distinct names of the most recent portions, newest first, at
    /// most four; the two starters when nothing has been recorded yet (Core.formulaChoices).
    static func formulaChoices(_ recent: [String]) -> [String] {
        var out: [String] = []
        for name in recent where !name.isEmpty && !out.contains(name) {
            out.append(name)
            if out.count == 4 { break }
        }
        return out.isEmpty ? ["Similac", "Enfamil"] : out
    }
}
