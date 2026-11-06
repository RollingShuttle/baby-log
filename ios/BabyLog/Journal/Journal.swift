import Foundation

enum JournalError: Error {
    case badRecord
}

/// The local mirror of the OneDrive app folder (the same children/ and events/<day>/ files)
/// plus an outbox of the files this phone wrote and has not uploaded yet. Files are immutable
/// (CLAUDE.md rule 1): a change is a new file, and sync only ever copies files across.
final class Journal {
    let root: URL
    private(set) var records: [String: Record] = [:]      // relative path -> record
    private(set) var pending: [String] = []               // relative paths awaiting upload
    private let fm = FileManager.default

    static func defaultRoot() -> URL {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        return base.appendingPathComponent("BabyLog/journal", isDirectory: true)
    }

    init(root: URL = Journal.defaultRoot()) {
        self.root = root
        try? fm.createDirectory(at: root, withIntermediateDirectories: true)
        load()
    }

    func load() {
        var out: [String: Record] = [:]
        for name in list("children") where Names.parseName(name) != nil {
            if let rec = read(relative: "children/" + name) { out["children/" + name] = rec }
        }
        for day in list("events") where day.count == 10 {
            for name in list("events/" + day) where Names.parseName(name) != nil {
                let rel = "events/" + day + "/" + name
                if let rec = read(relative: rel) { out[rel] = rec }
            }
        }
        records = out
        let outbox = root.appendingPathComponent("outbox.json")
        pending = (try? JSONDecoder().decode([String].self, from: Data(contentsOf: outbox))) ?? []
    }
    private func list(_ rel: String) -> [String] {
        (try? fm.contentsOfDirectory(atPath: root.appendingPathComponent(rel).path)) ?? []
    }
    func read(relative: String) -> Record? {
        guard let data = try? Data(contentsOf: root.appendingPathComponent(relative)),
              let obj = try? JSONSerialization.jsonObject(with: data),
              let dict = obj as? [String: Any] else { return nil }
        return Record(body: dict, file: String(relative.split(separator: "/").last ?? ""))
    }
    func exists(_ relative: String) -> Bool {
        fm.fileExists(atPath: root.appendingPathComponent(relative).path)
    }
    func data(of relative: String) -> Data? { try? Data(contentsOf: root.appendingPathComponent(relative)) }

    /// Keep a downloaded file exactly as it came.
    func store(relative: String, data: Data) throws {
        let url = root.appendingPathComponent(relative)
        try fm.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        try data.write(to: url, options: .atomic)
        if let rec = read(relative: relative) { records[relative] = rec }
    }
    /// Write one revision file into today's UTC folder and queue it for upload.
    @discardableResult
    func write(event body: [String: Any]) throws -> String {
        guard let id = body["event_id"] as? String, let rev = body["revision"] as? Int else {
            throw JournalError.badRecord
        }
        let rel = "events/" + Names.utcDate() + "/" + Names.fileName(id, rev)
        let data = try JSONSerialization.data(withJSONObject: body, options: [.prettyPrinted, .sortedKeys])
        try store(relative: rel, data: data)
        pending.append(rel)
        savePending()
        return rel
    }
    func markUploaded(_ relative: String) {
        pending.removeAll { $0 == relative }
        savePending()
    }
    private func savePending() {
        if let data = try? JSONEncoder().encode(pending) {
            try? data.write(to: root.appendingPathComponent("outbox.json"), options: .atomic)
        }
    }

    // -- resolved views

    var events: [Record] {
        Record.live(records.values.filter { $0.eventId != nil }, key: { $0.eventId })
    }
    /// Live children, oldest id first: the first one is the current child.
    var child: Record? {
        Record.live(records.values.filter { $0.childId != nil && $0.eventId == nil }, key: { $0.childId }).first
    }
    func resolved(_ eventId: String) -> Record? {
        Record.resolve(records.values.filter { $0.eventId == eventId }, key: { $0.eventId })[eventId]
    }
    func highestRevision(of eventId: String) -> Int {
        records.values.filter { $0.eventId == eventId }.map { $0.revision }.max() ?? 0
    }
    var fileCount: Int { records.count }
}
