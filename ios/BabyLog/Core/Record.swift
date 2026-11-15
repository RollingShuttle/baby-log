import Foundation

/// One journal file as read: the JSON body plus the filename it came from (the w tie-break).
/// Fields are read leniently, as core.js reads them; JSON nulls arrive as NSNull and count as
/// absent. The instant, the day and the w are parsed once here, because sorting and
/// resolving read them thousands of times. So are the fields the whole-journal loops read
/// (resolve, live, the lists, totals and formula chips): `body` never changes, and every read
/// through it bridges an Any again, and `data` a whole nested dictionary.
struct Record {
    let body: [String: Any]
    let file: String
    let instant: Date?
    let day: String
    let w: String
    let eventId: String?
    let childId: String?
    let type: String
    let end: String?
    let deleted: Bool
    let createdAt: String
    let device: String
    let bottleMl: Double
    /// The first portion's formula name, or nil: what the feed sheet preselects.
    let formula: String?
    let wet: Bool
    let dirty: Bool

    init(body: [String: Any], file: String) {
        self.body = body
        self.file = file
        let time = body["time"] as? String
        instant = Names.parseIso(time)
        day = Names.localDate(time)
        w = Names.wSuffix(file)
        eventId = body["event_id"] as? String
        childId = body["child_id"] as? String
        self.type = (body["type"] as? String) ?? ""
        end = body["end"] as? String
        deleted = (body["deleted"] as? Bool) ?? false
        createdAt = (body["created_at"] as? String) ?? ""
        device = (body["device"] as? String) ?? ""
        let d = (body["data"] as? [String: Any]) ?? [:]
        let portions = (d["bottles"] as? [[String: Any]]) ?? []
        bottleMl = portions.reduce(0.0) { sum, b in sum + ((b["ml"] as? Double) ?? 0) }
        if let first = portions.first, let f = first["formula"] as? String, !f.isEmpty {
            formula = f
        } else {
            formula = nil
        }
        wet = (d["wet"] as? Bool) ?? false
        dirty = (d["dirty"] as? Bool) ?? false
    }

    func string(_ key: String) -> String? { body[key] as? String }
    func int(_ key: String) -> Int? {
        if let n = body[key] as? Int { return n }
        if let n = body[key] as? Double { return Int(n) }
        return nil
    }
    func bool(_ key: String) -> Bool { (body[key] as? Bool) ?? false }

    var time: String? { string("time") }
    // Left computed: int() traps on a huge double, and a stored one would trap on every launch
    // for one malformed file instead of only when its id is touched.
    var revision: Int { int("revision") ?? 0 }
    var note: String { string("note") ?? "" }
    var data: [String: Any] { (body["data"] as? [String: Any]) ?? [:] }
    var loggedBy: String? { string("logged_by") }
    var editedBy: String? { string("edited_by") }

    var bottles: [[String: Any]] { (data["bottles"] as? [[String: Any]]) ?? [] }
    func number(_ key: String) -> Double? { data[key] as? Double }
    var madeMl: Double? { number("made_ml") }
    var leftoverMl: Double? { number("leftover_ml") }

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
