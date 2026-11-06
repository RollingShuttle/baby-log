import SwiftUI

/// What the sheet edits: a new entry of one kind, or an existing record's fields.
struct EntryDraft: Identifiable {
    let id = UUID()
    var kind: String            // feed | diaper | note | (any other type: time and note only)
    var editing: Record?
    var time: Date
    var ml: Int
    var formula: String
    var wet: Bool
    var dirty: Bool
    var note: String

    init(kind: String, ml: Int = 0, formula: String = "") {
        self.kind = kind
        editing = nil
        time = Date()
        self.ml = ml
        self.formula = formula
        wet = true
        dirty = false
        note = ""
    }
    init(editing rec: Record) {
        kind = rec.type
        editing = rec
        time = rec.instant ?? Date()
        ml = Int(rec.bottleMl.rounded())
        formula = rec.formula ?? ""
        wet = rec.wet
        dirty = rec.dirty
        note = rec.note
    }
}

struct EntrySheet: View {
    @EnvironmentObject var model: AppModel
    @Environment(\.dismiss) private var dismiss
    @State private var d: EntryDraft
    @State private var confirmDelete = false

    init(draft: EntryDraft) {
        _d = State(initialValue: draft)
    }

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    DatePicker(S("editor.start"), selection: $d.time, displayedComponents: [.date, .hourAndMinute])
                    Button(S("editor.now")) { d.time = Date() }
                }
                if d.kind == "feed" { feedSections }
                if d.kind == "diaper" { diaperSection }
                Section(S("editor.note")) {
                    TextField(S("editor.note"), text: $d.note, axis: .vertical)
                }
                if d.editing != nil {
                    Section {
                        Button(S("swipe.delete"), role: .destructive) { confirmDelete = true }
                    }
                }
            }
            .navigationTitle(title)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button(S("editor.cancel")) { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button(d.editing == nil ? S("editor.save") : S("editor.saveChanges")) { save() }
                        .disabled(!canSave)
                }
            }
            .confirmationDialog(S("editor.confirmDelete", ["type": model.typeName(d.kind), "time": model.timeText(d.time)]),
                                isPresented: $confirmDelete, titleVisibility: .visible) {
                Button(S("swipe.delete"), role: .destructive) {
                    if let rec = d.editing { model.delete(rec) }
                    dismiss()
                }
            }
        }
    }

    private var title: String {
        d.editing == nil ? S("editor.newTitle", ["type": model.typeName(d.kind)]) : model.typeName(d.kind)
    }
    private var canSave: Bool {
        switch d.kind {
        case "feed": return d.ml > 0
        case "note": return !d.note.isEmpty
        default: return true
        }
    }

    @ViewBuilder private var feedSections: some View {
        Section(S("settings.quickAmounts")) {
            Chips(items: model.quickAmounts.map { String($0) }, selected: String(d.ml)) { d.ml = Int($0) ?? d.ml }
            HStack {
                TextField("ml", value: $d.ml, format: .number).keyboardType(.numberPad)
                Text(S("settings.unitMl")).foregroundStyle(.secondary)
            }
        }
        Section(S("feed.formulaName")) {
            Chips(items: model.formulaChoices, selected: d.formula) { d.formula = $0 }
            TextField(S("feed.formulaNamePlaceholder"), text: $d.formula)
        }
    }
    private var diaperSection: some View {
        Section(S("type.diaper")) {
            Picker(S("type.diaper"), selection: diaperKind) {
                Text(S("log.wet")).tag(0)
                Text(S("log.dirty")).tag(1)
                Text(S("log.both")).tag(2)
            }
            .pickerStyle(.segmented)
            .labelsHidden()
        }
    }
    private var diaperKind: Binding<Int> {
        Binding(get: { d.wet && d.dirty ? 2 : (d.dirty ? 1 : 0) },
                set: { v in
                    d.wet = v != 1
                    d.dirty = v != 0
                })
    }

    private func save() {
        switch d.kind {
        case "feed":
            model.logFeed(ml: d.ml, formula: d.formula, time: d.time, note: d.note, editing: d.editing)
        case "diaper":
            model.logDiaper(wet: d.wet || !d.dirty, dirty: d.dirty, time: d.time, note: d.note, editing: d.editing)
        case "note":
            model.logNote(text: d.note, time: d.time, editing: d.editing)
        default:
            if let rec = d.editing { model.saveOther(time: d.time, note: d.note, editing: rec) }
        }
        dismiss()
    }
}

/// A row of tappable chips; the selected one is tinted. Borderless buttons, so each chip
/// answers for itself inside a Form row.
struct Chips: View {
    let items: [String]
    let selected: String
    let pick: (String) -> Void

    var body: some View {
        LazyVGrid(columns: [GridItem(.adaptive(minimum: 64))], spacing: 8) {
            ForEach(items, id: \.self) { item in
                Button {
                    pick(item)
                } label: {
                    Text(item)
                        .font(.body.weight(.semibold))
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 10)
                }
                .buttonStyle(.borderless)
                .background(item == selected ? Color.accentColor.opacity(0.25) : Color.secondary.opacity(0.12),
                            in: RoundedRectangle(cornerRadius: 10))
            }
        }
        .padding(.vertical, 4)
    }
}
