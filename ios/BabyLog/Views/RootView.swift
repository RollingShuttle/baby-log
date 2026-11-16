import Combine
import SwiftUI

/// Three tabs along the bottom: Today, Trends, Settings. Each keeps its own navigation stack,
/// so switching away and back leaves a screen where it was.
struct RootView: View {
    @EnvironmentObject var model: AppModel
    @State private var tab = 0
    // Once a minute, so "2 h 15 m ago" and the pill's "Synced 3 min ago" stay true.
    private let clock = Timer.publish(every: 60, on: .main, in: .common).autoconnect()

    var body: some View {
        TabView(selection: $tab) {
            NavigationStack {
                TodayView()
                    .navigationTitle(S("app.name"))
                    .navigationBarTitleDisplayMode(.inline)
            }
            // Above Today's log bar, as before the tab bar.
            .overlay(alignment: .bottom) { toast(lift: 72) }
            .tabItem { Label(S("tab.today"), systemImage: "calendar") }
            .tag(0)

            NavigationStack {
                TrendsView()
            }
            .overlay(alignment: .bottom) { toast(lift: 16) }
            .tabItem { Label(S("tab.trends"), systemImage: "chart.bar.xaxis") }
            .tag(1)

            NavigationStack {
                SettingsView()
            }
            .overlay(alignment: .bottom) { toast(lift: 16) }
            .tabItem { Label(S("tab.settings"), systemImage: "gearshape") }
            .tag(2)
        }
        .onReceive(clock) { _ in model.tickMinute() }
    }

    /// The saved / deleted toast with its Undo. Each tab carries one; only the visible tab's
    /// is on screen, and its timer runs only while that tab is showing.
    @ViewBuilder private func toast(lift: CGFloat) -> some View {
        if let message = model.lastMessage {
            HStack(spacing: 14) {
                Text(message)
                if model.undoable != nil {
                    Button(S("toast.undo")) { model.undo() }
                        .fontWeight(.semibold)
                }
            }
            .font(.footnote)
            .padding(.horizontal, 14)
            .padding(.vertical, 10)
            .background(.thinMaterial, in: Capsule())
            .padding(.bottom, lift)
            .task(id: message) {
                // Six seconds for a mis-tap to be taken back; then the toast and the undo go.
                try? await Task.sleep(nanoseconds: 6_000_000_000)
                if model.lastMessage == message {
                    model.lastMessage = nil
                    model.undoable = nil
                }
            }
        }
    }
}
