import Charts
import SwiftUI

/// The weight-for-age section at the top of Trends (China's standard WS/T 423-2022): the latest
/// weighing's percentile and rating, the standard's P3..P97 curves with the child's weighings
/// on them, and every weighing as a list. The range switch is the caller's state, so a choice
/// survives the redraws a sync or the minute tick causes.
struct WeightForAgeSection: View {
    let chart: WeightChart
    @Binding var range: Int?

    var body: some View {
        let table = Growth.standard?.table(chart.sex)
        let latest = chart.points.last
        let end = range ?? Growth.defaultRange(latestAge: latest?.ageMonths)
        Section {
            if chart.points.isEmpty {
                Text(S("growth.noWeightsYet")).foregroundStyle(.secondary)
            } else {
                if chart.sex == nil {
                    Text(S("growth.needSex")).font(.footnote).foregroundStyle(.secondary)
                } else if let t = table, let last = latest {
                    verdict(last)
                    Picker(S("growth.wfaTitle"), selection: Binding<Int>(get: { end }, set: { range = $0 })) {
                        Text(S("growth.range6")).tag(6)
                        Text(S("growth.range12")).tag(12)
                        Text(S("growth.range24")).tag(24)
                        Text(S("growth.rangeAll")).tag(81)
                    }
                    .pickerStyle(.segmented)
                    .labelsHidden()
                    curves(t, end: end)
                }
                ForEach(chart.points.reversed()) { p in
                    row(p)
                }
            }
        } header: {
            Text(S("growth.wfaTitle"))
        } footer: {
            if table != nil && !chart.points.isEmpty {
                VStack(alignment: .leading, spacing: 4) {
                    Text(S("growth.wfaLegend"))
                    Text(S("growth.ratingNote"))
                    Text(S("growth.wfaSource"))
                }
                .font(.caption)
            }
        }
    }

    // -- the verdict on the latest weighing

    @ViewBuilder
    private func verdict(_ p: WeightPoint) -> some View {
        if let age = p.ageMonths, age > 81 {
            Text(S("growth.pastStandard")).font(.footnote).foregroundStyle(.secondary)
        } else if let label = p.label, let band = p.band {
            let normal = band == "above" || band == "average" || band == "below"
            let tint = normal ? Color.green : Color.orange
            VStack(alignment: .leading, spacing: 6) {
                Text(S("growth.latest", ["date": p.dayText, "age": p.ageText]))
                    .font(.footnote)
                    .foregroundStyle(.secondary)
                Text(S("amount.kg", ["n": p.kgText]) + " · " + S("growth.percentile", ["n": label]))
                    .font(.title3.weight(.semibold))
                Text(WeightForAgeSection.bandName(band) + " · "
                     + (normal ? S("growth.inRange") : S("growth.outOfRange")))
                    .font(.footnote.weight(.semibold))
                    .foregroundStyle(tint)
                    .padding(.horizontal, 10)
                    .padding(.vertical, 4)
                    .background(tint.opacity(0.15), in: Capsule())
                if let z = p.z, let median = p.median {
                    Text(S("growth.zMedian", ["z": Growth.fixed2(z),
                                              "median": S("amount.kg", ["n": Growth.fixed2(median)])]))
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                }
            }
            .padding(.vertical, 2)
        }
    }

    /// The standard's Table 1 names; spelled out so every key is a literal the tests can check.
    static func bandName(_ band: String) -> String {
        switch band {
        case "upper": return S("growth.band.upper")
        case "above": return S("growth.band.above")
        case "average": return S("growth.band.average")
        case "below": return S("growth.band.below")
        default: return S("growth.band.lower")
        }
    }

    // -- one weighing in the list, newest first

    private func row(_ p: WeightPoint) -> some View {
        HStack(alignment: .firstTextBaseline) {
            VStack(alignment: .leading, spacing: 2) {
                Text(p.dayText)
                Text(p.ageText).font(.caption).foregroundStyle(.secondary)
            }
            Spacer()
            VStack(alignment: .trailing, spacing: 2) {
                Text(S("amount.kg", ["n": p.kgText])).monospacedDigit()
                if let label = p.label, let band = p.band {
                    Text(S("growth.percentile", ["n": label]) + " · " + WeightForAgeSection.bandName(band))
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
        }
        .font(.footnote)
    }

    // -- the chart

    private struct CurvePoint: Identifiable {
        let id: Int
        let series: String
        let age: Double
        let kg: Double
        let bold: Bool
    }
    private struct BandPoint: Identifiable {
        let id: Int
        let age: Double
        let low: Double
        let high: Double
    }
    private struct ChildPoint: Identifiable {
        let id: Int
        let age: Double
        let kg: Double
    }

    /// The curves are straight between the table's rows (the arithmetic interpolates linearly),
    /// so the rows themselves are the exact polyline: 7 to 44 points a curve instead of a fine
    /// sampling, the same picture for a fraction of the marks.
    private func curves(_ t: GrowthTable, end: Int) -> some View {
        let endAge = Double(end)
        var knots: [Double] = []
        var rows: [[Double]] = []
        for (i, age) in t.ages.enumerated() where age <= endAge {
            knots.append(age)
            rows.append(t.p[i])
        }
        if let lastKnot = knots.last, lastKnot < endAge, let r = Growth.rowAt(t.p, t.ages, endAge) {
            knots.append(endAge)
            rows.append(r)
        }
        let names = Growth.percentiles.map { "P" + String($0) }
        var curve: [CurvePoint] = []
        var band: [BandPoint] = []
        for k in 0..<7 {
            for j in 0..<knots.count {
                curve.append(CurvePoint(id: k * 1000 + j, series: names[k], age: knots[j], kg: rows[j][k], bold: k == 3))
            }
        }
        for j in 0..<knots.count {
            band.append(BandPoint(id: j, age: knots[j], low: rows[j][2], high: rows[j][4]))
        }
        var child: [ChildPoint] = []
        for p in chart.points {
            if let age = p.ageMonths, age <= endAge {
                child.append(ChildPoint(id: p.id, age: age, kg: p.kg))
            }
        }
        let endRow = rows.last ?? []
        let top = endRow.count == 7 ? endRow[6] : 0
        let maxKg = child.map { $0.kg }.max() ?? 0
        let minKg = child.map { $0.kg }.min() ?? 2
        let lo = min(2, floor(minKg))
        let hi = max(lo + 1, ceil(max(top, maxKg) + 0.5))   // never an empty (trapping) range
        let yTicks = WeightForAgeSection.ticks(lo: lo, hi: hi)
        let xStep = end <= 6 ? 1 : (end <= 12 ? 2 : (end <= 24 ? 3 : 12))
        let xTicks = Array(stride(from: 0, through: end, by: xStep))
        let unit = S("amount.kg", ["n": ""]).trimmingCharacters(in: .whitespaces)

        return VStack(alignment: .leading, spacing: 2) {
            Text(unit).font(.caption2).foregroundStyle(.secondary)
            Chart {
                ForEach(band) { b in
                    AreaMark(x: .value("age", b.age), yStart: .value("kg", b.low), yEnd: .value("kg", b.high))
                        .foregroundStyle(Color.gray.opacity(0.15))
                }
                ForEach(curve) { c in
                    LineMark(x: .value("age", c.age), y: .value("kg", c.kg), series: .value("series", c.series))
                        .foregroundStyle(Color.gray.opacity(c.bold ? 0.8 : 0.45))
                        .lineStyle(StrokeStyle(lineWidth: c.bold ? 2 : 1))
                }
                ForEach(child) { p in
                    LineMark(x: .value("age", p.age), y: .value("kg", p.kg), series: .value("series", "child"))
                        .foregroundStyle(Color.blue)
                        .lineStyle(StrokeStyle(lineWidth: 2))
                    PointMark(x: .value("age", p.age), y: .value("kg", p.kg))
                        .foregroundStyle(Color.blue)
                        .symbolSize(30)
                }
            }
            .chartXScale(domain: 0...endAge)
            .chartYScale(domain: lo...hi)
            .chartXAxis {
                AxisMarks(values: xTicks)
            }
            .chartYAxis {
                AxisMarks(position: .leading, values: yTicks)
                // P3..P97 named at the right end of their curves.
                AxisMarks(position: .trailing, values: endRow) { value in
                    AxisValueLabel {
                        Text(verbatim: value.index < names.count ? names[value.index] : "")
                            .font(.system(size: 9))
                    }
                }
            }
            .frame(height: 260)
            HStack {
                Spacer()
                Text(S("growth.axisMonths")).font(.caption2).foregroundStyle(.secondary)
            }
        }
        .padding(.vertical, 4)
    }

    /// Whole-kg axis values in a round step that gives at most about ten lines.
    private static func ticks(lo: Double, hi: Double) -> [Int] {
        let span = hi - lo
        var step = 500
        for s in [1, 2, 5, 10, 20, 50, 100, 200] where span / Double(s) <= 10 {
            step = s
            break
        }
        let first = Int(ceil(lo / Double(step))) * step
        let last = Int(floor(hi))
        guard first <= last else { return [] }
        return Array(stride(from: first, through: last, by: step))
    }
}
