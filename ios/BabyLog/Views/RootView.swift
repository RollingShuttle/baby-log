import Combine
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
                    ToolbarItem(placement: .topBarLeading) {
                        NavigationLink {
                            TrendsView()
                        } label: {
                            Image(systemName: "chart.bar")
                        }
                    }
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
            .padding(.bottom, 72)
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
