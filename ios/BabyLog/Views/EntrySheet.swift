import SwiftUI

/// What the sheet edits: a new entry of one kind, or an existing record's fields. Numbers are
/// kept as the text typed, because the number pad has no Return key and a value-bound field
/// would never commit.
struct EntryDraft: Identifiable {
    let id = UUID()
    var kind: String            // feed | diaper | note | growth | (any other type: time and note only)
    var editing: Record?
    var time: Date
    var ml: Int
    var mlText: String
    var madeText: String        // the bottle prepared, optional; leftover = made - drunk
    var formula: String
    var wet: Bool
    var dirty: Bool
    var weightText: String      // grams
    var lengthText: String      // cm
    var headText: String        // cm
    var note: String

    init(kind: String, ml: Int = 0, formula: String = "") {
        self.kind = kind
        editing = nil
        time = Date()
        self.ml = ml
        mlText = ml > 0 ? String(ml) : ""
        madeText = ""
        self.formula = formula
        wet = true
        dirty = false
        weightText = ""
        lengthText = ""
        headText = ""
        note = ""
    }
    init(editing rec: Record) {
        kind = rec.type
        editing = rec
        time = rec.instant ?? Date()
        ml = Int(rec.bottleMl.rounded())
        mlText = ml > 0 ? String(ml) : ""
        madeText = rec.madeMl.map { String(Int($0.rounded())) } ?? ""
        formula = rec.formula ?? ""
        wet = rec.wet
        dirty = rec.dirty
        weightText = rec.number("weight_g").map { String(Int($0.rounded())) } ?? ""
        lengthText = rec.number("length_cm").map { EntryDraft.trim($0) } ?? ""
        headText = rec.number("head_cm").map { EntryDraft.trim($0) } ?? ""
        note = rec.note
    }
    static func trim(_ x: Double) -> String {
        x == x.rounded() ? String(Int(x)) : String(x)
    }
    var made: Int? { Int(madeText.filter { $0.isNumber }) }
    var weightG: Int? { Int(weightText.filter { $0.isNumber }) }
    var lengthCm: Double? { Double(lengthText.replacingOccurrences(of: ",", with: ".")) }
    var headCm: Double? { Double(headText.replacingOccurrences(of: ",", with: ".")) }
}

struct EntrySheet: View {
    @EnvironmentObject var model: AppModel
    @Environment(\.dismiss) private var dismiss
    @State private var d: EntryDraft
    @State private var confirmDelete = false
    @FocusState private var focus: Field?

    private enum Field: Hashable {
        case ml, made, weight, length, head
    }

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
                if d.kind == "growth" { growthSection }
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
                // The number pad has no Return key; this is how it goes away.
                ToolbarItemGroup(placement: .keyboard) {
                    Spacer()
                    Button(S("catchup.done")) { focus = nil }
                }
            }
            .confirmationDialog(S("editor.confirmDelete", ["type": model.typeName(d.kind), "time": model.timeText(d.time)]),
                                isPresented: $confirmDelete, titleVisibility: .visible) {
                Button(S("swipe.delete"), role: .destructive) {
                    if let rec = d.editing { model.delete(rec) }
                    dismiss()
                }
            }
            .onChange(of: d.mlText) { _, text in
                d.ml = Int(text.filter { $0.isNumber }) ?? 0
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
        case "growth": return (d.weightG ?? 0) > 0 || (d.lengthCm ?? 0) > 0 || (d.headCm ?? 0) > 0
        default: return true
        }
    }
    /// The feed before this one (the one being edited does not count): what was drunk, when,
    /// and what was made and left, so a bottle finished now can be read against it.
    private var previousFeed: Record? {
        model.events.last(where: { $0.type == "feed" && $0.eventId != d.editing?.eventId })
    }

    @ViewBuilder private var feedSections: some View {
        if let last = previousFeed {
            Section(S("now.lastFeed")) {
                Text(model.describe(last) + " · " + model.sinceText(last.instant))
                if let madeLeft = model.madeLeftText(last) {
                    Text(madeLeft).font(.footnote).foregroundStyle(.secondary)
                }
            }
        }
        Section(S("settings.quickAmounts")) {
            Chips(items: model.quickAmounts.map { String($0) }, selected: String(d.ml)) { picked in
                d.mlText = picked
                focus = nil
            }
            HStack {
                TextField(S("amount.field"), text: $d.mlText)
                    .keyboardType(.numberPad)
                    .focused($focus, equals: .ml)
                Text(S("settings.unitMl")).foregroundStyle(.secondary)
            }
            HStack {
                Text(S("feed.made"))
                TextField(S("amount.field"), text: $d.madeText)
                    .keyboardType(.numberPad)
                    .multilineTextAlignment(.trailing)
                    .focused($focus, equals: .made)
                Text(S("settings.unitMl")).foregroundStyle(.secondary)
            }
            if let made = d.made, made > d.ml {
                Text(S("day.madeLeft", ["made": S("amount.ml", ["n": String(made)]),
                                        "left": S("amount.ml", ["n": String(made - d.ml)])]))
                    .font(.footnote).foregroundStyle(.secondary)
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
    private var growthSection: some View {
        Section(S("tab.growth")) {
            HStack {
                Text(S("growth.weightG"))
                TextField("0", text: $d.weightText)
                    .keyboardType(.numberPad)
                    .multilineTextAlignment(.trailing)
                    .focused($focus, equals: .weight)
            }
            if let g = d.weightG, g > 0 {
                Text(S("amount.kg", ["n": String(format: "%.2f", (Double(g) / 10).rounded() / 100)]))
                    .font(.footnote).foregroundStyle(.secondary)
            }
            HStack {
                Text(S("growth.lengthCm"))
                TextField("0", text: $d.lengthText)
                    .keyboardType(.decimalPad)
                    .multilineTextAlignment(.trailing)
                    .focused($focus, equals: .length)
            }
            HStack {
                Text(S("growth.headCm"))
                TextField("0", text: $d.headText)
                    .keyboardType(.decimalPad)
                    .multilineTextAlignment(.trailing)
                    .focused($focus, equals: .head)
            }
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
            model.logFeed(ml: d.ml, formula: d.formula, made: d.made, time: d.time, note: d.note, editing: d.editing)
        case "diaper":
            model.logDiaper(wet: d.wet || !d.dirty, dirty: d.dirty, time: d.time, note: d.note, editing: d.editing)
        case "note":
            model.logNote(text: d.note, time: d.time, editing: d.editing)
        case "growth":
            model.logGrowth(weightG: d.weightG, lengthCm: d.lengthCm, headCm: d.headCm,
                            time: d.time, note: d.note, editing: d.editing)
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
