# i18n — the bilingual string table

`strings.json` holds every user-facing text of Baby Log in English (`en`) and Simplified
Chinese (`zh-Hans`), started 2 Nov 2026 for the native iOS app (`guide/IOS-APP-PLAN.md`
§1.7c) and kept current from here on. The English is quoted from the web app's code as it
shows today — `docs/app.js`, `docs/core.js`, `docs/sync.js`, `docs/index.html` and the PC-only
screens in `static/app.js` — and the planned native features (bath, photos, the outing
checklist, reminders, Siri) are translated up front so no screen ships English-only.

**The frozen web app does not read this file.** Nothing in `docs/` or `static/` is wired to it;
it is the record the native app is built from.

## Shape

```json
{
  "_about": "…",
  "_locales": ["en", "zh-Hans"],
  "_glossary": { "Feed": "喂奶", … },
  "strings": {
    "feed.sameAsLast": { "en": "Same as last · {amount}", "zh-Hans": "同上次 · {amount}",
                         "where": "feed editor: the first quick chip" }
  }
}
```

- Keys are lower-case, dotted, grouped by screen or feature (`tab.*`, `now.*`, `sync.*`,
  `editor.*`, `feed.*`, `settings.*`, `outing.*`, `siri.*` …) and kept sorted.
- `where` says which screen and element shows the text, so a translator sees the context.
- `_glossary` is the vocabulary both languages are held to; use it before inventing a new word.

## Placeholders

A placeholder is `{name}` and must be the **same set** in both languages (`tests/test_strings.py`
checks). Reorder them freely — `"{type} {time} · {line}"` becomes `"{time} 的{type} · {line}"`.
Names describe the value: `{n}` a count, `{amount}` a formatted amount, `{time}` a clock time,
`{since}` a `since.*` duration, `{who}` a `device.*` text, `{type}` a type label.

## Plurals

Where English inflects the key carries two entries, `.one` and `.other` (CLDR categories):
`count.feeds.one` = `{n} feed`, `count.feeds.other` = `{n} feeds`. Chinese does not inflect, so
its two forms are identical; the generator folds them into one `plural` variation. A compound
age like `age.weeksDays` (`{w} weeks {d} days`) takes its singular parts from `age.weeks.one` /
`age.days.one`.

## What is not a string

Dates, times, numbers and units are formatted by the **system locale**, never by these strings:
weekday and month abbreviations (`Wed 23 Sep`), clock times, decimal separators, the `°C` sign,
`12:34` elapsed clocks, bare numerals (`−5`, `−15`, `30, 60, 90, 120`), and the `·` / `–` / `—`
separators. A line that is only placeholders and separators (the Day sheet's `{amount} {kind}`
portion, the header's `{name} · {age}`) is joined in code, not translated.

File and product names stay as they are: `Baby Log` as the bundle name and in the Siri phrases,
`Baby Log.xlsx`, `OneDrive`, `Similac`, `Enfamil`, `Siri`.

## Generating `Localizable.xcstrings`

A script in `tools/` (planned, stage 2 item 13a of the iOS plan) reads `strings.json` and writes
the Xcode String Catalog: one entry per key, `en` and `zh-Hans` as its localizations, `where` as
the comment, `.one`/`.other` pairs as one key with plural variations, and `{name}` placeholders
turned into `%@` / `%lld` with the key's argument order recorded so both languages can reorder
them (`%1$@`). The native code calls `String(localized:)` with the key; it never contains an
English literal. Adding a string means adding it here first, then regenerating.

## Keeping it current

A new screen, button, toast or notice goes into this file **before** it goes into Swift, with
its `where`. Run `python tests/test_strings.py` — it checks the JSON parses, the locales, that
every entry has both languages and a `where`, that the placeholders match, that every Chinese
value really is Chinese (brand names excepted), that keys are unique and sorted, and that the
file is UTF-8 without BOM with LF endings.
