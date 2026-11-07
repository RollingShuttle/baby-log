import AppIntents
import Foundation

/// Siri, the Shortcuts app and the Action button on the iPhone: "Log a wet diaper in Baby Log",
/// "Log a feed in Baby Log" (Siri asks for the amount). An Apple Watch needs its own watchOS
/// target declaring the same shortcuts; that is a later stage. They run inside
/// the app's own process, write the same journal through AppModel, and sync at once. Phrases
/// are literals by Apple's rule (AppShortcuts.xcstrings carries the Chinese ones); the spoken
/// answers come from the string table.
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
        let model = AppModel.shared
        await model.ready()
        guard model.child != nil else {
            return .result(dialog: IntentDialog(stringLiteral: S("siri.noChildYet")))
        }
        let written = model.logDiaper(wet: kind != .dirty, dirty: kind != .wet, time: Date(), note: "")
        await syncNow(model)
        let text = written.map {
            S("siri.loggedDiaper", ["description": model.describe($0), "time": model.timeText($0.instant)])
        } ?? S("error.notSavedStorageFull")
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
        let model = AppModel.shared
        await model.ready()
        guard model.child != nil else {
            return .result(dialog: IntentDialog(stringLiteral: S("siri.noChildYet")))
        }
        // Out of range: Siri asks for the amount again and re-runs perform.
        guard ml > 0 && ml < 1000 else { throw $ml.needsValueError() }
        let written = model.logFeed(ml: ml, formula: model.formulaChoices.first ?? "", made: nil,
                                    time: Date(), note: "")
        await syncNow(model)
        let text = written.map {
            S("siri.loggedFeed", ["amount": S("amount.ml", ["n": String(ml)]), "time": model.timeText($0.instant)])
        } ?? S("error.notSavedStorageFull")
        return .result(dialog: IntentDialog(stringLiteral: text))
    }
}

/// On a cold launch the startup sync is already in flight when `ready()` returns, and the
/// write's own `requestSync` has just cancelled it; `SyncEngine.sync()` would return at its
/// busy guard before the new file went up. Wait for it to unwind, then run one sync, so the
/// answer is spoken after the upload.
@MainActor
private func syncNow(_ model: AppModel) async {
    while model.sync.busy { try? await Task.sleep(nanoseconds: 100_000_000) }
    await model.sync.sync()
}

struct BabyLogShortcuts: AppShortcutsProvider {
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
