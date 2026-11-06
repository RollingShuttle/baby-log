import Foundation

/// Ids, filenames and instants in exactly the shapes of core.js and store.py (SPEC §3.1, §3.2),
/// so the three implementations name files and order revisions identically.
enum Names {
    // The one filename rule: <id>-r<n>-<w>.json. The pattern text must stay equal to core.js's
    // NAME_RE; tests/test_ios.py compares them.
    static let namePattern = "^([EC]-.+)-r([1-9]\\d*)-([0-9a-f]{4})\\.json$"
    static let isoPattern = "^(\\d{4})-(\\d{2})-(\\d{2})T(\\d{2}):(\\d{2}):(\\d{2})([+-])(\\d{2}):(\\d{2})$"
    private static let nameRegex = try! NSRegularExpression(pattern: namePattern)
    private static let isoRegex = try! NSRegularExpression(pattern: isoPattern)
    private static let wRegex = try! NSRegularExpression(pattern: "-r\\d+-([0-9a-f]{4})\\.json$")

    struct Parsed {
        let id: String
        let rev: Int
        let w: String
    }

    /// Four hex characters: the suffix that keeps two devices in the same second apart.
    static func rand4() -> String {
        String(format: "%02x%02x", Int.random(in: 0...255), Int.random(in: 0...255))
    }
    /// UTC "YYYYMMDD-HHMMSS", the same stamp as the other two writers.
    static func stamp(_ date: Date = Date()) -> String { utc("yyyyMMdd-HHmmss").string(from: date) }
    static func newId(_ prefix: String, _ date: Date = Date()) -> String {
        "\(prefix)-\(stamp(date))-\(rand4())"
    }
    /// A fresh w on every write, so two writers of one revision coexist.
    static func fileName(_ id: String, _ rev: Int) -> String { "\(id)-r\(rev)-\(rand4()).json" }

    static func parseName(_ name: String) -> Parsed? {
        let ns = name as NSString
        guard let m = nameRegex.firstMatch(in: name, range: NSRange(location: 0, length: ns.length)) else {
            return nil
        }
        return Parsed(id: ns.substring(with: m.range(at: 1)),
                      rev: Int(ns.substring(with: m.range(at: 2))) ?? 0,
                      w: ns.substring(with: m.range(at: 3)))
    }
    /// The w of a filename, or "": the last tie-break of the resolve rule.
    static func wSuffix(_ file: String) -> String {
        let ns = file as NSString
        guard let m = wRegex.firstMatch(in: file, range: NSRange(location: 0, length: ns.length)) else {
            return ""
        }
        return ns.substring(with: m.range(at: 1))
    }
    /// created_at: UTC with six fractional digits and "+00:00", fixed width so strings sort.
    static func nowIso(_ date: Date = Date()) -> String {
        let t = date.timeIntervalSince1970
        let micro = Int(((t - floor(t)) * 1_000_000).rounded(.down))
        return utc("yyyy-MM-dd'T'HH:mm:ss").string(from: date) + String(format: ".%06d+00:00", micro)
    }
    /// Whole seconds with the zone's numeric offset on that instant: the time/end shape.
    static func isoLocal(_ date: Date = Date(), zone: TimeZone = .current) -> String {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.timeZone = zone
        f.dateFormat = "yyyy-MM-dd'T'HH:mm:ss"
        let off = zone.secondsFromGMT(for: date)
        let a = abs(off)
        return f.string(from: date) + (off < 0 ? "-" : "+") + String(format: "%02d:%02d", a / 3600, (a % 3600) / 60)
    }
    /// A Date for a string of exactly the time/end shape, else nil.
    static func parseIso(_ iso: String?) -> Date? {
        guard let iso = iso else { return nil }
        let ns = iso as NSString
        guard isoRegex.firstMatch(in: iso, range: NSRange(location: 0, length: ns.length)) != nil else {
            return nil
        }
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "yyyy-MM-dd'T'HH:mm:ssXXX"
        return f.date(from: iso)
    }
    /// The display day: the writer's local date, never re-zoned.
    static func localDate(_ iso: String?) -> String { String((iso ?? "").prefix(10)) }
    /// The UTC date of a write: the day folder.
    static func utcDate(_ date: Date = Date()) -> String { utc("yyyy-MM-dd").string(from: date) }
    /// This phone's local "YYYY-MM-DD" for an instant.
    static func dayOf(_ date: Date) -> String { String(isoLocal(date).prefix(10)) }
    static func shiftDay(_ day: String, _ n: Int) -> String {
        let f = utc("yyyy-MM-dd")
        guard let d = f.date(from: day) else { return day }
        return f.string(from: d.addingTimeInterval(Double(n) * 86400))
    }
    /// Local midnight of a "YYYY-MM-DD", for display and ages.
    static func dateOfDay(_ day: String) -> Date? {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "yyyy-MM-dd"
        return f.date(from: day)
    }

    private static func utc(_ format: String) -> DateFormatter {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.timeZone = TimeZone(identifier: "UTC")
        f.dateFormat = format
        return f
    }
}
