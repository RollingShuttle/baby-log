import Foundation

/// The bilingual table, read from the bundled copy of i18n/strings.json (the test keeps the
/// copy identical). `S(key)` is the one way a screen gets its text; the language follows the
/// phone unless Settings pins one.
enum L10n {
    static var override = ""      // "", "en" or "zh-Hans"; set by AppModel from its setting
    static let table: [String: [String: String]] = load()

    static var locale: String {
        if !override.isEmpty { return override }
        let preferred = Locale.preferredLanguages.first ?? "en"
        return preferred.hasPrefix("zh") ? "zh-Hans" : "en"
    }

    private static func load() -> [String: [String: String]] {
        guard let url = Bundle.main.url(forResource: "strings", withExtension: "json"),
              let data = try? Data(contentsOf: url),
              let obj = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any],
              let strings = obj["strings"] as? [String: Any] else { return [:] }
        var out: [String: [String: String]] = [:]
        for (key, value) in strings {
            if let entry = value as? [String: Any] { out[key] = entry.compactMapValues { $0 as? String } }
        }
        return out
    }
}

/// The text for a key in the current language, with {name} placeholders filled in.
func S(_ key: String, _ args: [String: String] = [:]) -> String {
    let entry = L10n.table[key]
    var text = entry?[L10n.locale] ?? entry?["en"] ?? key
    for (name, value) in args { text = text.replacingOccurrences(of: "{" + name + "}", with: value) }
    return text
}
/// A plural key: `<key>.one` for exactly one, else `<key>.other`, with {n} filled in.
func SP(_ key: String, _ n: Int) -> String {
    S(n == 1 ? key + ".one" : key + ".other", ["n": String(n)])
}
