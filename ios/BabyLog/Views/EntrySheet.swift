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
    var madeText: String        // the bottle prepared, optional
    var madeOz: Bool            // madeText is in oz (the formula machine's unit); stored as ml all the same
    var keptMadeText: String    // a made text this sheet filled in itself (an edit, the ml/oz switch)...
    var keptMadeMl: Int?        // ...and the exact ml it stands for, so 120 ml shown as 4.1 oz stays 120
    var leftText: String        // what was left in it, optional, ml; made - left fills the amount drunk
    var formula: String
    var wet: Bool
    var dirty: Bool
    var washed: Bool            // the bottom washed at this change
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
        madeOz = EntryDraft.madeInOz()
        keptMadeText = ""
        keptMadeMl = nil
        leftText = ""
        self.formula = formula
        wet = true
        dirty = false
        washed = false
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
        let oz = EntryDraft.madeInOz()
        let madeShown = rec.madeMl.map { oz ? EntryDraft.ozText($0) : String(Int($0.rounded())) } ?? ""
        madeOz = oz
        madeText = madeShown
        keptMadeText = madeShown
        keptMadeMl = rec.madeMl.map { Int($0.rounded()) }
        leftText = rec.leftoverMl.map { String(Int($0.rounded())) } ?? ""
        formula = rec.formula ?? ""
        wet = rec.wet
        dirty = rec.dirty
        washed = rec.washed
        weightText = rec.number("weight_g").map { String(Int($0.rounded())) } ?? ""
        lengthText = rec.number("length_cm").map { EntryDraft.trim($0) } ?? ""
        headText = rec.number("head_cm").map { EntryDraft.trim($0) } ?? ""
        note = rec.note
    }
    static func trim(_ x: Double) -> String {
        x == x.rounded() ? String(Int(x)) : String(x)
    }
    static let mlPerOz = 29.5735
    /// This phone's "Bottle made in" setting (AppModel.madeUnit writes it).
    static func madeInOz() -> Bool {
        UserDefaults.standard.string(forKey: "bl.made_unit") == "oz"
    }
    /// Whole ml for an amount in oz, half up: 4 oz = 118 ml, 4.5 oz = 133 ml.
    static func mlFromOz(_ oz: Double) -> Int {
        Int((oz * mlPerOz).rounded())
    }
    /// An ml amount in oz to one decimal, ".0" dropped: 118 -> "4", 133 -> "4.5".
    static func ozText(_ ml: Double) -> String {
        trim((ml / mlPerOz * 10).rounded() / 10)
    }
    /// The bottle made, in ml whatever unit it was typed in. Untouched since the sheet filled
    /// it in, it is the ml it came from: an edit in oz mode must not move made_ml by a rounding.
    var made: Int? {
        if let kept = keptMadeMl, madeText == keptMadeText { return kept }
        if madeOz {
            let text = madeText.trimmingCharacters(in: .whitespaces).replacingOccurrences(of: ",", with: ".")
            // Bounded, so a pasted "1e400" cannot reach Int() and trap.
            guard let oz = Double(text), oz.isFinite, oz >= 0, oz < 1000 else { return nil }
            return EntryDraft.mlFromOz(oz)
        }
        return Int(madeText.filter { $0.isNumber })
    }
    var left: Int? { Int(leftText.filter { $0.isNumber }) }
    /// Made below leftover: refused, as on the PC.
    var madeBelowLeft: Bool {
        if let made = made, let left = left { return made < left }
        return false
    }
    var weightG: Int? { Int(weightText.filter { $0.isNumber }) }
    var lengthCm: Double? { Double(lengthText.replacingOccurrences(of: ",", with: ".")) }
    var headCm: Double? { Double(headText.replacingOccurrences(of: ",", with: ".")) }
}

struct EntrySheet: View {
    @EnvironmentObject var model: AppModel
    @Environment(\.dismiss) private var dismiss
    @State private var d: EntryDraft
    @State private var confirmDelete = false
    @State private var skipMadeRecompute = false   // the made text was converted by the ml/oz switch
    @FocusState private var focus: Field?

    private enum Field: Hashable {
        case ml, made, left, weight, length, head
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
                // The amount set by hand (typed, or a chip) with the bottle known: the leftover
                // follows. Not while made/left are being typed — they are what set the amount.
                if focus != .made && focus != .left, let made = d.made {
                    d.leftText = made >= d.ml ? String(made - d.ml) : ""
                }
            }
            // Made and left both typed: the amount drunk is the difference, as on the PC.
            // Not after the ml/oz switch: its one-decimal rounding (120 ml reads 4.1 oz) must not
            // move the amount drunk, and the field may still have the focus when it is tapped.
            .onChange(of: d.madeText) { _, _ in
                if skipMadeRecompute {
                    skipMadeRecompute = false
                    return
                }
                amountFromBottle(typing: .made)
            }
            .onChange(of: d.leftText) { _, _ in amountFromBottle(typing: .left) }
        }
    }

    private var title: String {
        d.editing == nil ? S("editor.newTitle", ["type": model.typeName(d.kind)]) : model.typeName(d.kind)
    }
    private var canSave: Bool {
        switch d.kind {
        case "feed": return d.ml > 0 && !d.madeBelowLeft
        case "note": return !d.note.isEmpty
        case "growth": return (d.weightG ?? 0) > 0 || (d.lengthCm ?? 0) > 0 || (d.headCm ?? 0) > 0
        default: return true
        }
    }
    /// Made or left being typed, with both known: the amount drunk is made - left. Only while
    /// that field has the focus, so the amount's own change (which moves the leftover) cannot
    /// bounce back here.
    private func amountFromBottle(typing field: Field) {
        guard focus == field, let made = d.made, let left = d.left, made >= left else { return }
        let drunk = made - left
        let text = drunk > 0 ? String(drunk) : ""
        if d.mlText != text { d.mlText = text }
    }
    /// The made row's ml/oz switch: what is typed is converted (118 ml reads 4), and the choice
    /// becomes this phone's setting. Focus is dropped so the field reopens with the right keypad.
    private var madeUnitSwitch: Binding<Bool> {
        Binding(get: { d.madeOz },
                set: { oz in
                    guard oz != d.madeOz else { return }
                    let ml = d.made
                    d.madeOz = oz
                    let text = ml.map { oz ? EntryDraft.ozText(Double($0)) : String($0) } ?? ""
                    d.keptMadeText = text
                    d.keptMadeMl = ml
                    if text != d.madeText {
                        skipMadeRecompute = true
                        d.madeText = text
                    }
                    if focus == .made { focus = nil }
                    model.madeUnit = oz ? "oz" : "ml"
                })
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
                    .keyboardType(d.madeOz ? .decimalPad : .numberPad)
                    .multilineTextAlignment(.trailing)
                    .focused($focus, equals: .made)
                // The unit beside the field is the switch itself; leftover and amount stay ml.
                Picker(S("settings.madeUnit"), selection: madeUnitSwitch) {
                    Text(S("settings.unitMl")).tag(false)
                    Text(S("settings.unitOz")).tag(true)
                }
                .pickerStyle(.segmented)
                .labelsHidden()
                .fixedSize()
            }
            if d.madeOz, let made = d.made, made > 0 {
                Text("≈ " + S("amount.ml", ["n": String(made)]))
                    .font(.footnote).foregroundStyle(.secondary)
            }
            HStack {
                Text(S("feed.leftover"))
                TextField(S("amount.field"), text: $d.leftText)
                    .keyboardType(.numberPad)
                    .multilineTextAlignment(.trailing)
                    .focused($focus, equals: .left)
                Text(S("settings.unitMl")).foregroundStyle(.secondary)
            }
            if d.madeBelowLeft {
                Text(S("validate.madeLessThanLeftover"))
                    .font(.footnote).foregroundStyle(.red)
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
            Toggle(S("diaper.washed"), isOn: $d.washed)
        }
    }
    private var growthSection: some View {
        Section(S("tab.growth")) {
            HStack {
                Text(S("growth.weightG"))
                TextField(S("amount.field"), text: $d.weightText)
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
                TextField(S("amount.field"), text: $d.lengthText)
                    .keyboardType(.decimalPad)
                    .multilineTextAlignment(.trailing)
                    .focused($focus, equals: .length)
            }
            HStack {
                Text(S("growth.headCm"))
                TextField(S("amount.field"), text: $d.headText)
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
            model.logFeed(ml: d.ml, formula: d.formula, made: d.made, left: d.left, time: d.time, note: d.note, editing: d.editing)
        case "diaper":
            model.logDiaper(wet: d.wet || !d.dirty, dirty: d.dirty, washed: d.washed, time: d.time, note: d.note, editing: d.editing)
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
