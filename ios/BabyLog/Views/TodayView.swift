import SwiftUI

struct TodayView: View {
    @EnvironmentObject var model: AppModel
    @State private var draft: EntryDraft? = nil

    var body: some View {
        List {
            Section { syncPill }
            Section { NowPanel() }
            Section(header: dayHeader) {
                if model.dayEvents.isEmpty {
                    Text(S("now.nothingLoggedYet")).foregroundStyle(.secondary)
                }
                ForEach(model.dayEvents, id: \.file) { rec in
                    Button {
                        draft = EntryDraft(editing: rec)
                    } label: {
                        EntryRow(rec: rec)
                    }
                    .buttonStyle(.plain)
                    .swipeActions(edge: .trailing) {
                        Button(role: .destructive) {
                            model.delete(rec)
                        } label: {
                            Label(S("swipe.delete"), systemImage: "trash")
                        }
                    }
                }
            }
        }
        .listStyle(.insetGrouped)
        .refreshable { await model.sync.sync() }
        .safeAreaInset(edge: .bottom) { logBar }
        .sheet(item: $draft) { d in EntrySheet(draft: d) }
    }

    private var syncPill: some View {
        Button {
            if model.signedIn { model.requestSync(after: 0) } else { model.signIn() }
        } label: {
            HStack {
                Image(systemName: model.signedIn ? "arrow.triangle.2.circlepath" : "person.crop.circle.badge.exclamationmark")
                Text(model.statusText).font(.footnote)
                Spacer()
                if model.sync.busy { ProgressView() }
            }
        }
    }

    private var dayHeader: some View {
        HStack {
            Button {
                model.day = Names.shiftDay(model.day, -1)
            } label: {
                Image(systemName: "chevron.left")
            }
            Spacer()
            Text(dayTitle)
            Spacer()
            Button {
                model.day = Names.shiftDay(model.day, 1)
            } label: {
                Image(systemName: "chevron.right")
            }
            .disabled(model.day >= Names.dayOf(Date()))
        }
        .buttonStyle(.borderless)
    }
    private var dayTitle: String {
        guard let date = Names.dateOfDay(model.day) else { return model.day }
        var text = date.formatted(.dateTime.weekday(.abbreviated).month(.abbreviated).day())
        if model.day == Names.dayOf(Date()) { text += " · " + S("day.todayMark") }
        return text
    }

    // The log bar: a feed is chip -> Save in the sheet; a diaper is one tap, logged now.
    private var logBar: some View {
        HStack(spacing: 8) {
            Button {
                draft = feedDraft()
            } label: {
                Text(S("log.feed")).frame(maxWidth: .infinity)
            }
            .buttonStyle(.borderedProminent)
            Button {
                model.logDiaper(wet: true, dirty: false, time: Date(), note: "")
            } label: {
                Text(S("log.wet")).frame(maxWidth: .infinity)
            }
            .buttonStyle(.bordered)
            Button {
                model.logDiaper(wet: false, dirty: true, time: Date(), note: "")
            } label: {
                Text(S("log.dirty")).frame(maxWidth: .infinity)
            }
            .buttonStyle(.bordered)
            Button {
                model.logDiaper(wet: true, dirty: true, time: Date(), note: "")
            } label: {
                Text(S("log.both")).frame(maxWidth: .infinity)
            }
            .buttonStyle(.bordered)
            Button {
                draft = EntryDraft(kind: "note")
            } label: {
                Image(systemName: "note.text")
            }
            .buttonStyle(.bordered)
        }
        .controlSize(.large)
        .lineLimit(1)
        .minimumScaleFactor(0.7)     // five buttons across a phone: no wrapped CJK labels
        .disabled(model.child == nil)
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
        .background(.bar)
    }
    private func feedDraft() -> EntryDraft {
        let last = model.lastFeed
        return EntryDraft(kind: "feed",
                          ml: last.map { Int($0.bottleMl.rounded()) } ?? (model.quickAmounts.first ?? 60),
                          formula: model.formulaChoices.first ?? "")
    }
}

struct NowPanel: View {
    @EnvironmentObject var model: AppModel

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            if let c = model.child {
                HStack {
                    Text(c.string("name") ?? "").font(.headline)
                    Spacer()
                    Text(model.ageText).foregroundStyle(.secondary)
                }
            } else {
                Text(S("now.childCreatedOnPc")).font(.footnote).foregroundStyle(.secondary)
            }
            row(S("now.lastFeed"),
                model.lastFeed.map { model.sinceText($0.instant) + " · " + model.describe($0) } ?? S("now.noFeedYet"))
            row(S("now.lastDiaper"),
                model.lastDiaper.map { model.sinceText($0.instant) + " · " + model.describe($0) } ?? S("now.noDiaperYet"))
            Text(model.todayTotals).font(.footnote).foregroundStyle(.secondary)
        }
        .padding(.vertical, 4)
    }
    private func row(_ title: String, _ value: String) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(title).font(.caption).foregroundStyle(.secondary)
            Text(value)
        }
    }
}

struct EntryRow: View {
    @EnvironmentObject var model: AppModel
    let rec: Record

    var body: some View {
        HStack(spacing: 10) {
            Text(model.timeText(rec.instant)).monospacedDigit().frame(width: 72, alignment: .leading)
            Image(systemName: model.icon(for: rec)).foregroundStyle(model.color(for: rec)).frame(width: 22)
            VStack(alignment: .leading, spacing: 2) {
                Text(model.describe(rec))
                if !rec.note.isEmpty && rec.type != "note" {
                    Text(rec.note).font(.caption).foregroundStyle(.secondary)
                }
            }
            Spacer()
            Text(rec.editedBy ?? rec.loggedBy ?? "").font(.caption2).foregroundStyle(.tertiary)
        }
        .contentShape(Rectangle())
    }
}
