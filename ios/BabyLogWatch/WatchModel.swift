import Combine
import Foundation
import WatchConnectivity

/// The watch keeps no journal: it shows the summary the iPhone pushes and sends taps to the
/// phone, which writes and syncs. A tap while the phone is out of reach is queued on the watch
/// and delivered when it is back; the time of the tap travels with it. Every text comes from
/// the phone in the phone's language; the English here is only for before the first contact.
@MainActor
final class WatchModel: NSObject, ObservableObject {
    static let shared = WatchModel()

    @Published private(set) var summary: [String: Any] = [:]
    @Published var message: String? = nil
    @Published private(set) var busy = false

    private override init() {
        super.init()
        if WCSession.isSupported() {
            WCSession.default.delegate = self
            WCSession.default.activate()
            summary = WCSession.default.receivedApplicationContext
        }
    }

    // MARK: what the screen shows

    private var labels: [String: String] { (summary["labels"] as? [String: String]) ?? [:] }
    func label(_ key: String, _ fallback: String) -> String { labels[key] ?? fallback }
    var childName: String { (summary["child"] as? String) ?? "" }
    var totals: String { (summary["totals"] as? String) ?? "" }
    var quick: [Int] { (summary["quick"] as? [Int]) ?? [60, 70, 80, 90, 100, 110, 120] }
    var lastMl: Int { (summary["lastMl"] as? Int) ?? 0 }

    func lastFeedLine(_ now: Date) -> String {
        guard let at = summary["lastFeedAt"] as? Double else { return label("noFeed", "No feed yet") }
        return since(Date(timeIntervalSince1970: at), now) + " · " + ((summary["lastFeedText"] as? String) ?? "")
    }
    func lastDiaperLine(_ now: Date) -> String {
        guard let at = summary["lastDiaperAt"] as? Double else { return label("noDiaper", "No diaper yet") }
        return since(Date(timeIntervalSince1970: at), now) + " · " + ((summary["lastDiaperText"] as? String) ?? "")
    }
    private func since(_ date: Date, _ now: Date) -> String {
        let minutes = max(0, Int(now.timeIntervalSince(date) / 60))
        let body: String
        if minutes < 60 {
            body = fill(label("minutes", "{m} m"), ["m": String(minutes)])
        } else if minutes < 1440 {
            body = fill(label("hoursMinutes", "{h} h {m} m"), ["h": String(minutes / 60), "m": String(minutes % 60)])
        } else {
            body = fill(label("daysHours", "{d} d {h} h"), ["d": String(minutes / 1440), "h": String((minutes % 1440) / 60)])
        }
        return fill(label("ago", "{since} ago"), ["since": body])
    }
    private func fill(_ template: String, _ args: [String: String]) -> String {
        var text = template
        for (k, v) in args { text = text.replacingOccurrences(of: "{" + k + "}", with: v) }
        return text
    }

    // MARK: sending

    /// Send one entry to the phone and return the text to show or speak. Reachable phone: the
    /// phone writes it and answers at once. Otherwise the entry is queued on the watch.
    func log(_ payload: [String: Any]) async -> String {
        var p = payload
        p["op"] = "log"
        p["at"] = Date().timeIntervalSince1970
        guard WCSession.isSupported() else { return label("noPhone", "iPhone not reachable") }
        let session = WCSession.default
        // activate() is asynchronous; a Siri phrase on a cold launch gets here first, and
        // transferUserInfo on an unactivated session is a programmer error. Wait, briefly.
        var waited = 0
        while session.activationState != .activated && waited < 50 {
            try? await Task.sleep(nanoseconds: 100_000_000)
            waited += 1
        }
        guard session.activationState == .activated else { return label("noPhone", "iPhone not reachable") }
        if session.isReachable {
            busy = true
            defer { busy = false }
            let sentText = label("sent", "Sent to iPhone")
            let reply: [String: Any]? = await withCheckedContinuation { cont in
                var done = false
                session.sendMessage(p, replyHandler: { r in
                    if !done { done = true; cont.resume(returning: r) }
                }, errorHandler: { error in
                    // A late or failed *reply* means the phone received and wrote the entry;
                    // queueing it again would log the same tap twice.
                    let code = (error as? WCError)?.code
                    let delivered = code == .messageReplyTimedOut || code == .messageReplyFailed
                    if !done { done = true; cont.resume(returning: delivered ? ["text": sentText] : nil) }
                })
            }
            if let r = reply {
                if (r["ok"] as? Bool) == true { summary = r }
                return (r["text"] as? String) ?? ""
            }
        }
        session.transferUserInfo(p)
        return label("queued", "Saved on the watch; sends when the iPhone is near")
    }

    /// Show a line under the title for a few seconds.
    func flash(_ text: String) {
        message = text
        Task { [weak self] in
            try? await Task.sleep(nanoseconds: 5_000_000_000)
            if self?.message == text { self?.message = nil }
        }
    }
}

extension WatchModel: WCSessionDelegate {
    nonisolated func session(_ session: WCSession, activationDidCompleteWith activationState: WCSessionActivationState,
                             error: Error?) {
        let context = session.receivedApplicationContext
        Task { @MainActor in
            if !context.isEmpty { self.summary = context }
        }
    }
    nonisolated func session(_ session: WCSession, didReceiveApplicationContext applicationContext: [String: Any]) {
        Task { @MainActor in
            self.summary = applicationContext
        }
    }
}
