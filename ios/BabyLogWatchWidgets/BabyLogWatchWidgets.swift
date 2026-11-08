import SwiftUI
import WidgetKit

/// The watch-face complication: a drop and the time since the last feed, counting on its own
/// (`Text(_:style: .relative)` needs no timeline). The watch app writes the last feed and diaper
/// into the shared App Group defaults and asks for a reload; a tap opens the watch app.
struct ComplicationEntry: TimelineEntry {
    let date: Date
    let lastFeedAt: Date?
    let lastFeedText: String
    let lastDiaperAt: Date?
    let lastDiaperText: String
    let title: String       // the child's name, or "Baby Log"
    let lastFeedLabel: String
    let lastDiaperLabel: String
}

enum SharedStore {
    static let suite = "group.com.rollingshuttle.babylog"

    static func read() -> ComplicationEntry {
        let d = UserDefaults(suiteName: suite)
        let feedAt = d?.object(forKey: "lastFeedAt") as? Double
        let diaperAt = d?.object(forKey: "lastDiaperAt") as? Double
        return ComplicationEntry(
            date: Date(),
            lastFeedAt: feedAt.map { Date(timeIntervalSince1970: $0) },
            lastFeedText: d?.string(forKey: "lastFeedText") ?? "",
            lastDiaperAt: diaperAt.map { Date(timeIntervalSince1970: $0) },
            lastDiaperText: d?.string(forKey: "lastDiaperText") ?? "",
            title: d?.string(forKey: "child").flatMap { $0.isEmpty ? nil : $0 } ?? "Baby Log",
            lastFeedLabel: d?.string(forKey: "lastFeedLabel") ?? "Last feed",
            lastDiaperLabel: d?.string(forKey: "lastDiaperLabel") ?? "Last diaper")
    }
}

struct ComplicationProvider: TimelineProvider {
    func placeholder(in context: Context) -> ComplicationEntry {
        ComplicationEntry(date: Date(), lastFeedAt: Date().addingTimeInterval(-8100), lastFeedText: "80 ml",
                          lastDiaperAt: Date().addingTimeInterval(-2400), lastDiaperText: "Wet",
                          title: "Baby Log", lastFeedLabel: "Last feed", lastDiaperLabel: "Last diaper")
    }
    func getSnapshot(in context: Context, completion: @escaping (ComplicationEntry) -> Void) {
        completion(context.isPreview ? placeholder(in: context) : SharedStore.read())
    }
    func getTimeline(in context: Context, completion: @escaping (Timeline<ComplicationEntry>) -> Void) {
        // One entry is enough: the relative text keeps counting, and the app reloads on change.
        completion(Timeline(entries: [SharedStore.read()], policy: .never))
    }
}

struct ComplicationView: View {
    @Environment(\.widgetFamily) private var family
    let entry: ComplicationEntry

    var body: some View {
        Group {
            switch family {
            case .accessoryCorner:
                Image(systemName: "drop.fill")
                    .font(.title3)
                    .widgetLabel { sinceFeed }
            case .accessoryRectangular:
                VStack(alignment: .leading, spacing: 1) {
                    Label(entry.title, systemImage: "drop.fill").font(.headline)
                    HStack(spacing: 4) {
                        Text(entry.lastFeedLabel).foregroundStyle(.secondary)
                        sinceFeed
                    }
                    .font(.caption2)
                    if !entry.lastFeedText.isEmpty {
                        Text(entry.lastFeedText).font(.caption2).foregroundStyle(.secondary)
                    }
                }
            case .accessoryInline:
                Label {
                    sinceFeed
                } icon: {
                    Image(systemName: "drop.fill")
                }
            default:    // .accessoryCircular
                ZStack {
                    AccessoryWidgetBackground()
                    VStack(spacing: 0) {
                        Image(systemName: "drop.fill").font(.caption)
                        sinceFeedShort.font(.caption2).minimumScaleFactor(0.6)
                    }
                }
            }
        }
        .containerBackground(for: .widget) { Color.clear }
    }

    /// "2 hr, 15 min" that keeps counting; a dash before the first feed.
    private var sinceFeed: Text {
        if let at = entry.lastFeedAt { return Text(at, style: .relative) }
        return Text("—")
    }
    /// The same, as a short timer for the small circle.
    private var sinceFeedShort: Text {
        if let at = entry.lastFeedAt { return Text(at, style: .timer) }
        return Text("—")
    }
}

struct BabyLogComplication: Widget {
    let kind = "BabyLogComplication"

    var body: some WidgetConfiguration {
        StaticConfiguration(kind: kind, provider: ComplicationProvider()) { entry in
            ComplicationView(entry: entry)
        }
        .configurationDisplayName("Baby Log")
        .description("Time since the last feed; tap to log.")
        .supportedFamilies([.accessoryCircular, .accessoryCorner, .accessoryRectangular, .accessoryInline])
    }
}

@main
struct BabyLogWatchWidgetBundle: WidgetBundle {
    var body: some Widget {
        BabyLogComplication()
    }
}
