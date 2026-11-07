import SwiftUI

@main
struct BabyLogApp: App {
    @StateObject private var model = AppModel.shared
    @Environment(\.scenePhase) private var scenePhase

    init() {
        // The watch's message launches this app in the background, where no scene may be
        // built; the model (and with it the WCSession) must exist from launch.
        _ = AppModel.shared
    }

    var body: some Scene {
        WindowGroup {
            RootView().environmentObject(model)
        }
        .onChange(of: scenePhase) { _, phase in
            if phase == .active { model.becameActive() }
        }
    }
}
