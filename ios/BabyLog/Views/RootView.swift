import SwiftUI

struct RootView: View {
    @EnvironmentObject var model: AppModel
    // Once a minute, so "2 h 15 m ago" and the pill's "Synced 3 min ago" stay true.
    private let clock = Timer.publish(every: 60, on: .main, in: .common).autoconnect()

    var body: some View {
        NavigationStack {
            TodayView()
                .navigationTitle(S("app.name"))
                .navigationBarTitleDisplayMode(.inline)
                .toolbar {
                    ToolbarItem(placement: .topBarTrailing) {
                        NavigationLink {
                            SettingsView()
                        } label: {
                            Image(systemName: "gearshape")
                        }
                    }
                }
        }
        .onReceive(clock) { _ in model.refresh() }
        .overlay(alignment: .bottom) { toast }
    }

    @ViewBuilder private var toast: some View {
        if let message = model.lastMessage {
            Text(message)
                .font(.footnote)
                .padding(.horizontal, 14)
                .padding(.vertical, 8)
                .background(.thinMaterial, in: Capsule())
                .padding(.bottom, 72)
                .onTapGesture { model.lastMessage = nil }
                .task(id: message) {
                    try? await Task.sleep(nanoseconds: 4_000_000_000)
                    if model.lastMessage == message { model.lastMessage = nil }
                }
        }
    }
}
