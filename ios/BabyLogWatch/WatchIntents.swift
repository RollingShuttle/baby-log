import AppIntents
import Foundation

/// Siri on the watch: the same phrases as on the phone. Each runs in the watch app and hands
/// the entry to the phone (or queues it); the spoken answer is the phone's.
enum DiaperKind: String, AppEnum {
    case wet
    case dirty
    case both

    static var typeDisplayRepresentation = TypeDisplayRepresentation(name: "Diaper")
    static var caseDisplayRepresentations: [DiaperKind: DisplayRepresentation] = [
        .wet: "Wet",
        .dirty: "Dirty",
        .both: "Wet and dirty",
    ]
}

struct LogDiaperIntent: AppIntent {
    static var title: LocalizedStringResource = "Log a diaper"
    static var description = IntentDescription("Logs a wet, dirty, or wet and dirty diaper now.")

    @Parameter(title: "Kind")
    var kind: DiaperKind

    init() {}
    init(kind: DiaperKind) {
        self.kind = kind
    }

    @MainActor
    func perform() async throws -> some IntentResult & ProvidesDialog {
        let text = await WatchModel.shared.log(["type": "diaper", "wet": kind != .dirty, "dirty": kind != .wet])
        WatchModel.shared.flash(text)
        return .result(dialog: IntentDialog(stringLiteral: text))
    }
}

struct LogFeedIntent: AppIntent {
    static var title: LocalizedStringResource = "Log a feed"
    static var description = IntentDescription("Logs a bottle now, with the formula used last time.")

    @Parameter(title: "Amount in ml")
    var ml: Int

    init() {}
    init(ml: Int) {
        self.ml = ml
    }

    @MainActor
    func perform() async throws -> some IntentResult & ProvidesDialog {
        guard ml > 0 && ml < 1000 else { throw $ml.needsValueError() }
        let text = await WatchModel.shared.log(["type": "feed", "ml": ml])
        WatchModel.shared.flash(text)
        return .result(dialog: IntentDialog(stringLiteral: text))
    }
}

struct BabyLogWatchShortcuts: AppShortcutsProvider {
    static var appShortcuts: [AppShortcut] {
        AppShortcut(intent: LogFeedIntent(),
                    phrases: ["Log a feed in \(.applicationName)",
                              "Log a bottle in \(.applicationName)"],
                    shortTitle: "Log a feed",
                    systemImageName: "drop.fill")
        AppShortcut(intent: LogDiaperIntent(),
                    phrases: ["Log a \(\.$kind) diaper in \(.applicationName)",
                              "Log a diaper in \(.applicationName)"],
                    shortTitle: "Log a diaper",
                    systemImageName: "cloud.fill")
    }
}
