import Foundation

/// One sex's half of the standard: ages in months and, for each age, the seven weights in kg
/// at P3, P10, P25, P50, P75, P90, P97 (`p`) and at -3..+3 SD (`sd`).
struct GrowthTable: Decodable {
    let ages: [Double]
    let p: [[Double]]
    let sd: [[Double]]

    /// The shape every lookup below indexes into; a file that breaks it hides the chart rather
    /// than crashing on an index.
    var isValid: Bool {
        guard ages.count >= 2, p.count == ages.count, sd.count == ages.count else { return false }
        for row in p where row.count != 7 { return false }
        for row in sd where row.count != 7 { return false }
        return true
    }
}

/// The bundled weight-for-age standard, WS/T 423-2022 (static/growth_wfa.json, byte for byte).
struct GrowthStandard: Decodable {
    let boy: GrowthTable
    let girl: GrowthTable

    func table(_ sex: String?) -> GrowthTable? {
        if sex == "boy" { return boy }
        if sex == "girl" { return girl }
        return nil
    }
}

/// One weighing on the weight-for-age chart, rated when the child's sex is set (AppModel).
struct WeightPoint: Identifiable {
    let id: Int
    let day: String           // YYYY-MM-DD: the writer's local date of the weighing
    let dayText: String       // the day as the phone shows dates
    let grams: Double
    let ageMonths: Double?    // nil before the birth day
    let ageText: String       // "23 days old", "1 mo 23 d"
    let z: Double?            // nil without a sex, before birth, or past 81 months
    let percentile: Double?
    let median: Double?       // P50 at that age, kg

    var kg: Double { grams / 1000 }
    var kgText: String { Growth.kgText(grams: grams) }
    var label: String? { percentile.map { Growth.pctLabel($0) } }
    var band: String? { percentile.map { Growth.band($0) } }
}

/// The chart's input: the child's sex ("boy", "girl" or nil) and the weighings, birth first.
struct WeightChart {
    let sex: String?
    let points: [WeightPoint]
}

/// The arithmetic of the weight-for-age chart, line for line tools/growth_standard.py (and
/// static/growth.js): the same operations in the same order, so all three agree with
/// tests/fixtures/growth_cases.json.
enum Growth {
    static let daysPerMonth = 30.4375   // 365.25 / 12: the standard's ages are whole months
    static let percentiles = [3, 10, 25, 50, 75, 90, 97]
    /// Decoded once; nil when the file is missing or malformed, and the chart is then not shown.
    static let standard: GrowthStandard? = load()

    private static func load() -> GrowthStandard? {
        guard let url = Bundle.main.url(forResource: "growth_wfa", withExtension: "json"),
              let data = try? Data(contentsOf: url),
              let std = try? JSONDecoder().decode(GrowthStandard.self, from: data),
              std.boy.isValid, std.girl.isValid else { return nil }
        return std
    }

    // -- dates: plain integers on the proleptic Gregorian calendar, so no time zone or DST
    // change can move a day (the JS side works on Date.UTC for the same reason)

    /// Year, month and day of a string's first ten characters, "YYYY-MM-DD".
    static func ymd(_ day: String) -> (y: Int, m: Int, d: Int)? {
        let parts = day.prefix(10).split(separator: "-")
        guard parts.count == 3, let y = Int(parts[0]), let m = Int(parts[1]), let d = Int(parts[2]),
              m >= 1, m <= 12, d >= 1, d <= 31 else { return nil }
        return (y: y, m: m, d: d)
    }
    /// Days since 1970-01-01 (H. Hinnant's days_from_civil). A day past the month's end rolls
    /// into the next month, as Date.UTC does.
    static func civilDays(_ year: Int, _ month: Int, _ day: Int) -> Int {
        let y = month <= 2 ? year - 1 : year
        let era = (y >= 0 ? y : y - 399) / 400
        let yoe = y - era * 400
        let mp = (month + 9) % 12                 // March = 0
        let doy = (153 * mp + 2) / 5 + day - 1
        let doe = yoe * 365 + yoe / 4 - yoe / 100 + doy
        return era * 146097 + doe - 719468
    }
    /// Whole days from `born` to `day`, negative before birth.
    static func ageDays(born: String, day: String) -> Int? {
        guard let b = ymd(born), let t = ymd(day) else { return nil }
        return civilDays(t.y, t.m, t.d) - civilDays(b.y, b.m, b.d)
    }
    /// Months between two dates as whole days / 30.4375; nil before birth.
    static func ageMonths(born: String, day: String) -> Double? {
        guard let d = ageDays(born: born, day: day), d >= 0 else { return nil }
        return Double(d) / daysPerMonth
    }
    /// Whole calendar months since birth, anchored on the birth's day of the month, and the
    /// days left over; nil before birth. An anniversary that has not come yet, or that rolled
    /// past a short month (born on the 31st), is not a month yet (growth.js ageParts).
    static func ageParts(born: String, day: String) -> (months: Int, days: Int)? {
        guard let b = ymd(born), let t = ymd(day) else { return nil }
        let target = civilDays(t.y, t.m, t.d)
        guard target >= civilDays(b.y, b.m, b.d) else { return nil }
        var months = (t.y - b.y) * 12 + t.m - b.m
        while months > 0 && anniversary(b.y, b.m, b.d, months) > target { months -= 1 }
        return (months: months, days: target - anniversary(b.y, b.m, b.d, months))
    }
    /// civilDays of the birth day `months` months on: Date.UTC(by, bm + months, bd).
    private static func anniversary(_ y: Int, _ m: Int, _ d: Int, _ months: Int) -> Int {
        let total = m - 1 + months                // >= 0: months is never negative here
        return civilDays(y + total / 12, total % 12 + 1, 1) + d - 1
    }

    // -- the standard

    /// The 7 values at a fractional age, linear between the two table rows around it; nil
    /// outside 0..81 months.
    static func rowAt(_ rows: [[Double]], _ ages: [Double], _ age: Double) -> [Double]? {
        guard ages.count >= 2, rows.count == ages.count, age >= 0, age <= ages[ages.count - 1] else { return nil }
        var i = 0
        while i < ages.count - 2 && ages[i + 1] <= age { i += 1 }
        let f = (age - ages[i]) / (ages[i + 1] - ages[i])
        let a = rows[i]
        let b = rows[i + 1]
        var out: [Double] = []
        for k in 0..<min(a.count, b.count) { out.append(a[k] + (b[k] - a[k]) * f) }
        return out
    }
    /// The weight's SD score: linear between the -3..+3 SD values at that age, and beyond them
    /// along the outermost step. Nil for an unknown sex or an age outside the table.
    static func zScore(_ std: GrowthStandard, sex: String?, age: Double?, kg: Double?) -> Double? {
        guard let t = std.table(sex), let age = age, let kg = kg,
              let s = rowAt(t.sd, t.ages, age), s.count == 7 else { return nil }
        var z = 3.0
        if kg <= s[0] {
            z = -3 - (s[0] - kg) / (s[1] - s[0])
        } else if kg >= s[6] {
            z = 3 + (kg - s[6]) / (s[6] - s[5])
        } else {
            for i in 0..<6 where kg <= s[i + 1] {
                z = Double(i - 3) + (kg - s[i]) / (s[i + 1] - s[i])
                break
            }
        }
        return z.isFinite ? z : nil
    }
    /// The share of children below this SD score, 0..100.
    static func percentile(_ z: Double) -> Double {
        50 * (1 + erf(z / 2.0.squareRoot()))
    }
    /// The standard's Table 1 rating of the exact percentile: upper (>= P97), above
    /// (P75-P97), average (P25-P75), below (P3-P25), lower (< P3).
    static func band(_ pc: Double) -> String {
        if pc >= 97 { return "upper" }
        if pc >= 75 { return "above" }
        if pc >= 25 { return "average" }
        if pc >= 3 { return "below" }
        return "lower"
    }
    /// The percentile as shown: "<1", ">99", or the whole number below it. Truncated, not
    /// rounded, so the number always sits in the band shown (24.99 reads 24, Below average).
    static func pctLabel(_ pc: Double) -> String {
        if !(pc >= 1) { return "<1" }             // NaN lands here too, never in Int()
        if pc > 99 { return ">99" }
        return String(Int(floor(pc)))
    }
    /// The range switch's default: the smallest of 6, 12, 24 months that holds the latest
    /// weighing with half a month to spare, else the whole standard (81 months).
    static func defaultRange(latestAge: Double?) -> Int {
        guard let age = latestAge else { return 6 }
        for end in [6, 12, 24] where Double(end) >= age + 0.5 { return end }
        return 81
    }

    // -- texts: two decimals, half up, as the rest of the app rounds (rollup._round_half_up_to)

    /// A weight in grams as kg with two decimals, rounded from the grams so 3335 g is 3.34.
    static func kgText(grams: Double) -> String {
        String(format: "%.2f", floor(grams / 10 + 0.5) / 100)
    }
    /// Two decimals, half up, never "-0.00".
    static func fixed2(_ x: Double) -> String {
        let r = floor(x * 100 + 0.5) / 100
        let v: Double = r == 0 ? 0 : r
        return String(format: "%.2f", v)
    }
}
