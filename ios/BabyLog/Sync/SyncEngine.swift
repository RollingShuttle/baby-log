import Foundation

struct SyncState: Codable {
    var approotId: String?
    var deltaLink: String?
    var lastSyncAt: Date?
    var lastError: String?
    var lastErrorAt: Date?
}

/// One sync: flush the outbox, then walk the delta and download what the mirror lacks. The
/// listing is a few pages for the whole journal and the downloads run six at a time, so a
/// first sync of a thousand files takes seconds, not the twenty minutes of the web app's
/// folder-by-folder, file-by-file pull; a later sync sees only what changed.
@MainActor
final class SyncEngine: ObservableObject {
    @Published private(set) var busy = false
    @Published private(set) var phase = ""
    @Published private(set) var state: SyncState
    @Published private(set) var backoffUntil: Date?
    @Published private(set) var lastSent = 0
    @Published private(set) var lastReceived = 0

    let journal: Journal
    let graph: Graph
    private let stateUrl: URL
    var onChange: (() -> Void)?
    private static let parallel = 6

    init(journal: Journal, graph: Graph) {
        self.journal = journal
        self.graph = graph
        let url = journal.root.appendingPathComponent("sync.json")
        stateUrl = url
        state = (try? JSONDecoder().decode(SyncState.self, from: Data(contentsOf: url))) ?? SyncState()
    }

    private func save() {
        if let data = try? JSONEncoder().encode(state) { try? data.write(to: stateUrl, options: .atomic) }
    }
    /// Walk the whole folder on the next sync (files already here are still skipped).
    func forgetDelta() {
        state.deltaLink = nil
        save()
    }

    func sync() async {
        if busy { return }
        if let until = backoffUntil, until > Date() { return }
        busy = true
        phase = S("sync.syncing")
        var sent = 0
        var received = 0
        do {
            // 1. The outbox first, so the other devices see this phone's entries before it reads theirs.
            let outbox = journal.pending
            for (i, rel) in outbox.enumerated() {
                phase = S("sync.sending", ["done": String(i + 1), "total": String(outbox.count)])
                guard let data = journal.data(of: rel) else {
                    journal.markUploaded(rel)
                    continue
                }
                do {
                    try await graph.upload(relative: rel, data: data)
                } catch GraphError.http(let code, _) where code == 404 {
                    try await graph.ensureFolder(rel.split(separator: "/").dropLast().joined(separator: "/"))
                    try await graph.upload(relative: rel, data: data)
                }
                journal.markUploaded(rel)
                sent += 1
            }
            // 2. Everything that changed in the app folder since the stored delta link.
            let folderId: String
            if let id = state.approotId {
                folderId = id
            } else {
                folderId = try await graph.approotId()
                state.approotId = folderId
            }
            var link = state.deltaLink
            var newDelta: String? = nil
            var wanted: [GraphItem] = []
            repeat {
                let page = try await graph.delta(folderId: folderId, link: link)
                for item in page.items where !item.isFolder && !item.deleted && item.size > 0 {
                    guard let rel = item.relative, Names.parseName(item.name) != nil, !journal.exists(rel) else {
                        continue
                    }
                    wanted.append(item)
                }
                link = page.nextLink
                if let d = page.deltaLink { newDelta = d }
                phase = S("sync.reading", ["n": String(wanted.count)])
            } while link != nil
            // 3. The downloads, a few at a time; each file is kept as soon as it arrives.
            if !wanted.isEmpty {
                let graph = self.graph
                try await withThrowingTaskGroup(of: (String, Data).self) { group in
                    var next = 0
                    while next < wanted.count && next < SyncEngine.parallel {
                        let item = wanted[next]
                        next += 1
                        group.addTask {
                            let data = try await graph.download(item)
                            return (item.relative ?? "", data)
                        }
                    }
                    while let (rel, data) = try await group.next() {
                        try journal.store(relative: rel, data: data)
                        received += 1
                        phase = S("sync.reading", ["n": String(wanted.count - received)])
                        if next < wanted.count {
                            let item = wanted[next]
                            next += 1
                            group.addTask {
                                let data = try await graph.download(item)
                                return (item.relative ?? "", data)
                            }
                        }
                    }
                }
            }
            if let d = newDelta { state.deltaLink = d }
            state.lastSyncAt = Date()
            state.lastError = nil
            save()
        } catch GraphError.throttled(let seconds) {
            backoffUntil = Date().addingTimeInterval(Double(seconds))
        } catch AuthError.signedOut {
            // The pill reads "Signed out" from Auth; nothing to record here.
        } catch {
            state.lastError = error.localizedDescription
            state.lastErrorAt = Date()
            save()
        }
        lastSent = sent
        lastReceived = received
        phase = ""
        busy = false
        onChange?()
    }

    /// The pill text, the same phrases as the web app's Sync.statusText.
    func statusText(signedIn: Bool, pending: Int) -> String {
        if !signedIn {
            return pending > 0 ? S("sync.signedOutWaiting", ["n": String(pending)]) : S("sync.signedOutTap")
        }
        if busy { return phase.isEmpty ? S("sync.syncing") : phase }
        if let until = backoffUntil, until > Date() {
            return S("error.slowDown", ["n": String(Int(until.timeIntervalSinceNow) + 1)])
        }
        if state.lastError != nil, let at = state.lastErrorAt {
            return S("sync.failed", ["time": at.formatted(date: .omitted, time: .shortened)])
        }
        guard let at = state.lastSyncAt else { return S("sync.notSyncedYet") }
        let minutes = Int(-at.timeIntervalSinceNow / 60)
        if minutes < 1 {
            if lastSent > 0 && lastReceived > 0 {
                return S("sync.syncedSentNew", ["sent": String(lastSent), "received": String(lastReceived)])
            }
            if lastSent > 0 { return S("sync.syncedSent", ["sent": String(lastSent)]) }
            if lastReceived > 0 { return S("sync.syncedNew", ["received": String(lastReceived)]) }
            return S("sync.syncedJustNow")
        }
        if minutes < 60 { return S("sync.syncedMinAgo", ["n": String(minutes)]) }
        if minutes < 1440 { return S("sync.syncedHoursAgo", ["n": String(minutes / 60)]) }
        return S("sync.syncedDaysAgo", ["n": String(minutes / 1440)])
    }
}
