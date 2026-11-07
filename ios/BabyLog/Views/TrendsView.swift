import Charts
import SwiftUI

/// The last 7 or 14 days as charts: bottle ml, feeds, diapers (wet and dirty stacked), the
/// day's milk as a cumulative line per day with a forecast for the rest of today, and the
/// 24-hour rhythm (feeds, wet, dirty or all, as dots by time of day), then the same numbers
/// as a table. Day labels are "M/d" strings, so those axes are categorical and keep their order.
struct TrendsView: View {
    @EnvironmentObject var model: AppModel
    @State private var span = 7
    @State private var rhythmKind = "feed"

    var body: some View {
        let stats = model.dailyStats(days: span)
        let labels = stats.map { $0.label }
        let forecast = model.intakeForecast(stats)
        List {
            Section {
                Picker(S("tab.trends"), selection: $span) {
                    Text(S("trends.last7Days")).tag(7)
                    Text(S("trends.last14Days")).tag(14)
                }
                .pickerStyle(.segmented)
                .labelsHidden()
            }
            Section(S("trends.bottlePerDay")) {
                Chart(stats) { d in
                    BarMark(x: .value("day", d.label), y: .value("ml", d.ml))
                        .foregroundStyle(Color.blue)
                        .annotation(position: .top) {
                            Text(d.ml > 0 ? String(d.ml) : "").font(.caption2).foregroundStyle(.secondary)
                        }
                }
                .chartXScale(domain: labels)
                .frame(height: 170)
            }
            Section(header: Text(S("trends.intakeTitle")), footer: Text(S("trends.intakeSub"))) {
                Chart {
                    ForEach(stats) { d in
                        ForEach(d.intake) { pt in
                            LineMark(x: .value("hour", pt.hour), y: .value("ml", pt.ml), series: .value("day", d.label))
                                .foregroundStyle(d.isToday ? Color.blue : Color.gray.opacity(0.35))
                                .lineStyle(StrokeStyle(lineWidth: d.isToday ? 3 : 1))
                        }
                    }
                    RuleMark(x: .value("now", model.hourNow))
                        .foregroundStyle(Color.orange.opacity(0.7))
                        .lineStyle(StrokeStyle(lineWidth: 1, dash: [4, 3]))
                }
                .chartXScale(domain: 0...24)
                .chartXAxis { AxisMarks(values: [0, 6, 12, 18, 24]) }
                .frame(height: 200)
                if let f = forecast {
                    forecastText(f)
                }
            }
            Section(S("trends.feedsPerDay")) {
                Chart(stats) { d in
                    BarMark(x: .value("day", d.label), y: .value("n", d.feeds))
                        .foregroundStyle(Color.blue.opacity(0.55))
                }
                .chartXScale(domain: labels)
                .frame(height: 120)
            }
            Section(S("trends.diapersPerDay")) {
                Chart {
                    ForEach(stats) { d in
                        BarMark(x: .value("day", d.label), y: .value("n", d.wet))
                            .foregroundStyle(by: .value("kind", S("log.wet")))
                        BarMark(x: .value("day", d.label), y: .value("n", d.dirty))
                            .foregroundStyle(by: .value("kind", S("log.dirty")))
                    }
                }
                .chartForegroundStyleScale([S("log.wet"): Color.teal, S("log.dirty"): Color.brown])
                .chartXScale(domain: labels)
                .frame(height: 140)
            }
            Section(header: Text(S("trends.rhythm")), footer: Text(S("trends.rhythmPhone"))) {
                Picker(S("trends.rhythm"), selection: $rhythmKind) {
                    Text(S("log.feed")).tag("feed")
                    Text(S("log.wet")).tag("wet")
                    Text(S("log.dirty")).tag("dirty")
                    Text(S("trends.rhythmAll")).tag("all")
                }
                .pickerStyle(.segmented)
                .labelsHidden()
                Chart {
                    ForEach(stats) { d in
                        ForEach(rhythmPoints(d)) { pt in
                            PointMark(x: .value("hour", pt.hour), y: .value("day", d.label))
                                .foregroundStyle(by: .value("kind", pt.kind))
                        }
                    }
                }
                .chartForegroundStyleScale([S("log.feed"): Color.blue, S("log.wet"): Color.teal,
                                            S("log.dirty"): Color.brown])
                .chartLegend(rhythmKind == "all" ? .visible : .hidden)
                .chartXScale(domain: 0...24)
                .chartXAxis { AxisMarks(values: [0, 6, 12, 18, 24]) }
                .chartYScale(domain: labels.reversed())
                .frame(height: CGFloat(stats.count) * 24 + 40)
            }
            Section(S("trends.dayTable")) {
                ForEach(stats.reversed()) { d in
                    HStack(spacing: 10) {
                        Text(d.label).frame(width: 46, alignment: .leading).monospacedDigit()
                        Text(SP("count.feeds", d.feeds))
                        Text(S("amount.ml", ["n": String(d.ml)]))
                        Spacer()
                        Text(S("now.wetTotal", ["n": String(d.wet)]))
                        Text(S("now.dirtyTotal", ["n": String(d.dirty)]))
                    }
                    .font(.footnote)
                }
            }
        }
        .listStyle(.insetGrouped)
        .navigationTitle(S("tab.trends"))
        .navigationBarTitleDisplayMode(.inline)
    }

    private func forecastText(_ f: IntakeForecast) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(S("trends.intakeSoFar", ["ml": S("amount.ml", ["n": String(f.soFar)])]))
            Text(S("trends.intakeTypical", ["n": String(f.pastDays),
                                            "pct": String(Int((f.typicalShare * 100).rounded()))]))
            if let total = f.projectedTotal {
                Text(S("trends.intakeProjected", ["total": S("amount.ml", ["n": String(total)]),
                                                  "left": S("amount.ml", ["n": String(max(0, total - f.soFar))])]))
                    .fontWeight(.semibold)
            }
            Text(S("trends.intakeAverage", ["avg": S("amount.ml", ["n": String(f.averageTotal)]),
                                            "left": S("amount.ml", ["n": String(max(0, f.averageTotal - f.soFar))])]))
        }
        .font(.footnote)
    }

    private struct RhythmPoint: Identifiable {
        let id: Int
        let hour: Double
        let kind: String
    }
    /// The dots of one day's rhythm row for the chosen kind(s), keyed by the legend name.
    private func rhythmPoints(_ d: DayStat) -> [RhythmPoint] {
        var out: [RhythmPoint] = []
        func add(_ hours: [Double], _ kind: String) {
            for h in hours { out.append(RhythmPoint(id: out.count, hour: h, kind: kind)) }
        }
        if rhythmKind == "feed" || rhythmKind == "all" { add(d.feedHours, S("log.feed")) }
        if rhythmKind == "wet" || rhythmKind == "all" { add(d.wetHours, S("log.wet")) }
        if rhythmKind == "dirty" || rhythmKind == "all" { add(d.dirtyHours, S("log.dirty")) }
        return out
    }
}
