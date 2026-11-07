import Foundation
import WatchConnectivity

/// The iPhone end of the Watch app. The watch holds no journal and no sign-in: it sends "log
/// this" and gets back what was written, and the phone pushes a small summary (last feed, last
/// diaper, today, the labels in the phone's language) whenever the journal changes. A tap made
/// while the phone was out of reach arrives later through transferUserInfo, with its own time.
final class WatchBridge: NSObject, WCSessionDelegate {
    static let shared = WatchBridge()

    func start() {
        guard WCSession.isSupported() else { return }
        WCSession.default.delegate = self
        WCSession.default.activate()
    }

    /// The summary for the watch; nothing is sent when no watch app is installed.
    func push(_ context: [String: Any]) {
        guard WCSession.isSupported() else { return }
        let session = WCSession.default
        guard session.activationState == .activated, session.isPaired, session.isWatchAppInstalled else { return }
        try? session.updateApplicationContext(context)
    }

    // MARK: WCSessionDelegate (background queue; every journal access hops to the main actor)

    func session(_ session: WCSession, activationDidCompleteWith activationState: WCSessionActivationState, error: Error?) {
        Task { @MainActor in
            AppModel.shared.pushWatchSummary()
        }
    }
    func sessionDidBecomeInactive(_ session: WCSession) {}
    func sessionDidDeactivate(_ session: WCSession) {
        session.activate()
    }
    func session(_ session: WCSession, didReceiveMessage message: [String: Any],
                 replyHandler: @escaping ([String: Any]) -> Void) {
        Task { @MainActor in
            let reply = await AppModel.shared.handleWatch(message)
            replyHandler(reply)
        }
    }
    func session(_ session: WCSession, didReceiveMessage message: [String: Any]) {
        Task { @MainActor in
            _ = await AppModel.shared.handleWatch(message)
        }
    }
    func session(_ session: WCSession, didReceiveUserInfo userInfo: [String: Any] = [:]) {
        Task { @MainActor in
            _ = await AppModel.shared.handleWatch(userInfo)
        }
    }
}
