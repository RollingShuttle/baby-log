import Combine
import SwiftUI

/// One screen: the last feed and diaper, four big buttons, and a feed picker. The phone's
/// summary supplies every text, so the watch follows the phone's language.
struct WatchRootView: View {
    @EnvironmentObject var model: WatchModel
    @State private var showFeed = false
    @State private var now = Date()
    private let clock = Timer.publish(every: 30, on: .main, in: .common).autoconnect()

    var body: some View {
        // watchOS shows the title, and a sheet's Cancel button, only inside a NavigationStack.
        NavigationStack {
            ScrollView {
            VStack(spacing: 8) {
                if let message = model.message {
                    Text(message).font(.footnote).foregroundStyle(.secondary).multilineTextAlignment(.center)
                }
                VStack(alignment: .leading, spacing: 2) {
                    Text(model.label("lastFeed", "Last feed")).font(.caption2).foregroundStyle(.secondary)
                    Text(model.lastFeedLine(now)).font(.footnote)
                    Text(model.label("lastDiaper", "Last diaper")).font(.caption2).foregroundStyle(.secondary)
                    Text(model.lastDiaperLine(now)).font(.footnote)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                HStack(spacing: 6) {
                    big(model.label("wet", "Wet"), .teal) { send(["type": "diaper", "wet": true, "dirty": false]) }
                    big(model.label("dirty", "Dirty"), .brown) { send(["type": "diaper", "wet": false, "dirty": true]) }
                }
                HStack(spacing: 6) {
                    big(model.label("both", "Both"), .orange) { send(["type": "diaper", "wet": true, "dirty": true]) }
                    big(model.label("feed", "Feed"), .blue) { showFeed = true }
                }
                if !model.totals.isEmpty {
                    Text(model.totals).font(.caption2).foregroundStyle(.secondary).multilineTextAlignment(.center)
                }
            }
            }
            .navigationTitle(model.childName.isEmpty ? "Baby Log" : model.childName)
        }
        .onReceive(clock) { now = $0 }
        .sheet(isPresented: $showFeed) {
            NavigationStack {
                FeedPicker { ml in
                    showFeed = false
                    send(["type": "feed", "ml": ml])
                }
            }
        }
        .disabled(model.busy)
    }

    private func big(_ title: String, _ color: Color, _ action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Text(title)
                .font(.headline)
                .lineLimit(1)
                .minimumScaleFactor(0.7)
                .frame(maxWidth: .infinity, minHeight: 40)
        }
        .buttonStyle(.borderedProminent)
        .tint(color)
    }
    private func send(_ payload: [String: Any]) {
        Task {
            let text = await model.log(payload)
            model.flash(text)
        }
    }
}

/// The quick amounts as a list, the last amount first.
struct FeedPicker: View {
    @EnvironmentObject var model: WatchModel
    let pick: (Int) -> Void

    var body: some View {
        List {
            ForEach(amounts, id: \.self) { ml in
                Button { pick(ml) } label: { Text(verbatim: "\(ml) ml") }
            }
        }
        .navigationTitle(model.label("feed", "Feed"))
    }
    private var amounts: [Int] {
        var list = model.quick
        if model.lastMl > 0 {
            list.removeAll { $0 == model.lastMl }
            list.insert(model.lastMl, at: 0)
        }
        return list
    }
}
