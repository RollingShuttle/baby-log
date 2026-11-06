import Charts
import SwiftUI

/// The last 7 or 14 days as charts: bottle ml, feeds, diapers (wet and dirty stacked), and
/// the 24-hour rhythm (every feed as a dot by its start time), then the same numbers as a
/// table. Day labels are "M/d" strings, so the axes are categorical and keep their order.
struct TrendsView: View {
    @EnvironmentObject var model: AppModel
    @State private var span = 7

    var body: some View {
        let stats = model.dailyStats(days: span)
        let labels = stats.map { $0.label }
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
                Chart {
                    ForEach(stats) { d in
                        ForEach(Array(d.feedHours.enumerated()), id: \.offset) { _, hour in
                            PointMark(x: .value("hour", hour), y: .value("day", d.label))
                                .foregroundStyle(Color.blue)
                        }
                    }
                }
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
}
