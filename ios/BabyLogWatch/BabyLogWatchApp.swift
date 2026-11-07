import SwiftUI

@main
struct BabyLogWatchApp: App {
    @StateObject private var model = WatchModel.shared

    var body: some Scene {
        WindowGroup {
            WatchRootView().environmentObject(model)
        }
    }
}
