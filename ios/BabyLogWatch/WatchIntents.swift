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

/// Fixed-kind diapers, so each kind has its own spoken variants (记一次尿 / 拉屎 / 都有 ...).
struct LogWetDiaperIntent: AppIntent {
    static var title: LocalizedStringResource = "Log a wet diaper"
    static var description = IntentDescription("Logs a wet diaper now.")

    init() {}

    @MainActor
    func perform() async throws -> some IntentResult & ProvidesDialog {
        try await LogDiaperIntent(kind: .wet).perform()
    }
}

struct LogDirtyDiaperIntent: AppIntent {
    static var title: LocalizedStringResource = "Log a dirty diaper"
    static var description = IntentDescription("Logs a dirty diaper now.")

    init() {}

    @MainActor
    func perform() async throws -> some IntentResult & ProvidesDialog {
        try await LogDiaperIntent(kind: .dirty).perform()
    }
}

struct LogBothDiaperIntent: AppIntent {
    static var title: LocalizedStringResource = "Log a wet and dirty diaper"
    static var description = IntentDescription("Logs a wet and dirty diaper now.")

    init() {}

    @MainActor
    func perform() async throws -> some IntentResult & ProvidesDialog {
        try await LogDiaperIntent(kind: .both).perform()
    }
}

struct BabyLogWatchShortcuts: AppShortcutsProvider {
    static var appShortcuts: [AppShortcut] {
        AppShortcut(intent: LogFeedIntent(),
                    phrases: [
                              "Log a feed in \(.applicationName)",
                              "Log a bottle in \(.applicationName)",
                              "Record a feed in \(.applicationName)",
                              "Add a feed in \(.applicationName)",
                              "Log feeding in \(.applicationName)",
                              "Log milk in \(.applicationName)",
                              "\(.applicationName) feed"],
                    shortTitle: "Log a feed",
                    systemImageName: "drop.fill")
        AppShortcut(intent: LogWetDiaperIntent(),
                    phrases: [
                              "Log a wet diaper in \(.applicationName)",
                              "Log a wet one in \(.applicationName)",
                              "Log a pee in \(.applicationName)",
                              "Record a wet diaper in \(.applicationName)",
                              "Add a wet diaper in \(.applicationName)",
                              "\(.applicationName) wet diaper"],
                    shortTitle: "Wet diaper",
                    systemImageName: "drop")
        AppShortcut(intent: LogDirtyDiaperIntent(),
                    phrases: [
                              "Log a dirty diaper in \(.applicationName)",
                              "Log a poop in \(.applicationName)",
                              "Log a poo in \(.applicationName)",
                              "Log a bowel movement in \(.applicationName)",
                              "Record a dirty diaper in \(.applicationName)",
                              "Add a dirty diaper in \(.applicationName)",
                              "\(.applicationName) dirty diaper"],
                    shortTitle: "Dirty diaper",
                    systemImageName: "cloud.fill")
        AppShortcut(intent: LogBothDiaperIntent(),
                    phrases: [
                              "Log a wet and dirty diaper in \(.applicationName)",
                              "Log both in \(.applicationName)",
                              "Log pee and poop in \(.applicationName)",
                              "Record a wet and dirty diaper in \(.applicationName)",
                              "Add a wet and dirty diaper in \(.applicationName)"],
                    shortTitle: "Wet and dirty diaper",
                    systemImageName: "cloud.rain.fill")
        AppShortcut(intent: LogDiaperIntent(),
                    phrases: [
                              "Log a \(\.$kind) diaper in \(.applicationName)",
                              "Log a diaper in \(.applicationName)"],
                    shortTitle: "Log a diaper",
                    systemImageName: "cloud.fill")
    }
}
