import SwiftUI

struct SettingsView: View {
    @EnvironmentObject var model: AppModel

    var body: some View {
        Form {
            Section(S("syncCard.title")) {
                if model.signedIn {
                    Text(S("syncCard.signedInAs", ["who": model.auth.account ?? ""]))
                    Button(S("syncCard.syncNow")) { model.requestSync(after: 0) }
                    Button(S("syncCard.checkAll")) { model.checkEverything() }
                    Button(S("syncCard.signOut"), role: .destructive) { model.signOut() }
                } else {
                    Text(S("syncCard.notSignedIn")).foregroundStyle(.secondary)
                    Button(S("syncCard.signInWithMicrosoft")) { model.signIn() }
                }
                Text(model.statusText).font(.footnote).foregroundStyle(.secondary)
                if let at = model.sync.state.lastSyncAt {
                    Text(S("syncCard.lastSync", ["time": at.formatted(date: .abbreviated, time: .shortened)]))
                        .font(.footnote)
                }
                if !model.journal.pending.isEmpty {
                    Text(S("syncCard.waiting", ["n": String(model.journal.pending.count)])).font(.footnote)
                }
                if let error = model.sync.state.lastError {
                    Text(error).font(.footnote).foregroundStyle(.red)
                }
            }
            Section(S("label.title")) {
                TextField(S("settings.labelPlaceholder"), text: $model.label)
                HStack {
                    Button(S("label.dad")) { model.label = "Dad" }
                    Button(S("label.mom")) { model.label = "Mom" }
                }
                .buttonStyle(.bordered)
            }
            Section(S("settings.quickAmounts")) {
                Stepper(S("settings.rangeFrom") + ": \(model.quickFrom)", value: $model.quickFrom, in: 10...400, step: 5)
                Stepper(S("settings.rangeTo") + ": \(model.quickTo)", value: $model.quickTo, in: 10...400, step: 5)
                Stepper(S("settings.rangeStep") + ": \(model.quickStep)", value: $model.quickStep, in: 5...50, step: 5)
                Text(model.quickAmounts.map { String($0) }.joined(separator: " · "))
                    .font(.footnote).foregroundStyle(.secondary)
            }
            Section(S("settings.language")) {
                Picker(S("settings.language"), selection: $model.language) {
                    Text(S("settings.languageFollowPhone")).tag("")
                    Text(S("settings.languageEnglish")).tag("en")
                    Text(S("settings.languageChinese")).tag("zh-Hans")
                }
                .pickerStyle(.inline)
                .labelsHidden()
            }
            Section(S("child.showing")) {
                if let c = model.child {
                    Text((c.string("name") ?? "") + " · " + (c.string("born") ?? ""))
                } else {
                    Text(S("now.childCreatedOnPc")).foregroundStyle(.secondary)
                }
                Text(S("settings.thisPhone") + " · " + model.device).font(.footnote).foregroundStyle(.secondary)
            }
        }
        .navigationTitle(S("tab.settings"))
    }
}
