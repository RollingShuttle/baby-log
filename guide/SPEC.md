# Baby Log — Build Spec (v3, 2026-09-27)

A feeding, diaper, sleep and health log for one child (more later), shared by two iPhones and one
PC through the owner's personal OneDrive. It replaces the hospital's paper *Feeding & Diapering*
sheet. Written from the approved proposal (https://claude.ai/artifact/Mva9Y3fzFx9dgqrJZ6NF7K), the
decisions the owner confirmed on 2026-09-23, and an adversarial review of the v1 draft.

It is built on the structure of `E:\Claude Code\whiskey-tasting` (the Whiskey Tasting Book):
a Python/Flask PC app in its own window, a static iPhone web app on GitHub Pages, and a folder of
small immutable JSON files in OneDrive as the only transport. **Read that project's `CLAUDE.md`,
`launch.py`, `store.py`, `docs/graph.js` and `docs/store.js` before building the matching part
here.** The working style, the file-naming rules and the iOS rules carry over. Nothing about the
whiskey *collection workbook* carries over: there is no master workbook, nothing is read-only, and
no surgical zip write exists.

---

## 0. Decisions already made (do not reopen)

| Question | Decision |
|---|---|
| Accounts | Both phones sign in with the **owner's** personal Microsoft account. Each device carries a label saying who holds it. |
| Where the journal lives | `OneDrive\Apps\Baby Log\` — the Entra app folder, reached by phones with the `Files.ReadWrite.AppFolder` scope only. |
| Where the readable files live | `C:\Users\mikey\OneDrive\文档\Yisen File\` — `Baby Log.xlsx` and `Day sheets\`. The PC writes these; phones never touch them. |
| Phones | Both iPhones. Build to iOS conventions (§7.5). |
| Units | Stored in **whole ml**. Shown in ml by default; oz is a per-device display switch. |
| Version 1 scope | §11. Nothing from "Next" unless it is free. |
| The child | **Yisen**, born 2026-09-21 (time unknown; store the date until the owner fills it in). |
| The paper sheet | Imported as the first three days (§10), with the uncertain readings flagged `Check:` in the note and listed under **Needs check** so they can be corrected in the app. |
| Editing | **Every entry can be changed or deleted from every device, and it must be obvious how.** §8.3 lists every surface. Deleted entries are recoverable. |
| Name of the Entra registration | `Baby Log` — it becomes the folder name `OneDrive/Apps/Baby Log`. |
| PC port | **8766** (the whiskey app holds 8765; both may run at once). |

---

## 1. Project rules that carry over from the whiskey app

1. **Every generated filename is unique at sub-second resolution.** Ids carry a UTC timestamp *and*
   a random suffix, and every *write* adds a fresh suffix of its own (§3). Two devices logging in
   the same second must never share a name. The whiskey project hit this bug three times.
2. **Journal files are immutable.** A correction is a new revision file; a deletion is a tombstone
   revision. Nothing is ever edited in place.
3. **Nothing is ever held only in memory on a phone.** Save locally (and *check that the save
   succeeded*), then queue the upload. An open editor's typed fields are also persisted (§7.4).
4. **Save each step as it is finished and run its tests before starting the next.** Every module
   has `tests/test_<module>.py` that runs standalone (`python tests/test_store.py`) and under
   discovery (`python -m unittest discover -s tests`). Tests use temp folders, never the real
   OneDrive folder, and fixtures are synthetic — the committed tree carries no personal data beyond
   the child's first name in `tools/paper_sheet.json`.
5. Commits use the repo-local noreply identity already configured (`RollingShuttle`), because the
   repository may be public for GitHub Pages.

---

## 2. Layout

```
baby-logging/
  app.py                  Flask server + JSON API at 127.0.0.1:8766, serves static/ and /core.js
  launch.py               window + tray + single instance (ported from whiskey; port 8766, names changed)
  store.py                the journal: children and events, revisions, tombstones, resolution, index
  rollup.py               writes Baby Log.xlsx and the day-sheet HTML into Yisen File
  paper.py                the paper-sheet import (reads tools/paper_sheet.json)
  config.yaml             machine paths only                                     (gitignored)
  config.example.yaml     the template (§6.1 lists its keys)
  requirements.txt        openpyxl, PyYAML, Flask, pystray (same pins as whiskey)
  run.bat  update.bat  build_exe.bat   icon.ico
  static/                 the PC front end (bundled into the exe)
    index.html  style.css  app.js  print.css  icon.ico  icon-180.png
  docs/                   the iPhone client — GitHub Pages serves only / or /docs
    index.html  style.css  config.js  core.js  graph.js  store.js  sync.js  app.js
    sw.js  manifest.webmanifest  icon-180.png
  tests/                  test_store.py  test_core.py  test_app.py  test_rollup.py  test_paper.py
                          test_launch.py  test_update.py  test_setup_machine.py  test_phone.py  test_sync.py
                          fixtures/data_cases.json
  tools/                  setup_machine.py  make_shortcut.py  update.py  paper_sheet.json
  guide/                  SPEC.md (this)  SETUP.md  RUNNING.md
  data/                   settings.json, backups/                                (gitignored)
```

`docs/core.js` is **shared**: the PC front end loads it too. `build_exe.bat` and `tools/update.py`
both pass `--add-data "%~dp0static;static"` and `--add-data "%~dp0docs\core.js;docs"`, so in the
exe the file is `<sys._MEIPASS>/docs/core.js`. `app.py` defines
`CORE_JS = _resource_dir() / "docs" / "core.js"` (whiskey's `_resource_dir()`), serves it at
`/core.js` with `Cache-Control: no-cache`, and `tests/test_app.py` asserts `/core.js` serves the
same bytes as `docs/core.js`. `tests/test_update.py` asserts both `--add-data` flags appear in both
`build_exe.bat` and `tools/update.py`.

---

## 3. The OneDrive app folder — the journal

```
OneDrive/Apps/Baby Log/
  children/   C-<stamp>-<rand>-r<n>-<w>.json                one child; revisions for edits
  events/     <YYYY-MM-DD>/E-<stamp>-<rand>-r<n>-<w>.json   one feed / diaper / … per file
  meta/       (reserved; nothing in v1)
```

### 3.1 File names — one canonical rule

**Every journal file is named `<id>-r<n>-<w>.json`.** `<id>` is the record's id: normally
`E-<stamp>-<rand4>` / `C-<stamp>-<rand4>` where `<stamp>` is UTC `YYYYMMDD-HHMMSS` and `<rand4>` is
4 hex characters; for the paper import `E-paper-<YYYYMMDD>-<HHMM>-<type>`. `<n>` is the revision
(decimal, no padding, from 1). `<w>` is **4 fresh hex characters per write**, so two devices that
both write revision 2 of one event produce two different files and neither destroys the other.

The one parser, identical in `store.NAME_RE` and `Core.parseName(name)`:

```
^(?P<id>[EC]-.+)-r(?P<rev>\d+)-(?P<w>[0-9a-f]{4})\.json$
```

Readers ignore any name that does not match (OneDrive briefly shows temp files; the PC's own temp
files end in `.tmp` so the OneDrive client never uploads them). Examples:
`E-20260923-225012-a1b2-r1-7c1d.json`, `E-20260923-225012-a1b2-r2-0e9f.json`,
`E-paper-20260921-1400-feed-r1-00aa.json`, `C-20260923-220000-0a1b-r2-9e3f.json`.

- **The day folder is the UTC date when the file is uploaded** — on the PC, the moment of the
  write; on a phone, the moment of the upload attempt (§7.3 re-paths a stale item). It is **not**
  the event's own date. A revision of a week-old event lands in *today's* folder. This is what lets
  a phone find every change by listing only the day folders since its last successful pull.
- **The id never changes across revisions.** Readers resolve each id to one record (§3.4).
- A **tombstone** is the latest record with every field carried, `revision + 1`, `deleted: true`,
  `reason` (string or null; the one-tap Undo uses `"undo"`), and re-stamped `device`,
  `entered_from`, `edited_by`, `created_at`. A **restore** copies the latest *non-deleted*
  revision from the history (falling back to the tombstone's body), sets `deleted: false`,
  `reason: null`, `revision = highest + 1`. Deleting a tombstoned id or restoring a live one is an
  error (`ValueError`; API 409).
- The PC reads and writes this folder as ordinary files through the OneDrive client
  (`config.yaml: paths.app_folder`). Phones reach it only through Microsoft Graph (§7.1).

### 3.2 The event record

Written identically by `store.py` and `docs/store.js`. Keys are fixed; unknown top-level keys are
preserved by readers.

```json
{
  "event_id": "E-20260923-225012-a1b2",
  "revision": 1,
  "deleted": false,
  "reason": null,
  "child_id": "C-20260923-220000-0a1b",
  "type": "feed",
  "time": "2026-09-23T17:50:00-05:00",
  "end": null,
  "data": { },
  "note": "",
  "logged_by": "Dad",
  "edited_by": null,
  "device": "d-3f9a",
  "entered_from": "phone",
  "created_at": "2026-09-23T22:50:12.123456+00:00"
}
```

- `time` is the moment the thing **started**; `end` is when it ended (feed, sleep, pump), `null`
  while running or not applicable. Both are exactly `YYYY-MM-DDTHH:MM:SS±HH:MM` — whole seconds,
  numeric offset, never `Z`, never fractional seconds. The offset is the writing device's zone
  offset **on that date and time** (JS: build a `Date` from local components and read
  `getTimezoneOffset()`; Python: `datetime(...).astimezone()`), so an entry edited in November keeps
  its September offset. Writers reject any other shape and never rewrite one.
- **The display day of an event is the first 10 characters of `time`** — the writer's local date.
  `Core.localDate(iso)` and `store.events_on(date)` slice the string and take no zone argument.
  Durations are always `Date(end) − Date(time)` on instants, never wall-clock differences.
- `created_at` is exactly `YYYY-MM-DDTHH:MM:SS.ffffff+00:00` (UTC, six fractional digits, `+00:00`
  never `Z`). Python: `datetime.now(timezone.utc).isoformat(timespec="microseconds")`. JS:
  `Core.nowIso()` = `new Date().toISOString().replace("Z", "000+00:00")`. Fixed width, so ties
  are broken by plain string comparison.
- `logged_by` is **who did it** — the label chosen in the editor, defaulting to the device's label.
  It is carried unchanged through every later revision unless the editor changes it explicitly (the
  editor shows it as a field). `edited_by` is the label of the device writing the revision (`null`
  on revision 1). `device`, `entered_from`, `edited_by` and `created_at` are re-stamped on every
  revision. `device` is `pc` on the PC, `d-<rand4>` on a phone (minted once, kept in settings),
  `paper` for the import. `entered_from` is `pc`, `phone` or `paper`.
- `type` is one of `feed diaper sleep pump growth health note`. A revision may change `type` (the
  editor's **Change type…**) and `child_id`; `data` is then validated against the new type.

`data` per type — every key always present (see `Core.defaults(type)` / `store.DEFAULTS` below):

| type | data |
|---|---|
| `feed` | `{"breast": {"left_s": int\|null, "right_s": int\|null, "total_s": int\|null, "last_side": "left"\|"right"\|null, "approx": bool}, "bottles": [{"kind": "formula"\|"breast_milk", "ml": number, "formula": string\|null}], "made_ml": number\|null, "leftover_ml": number\|null, "timer": {"side": "left"\|"right", "side_started": iso} \| null}` |
| `diaper` | `{"wet": bool, "dirty": bool, "color": "black"\|"dark_green"\|"green"\|"yellow"\|"brown"\|"other"\|null, "texture": "sticky"\|"seedy"\|"soft"\|"solid"\|"watery"\|null, "size": "small"\|"medium"\|"large"\|null, "rash": bool, "blowout": bool}` |
| `sleep` | `{"where": string\|null, "timer": {"running": true} \| null}` |
| `pump` | `{"left_ml": number\|null, "right_ml": number\|null, "minutes": number\|null}` |
| `growth` | `{"weight_g": number\|null, "length_cm": number\|null, "head_cm": number\|null}` |
| `health` | `{"temp_c": number\|null, "medicine": string\|null, "dose": string\|null, "symptom": string\|null}` — vitamin D is a medicine named `Vitamin D`. |
| `note` | `{"milestone": bool}` |

Feed rules: `total_s` is the sum of the sides when they are known, or the typed "~15 min" (900,
`approx: true`) when they are not. **Breast feeding is no longer entered** (decided 27 Sep 2026:
Yisen is on formula) — the `breast` and `timer` fields stay in the record for the paper rows and
history, both validators still accept them, but no editor offers a side timer or typed minutes;
an entry that carries breast seconds shows them as a read-only line. `bottles[].formula` is the
formula's name as the parents call it (`Similac Pro-Advance`, `Enfamil NeuroPro`), a non-empty
string or null; null for breast milk. `left_*` always means the left breast; leftover milk is
`leftover_ml`. Bottle ml (derived, never stored) = sum of `bottles[].ml`. Amounts are whole ml.

**Timers.** A running event is exactly `end: null` **with `timer` non-null** — both, always:
a feed typed in after the fact, or imported from the paper sheet, has no end and no timer, and
is over. `Core.isRunning` / `rollup.is_running` test both. A running feed's
`timer.side_started` is an instant; the running side's elapsed time is `now − side_started` on the
displaying device and is folded into `left_s`/`right_s` on Switch or Stop, each of which is a
revision. Stop writes `end` and `timer: null` in the same revision; with an explicit end earlier
than now, the running side's seconds are `end − side_started`, never `now − side_started`. Readers
decide "running" by `end === null` for feeds and sleeps; `timer` is informational. A timer running
longer than 60 min (feed) or 6 h (sleep) is *stale*: shown with a warning and a **Set end time**
action, never auto-stopped. Readers decide "running" by `end === null && data.timer`, never by
`end` alone.

**Validation — both writers, identical.** `Core.defaults(type)` (JS) and `store.DEFAULTS[type]`
(Python) return the full `data` object with every key present: feed →
`{breast: {left_s: null, right_s: null, total_s: null, last_side: null, approx: false}, bottles: [], made_ml: null, leftover_ml: null, timer: null}`;
diaper → all bools false, enums null; sleep → `{where: null, timer: null}`; pump/growth/health → all
null; note → `{milestone: false}`. Both writers deep-merge the caller's `data` over the defaults
(arrays replaced, not merged). Both reject: unknown keys at any depth; an enum value outside its
set; `bottles[].ml` not a finite number > 0; `bottles[].kind` not in the set; any `*_s`, `*_ml`,
`*_g`, `*_cm`, `temp_c`, `minutes` that is neither null nor a finite number ≥ 0; a `time`/`end`
of the wrong shape; `end` earlier than `time`; an unknown `type`. Python raises `ValueError`
(API → 400); JS throws `Error`. **`tests/fixtures/data_cases.json` is the shared fixture**:
`test_store.py` and `test_core.py` both run every accepted and rejected case in it, and both
assert `defaults` in it equals their own defaults.

### 3.3 The child record

`children/C-<stamp>-<rand>-r<n>-<w>.json`:

```json
{"child_id": "C-20260923-220000-0a1b", "revision": 1, "deleted": false, "reason": null,
 "name": "Yisen", "born": "2026-09-21", "born_time": null, "sex": null, "birth_weight_g": null,
 "targets": {"feeds_per_day": null, "wet_per_day": null, "dirty_per_day": null},
 "device": "pc", "created_at": "2026-09-23T22:00:00.000000+00:00"}
```

`born` is a local date; `born_time` is `"HH:MM"` or null. Targets are what the pediatrician said,
typed by the owner; the app never invents them. **The current child is the live child with the
lexically smallest `child_id`** (the oldest). Only two things ever create a child: the PC's
Settings → Child form (`POST /api/children`, shown as a first-run card on Today while
`/api/config.child` is null) and `paper.py`, which creates Yisen only when `children()` is empty
after a fresh read. **The phone never creates a child**; it can revise one. While it holds no
child, the phone's Now screen says "Waiting for the first sync" and the log buttons are disabled.
The chooser (PC top bar, phone Settings) appears only when two or more live children exist and
stores the choice per device (`settings.child_id`).

### 3.4 Resolution — the one ordering rule

`store.resolve(records, key="event_id")` → `dict id → record`, keeping tombstones. For each id the
winner is, in order: the highest `revision`; then — for feeds, sleeps and pumps — a record with
`end` non-null beats one with `end` null (a Stop is never undone by a concurrent Switch); then the
greatest `created_at` string; then the greatest `device` string; then the greatest `<w>` from the
filename (readers keep `_file`, the filename, on each record in memory; it is never written into
the file). `store.live(records, key)` → the resolved values with `deleted` true removed, sorted by
`time` as an instant, ties by id. `Core.resolve` / `Core.live` implement the same rule and return a
`Map` / array. Where a route or screen says "resolved events" it means `live()` — tombstones appear
only in `/api/deleted`, `/api/event/<id>` and the Deleted lists.

---

## 4. `store.py` — the journal (Python)

`Journal(root)` mirrors whiskey's `store.Journal`:

- `ensure()` — creates `children/`, `events/`, `meta/`.
- `write_child(*, name, born, born_time=None, sex=None, birth_weight_g=None, targets=None,
  child_id=None, device="pc")` → record; a `child_id` writes a revision (targets merged over the
  null defaults).
- `children()` → live list, oldest id first; `child(child_id)` → resolved record or None.
- `write_event(*, child_id, type, time, end=None, data=None, note="", logged_by, device="pc",
  entered_from="pc", edited_by=None, event_id=None, revision=None, reason=None, deleted=False)` →
  record. Validates per §3.2. Omit `event_id` for a new event (id = `E-<stamp>-<rand4>`). Pass
  `event_id` to write a revision (`highest on file + 1`, `logged_by` carried from the latest
  revision unless given). Passing an explicit `revision=1` for an id that already has any
  revision on file raises `FileExistsError` — the paper import uses this.
- `delete_event(event_id, reason=None, *, device, edited_by)` → tombstone;
  `restore_event(event_id, *, device, edited_by)` → revision per §3.1.
- `events()` → `live()` list; `events_on(date)` (`time[:10] == date`); `events_between(d1, d2)`
  (inclusive local dates); `event(event_id)` → resolved record including a tombstone, or None;
  `history(event_id)` → every revision ascending (revision, created_at); `deleted()` → tombstoned
  records newest tombstone first.
- `stats()` → `{"events": live count, "deleted": tombstone count, "children": live count,
  "files": total json files, "newest_at": max created_at or null, "unreadable": [names]}`.
- The day folder for a write is `datetime.now(timezone.utc).strftime("%Y-%m-%d")`.

**Reading is defensive.** The journal lives in a OneDrive-synced folder: a file may be a
Files-On-Demand placeholder, zero bytes mid-download, or half-written. The reader wraps every file
in `try/except (OSError, ValueError)`, skips it, lists it in `stats()["unreadable"]`, and retries it
on the next read (never caches it as absent). `Journal` keeps an in-process index keyed by
`(path, size, mtime_ns)` so unchanged files are parsed once; `load(force=False)` rescans the tree
only when the last scan is older than 2 s (or `force=True`). `_atomic_write_json` is whiskey's,
with the temp file named `*.tmp` (OneDrive does not sync `*.tmp`).

`resolve`, `live`, `DEFAULTS`, `validate_data(type, data) -> data`, `NAME_RE`, `parse_name(name)`,
`now_iso()`, `iso_local(dt)` are module-level so `rollup.py`, `paper.py` and `app.py` share them.

---

## 5. `docs/core.js` — shared logic for both front ends

A single global `Core` (no modules, no build step) of pure functions with no DOM and no storage.
The file ends with `if (typeof module !== "undefined") module.exports = Core;` so
`tests/test_core.py` can `require` it under Node (it skips with a message when `node` is not on
PATH; the suite must not depend on Node). Units: every function takes and returns **ml** and
**seconds / milliseconds** unless the name says otherwise; `unit` arguments (`"ml"|"oz"`) affect
only formatting and step granularity. 1 oz = 29.5735 ml.

```
Core.stamp(date)               UTC "YYYYMMDD-HHMMSS"
Core.rand4()                   4 hex chars from crypto.getRandomValues
Core.newId(prefix, date=now)   `${prefix}-${stamp(date)}-${rand4()}`
Core.fileName(id, rev)         `${id}-r${rev}-${rand4()}.json`
Core.parseName(name)           {id, rev, w} or null (the §3.1 regex)
Core.nowIso()                  created_at format (§3.2)
Core.isoLocal(date)            "2026-09-23T17:50:00-05:00" (whole seconds, the zone's offset on that date)
Core.parseIso(iso)             Date, or null when not the §3.2 shape
Core.localDate(iso)            iso.slice(0, 10)
Core.defaults(type)            full data object (§3.2)
Core.validate(type, data)      deep-merged data, or throws Error with the §3.2 message
Core.resolve(records, key="event_id")   Map id -> winner (§3.4, tombstones kept)
Core.live(records, key)        array, deleted removed, sorted by time instant then id
Core.onDay(events, "YYYY-MM-DD")
Core.isRunning(ev)             ev.end === null && (type feed|sleep)
Core.staleTimer(ev, now)       running for > 60 min (feed) / 6 h (sleep)
Core.lastOf(events, type, before=now)   latest by time with time <= before, running included
Core.sinceText(ms)             "1 h 15 m", "45 m", "2 d 3 h"
Core.usualGapMs(events, type, n=6)   median gap between the last n starts; null with < 3 events
Core.nextFeedAt(events)        iso in the device zone, or null
Core.totals(events, day, now)  {feeds, bottle_ml, breast_s, wet, dirty, sleeps, sleep_s, pumps, pump_ml}
                               — counts an event on Core.localDate(ev.time); a sleep's full span counts
                               on its start day; running feeds/sleeps fold `now`
Core.bottleMl(ev)              Core.breastSeconds(ev, now)   (folds a running timer)
Core.describe(ev, unit)        "5 min + 22 ml formula" · "Wet + dirty · yellow" · "Sleep 1 h 20 m" ·
                               "Pumped 60 ml" · "Weight 3.42 kg" · "Vitamin D 1 drop" · "Note"
Core.fmtAmount(ml, unit)       "22 ml" / "0.75 oz"    Core.toUnit(ml, unit)   Core.fromUnit(v, unit) -> whole ml
Core.stepMl(recentMls, unit)   ml: 1 while median < 40, 5 < 100, else 10; oz: 0.25 oz (7 ml) while
                               median < 1.5 oz else 0.5 oz (15 ml); [] -> 1 ml / 0.25 oz
Core.chipStepMl(recentMls, unit)  ml: 5 < 40, 10 < 100, 20 < 200, else 30; oz: 0.25 / 0.5 / 1
Core.quickRange(fromMl, toMl, stepMl)  every step from `from` to `to` inclusive (swapped if reversed),
                               capped at 12 values, [] when the step is 0 or a bound is missing
Core.formulaChoices(recentFormulas)  distinct names most recent first, at most 4; ["Similac", "Enfamil"]
                               when nothing has been recorded yet
Core.quickAmounts(recentMls, unit, custom)  exactly 4 ml values: median rounded to the chip step and
                               −1, +1, +2 chip steps (e.g. 10 15 20 25; later 160 180 200 220), all > 0;
                               `custom` (non-empty array) returned verbatim instead
Core.unusual(ml, recentMls)    true above 2 × max(recent); false with fewer than 3 recent
Core.ageText(born, now)        < 14 days "N days old"; < 8 weeks "W weeks D days" (omit "0 days");
                               else "M months W weeks" by calendar months
Core.isNight(now, {night_from, night_to})  "HH:MM" local; a window crossing midnight is t >= from || t < to
Core.fmtTime(iso) "17:50"      Core.fmtDay(iso) "Wed 23 Sep"     Core.fmtDateTime(iso) "Wed 23 Sep 17:50"
Core.dayNumber(born, iso)      1-based day of life for the heading
```

`recentMls` everywhere = the bottle **totals** of the last 10 feeds that had any bottle. The three
`describe` examples, the `stepMl`/`chipStepMl` thresholds, the `quickAmounts` examples, the
`ageText` boundaries, a DST-crossing `isoLocal` case and the `data_cases.json` fixture are the
`test_core.py` fixtures.

---

## 6. The PC app — `app.py`, `static/`, `launch.py`

### 6.1 Server

Flask at `127.0.0.1:8766` (`server.bind_lan: true` serves the home network too, as in whiskey).

`create_app(config_path="config.yaml", *, app_folder=None, output_folder=None, data_dir=None,
rollup_delay_s=20)`. Precedence for the journal root: argument > env `BABY_LOG_APP_FOLDER` >
`cfg.paths.app_folder`; the same for the output folder with `BABY_LOG_OUTPUT_FOLDER`. `data_dir`
(default `cfg.paths.local_data`) holds `settings.json` and `backups/`. `rollup_delay_s=None`
disables every background thread (tests). Tests write a minimal `config.yaml` into a
`tempfile.mkdtemp()` folder and pass all three paths under it; `test_app.py` asserts no file is
created outside that folder. `app.py` also exposes `STATIC_DIR` and `CORE_JS`, and `launch.py`
calls `create_app(config_path)` exactly as whiskey's does.

`config.example.yaml` has exactly: `paths.app_folder`, `paths.output_folder`, `paths.local_data`
(`./data`), `paths.backups` (`./data/backups`), `paths.backup_keep` (30), `server.host`,
`server.port` (8766), `server.bind_lan` (false), `auth.client_id`, `auth.authority`,
`auth.scopes`, `auth.redirect_uri_dev`, `auth.redirect_uri_prod`. The device label is never in
config.yaml. `test_setup_machine.py` asserts the generated `config.yaml` has the same key set.

**Settings** (`data/settings.json` on the PC; `bl.settings` on a phone) have exactly these keys on
every device: `{label: str, units: "ml"|"oz", step_ml: number|null (null = automatic via
Core.stepMl), quick_mode: "recent"|"range"|"custom", quick_custom: [ml…], quick_from: ml|null,
quick_to: ml|null, quick_step: ml|null, night_from: "HH:MM",
night_to: "HH:MM", child_id: str|null}`; the phone adds `device`. Defaults: `label ""`, `ml`,
`null`, `range`, `[]`, `50`, `100`, `10`, `21:00`, `07:00`, `null`.

JSON API. Every response is `{"ok": true, ...}` or `{"ok": false, "error": "…"}`. Errors:
`ValueError` → 400, `KeyError` → 404, `FileExistsError` and "Excel has the workbook open" → 409,
deleting an already-deleted event or restoring a live one → 409, no child → 400 `no child`.

| Route | Response |
|---|---|
| `GET /` | `static/index.html`; `GET /core.js` → `docs/core.js`; `GET /static/<file>` |
| `GET /api/config` | `{ok, child: rec\|null, children: [rec], settings, version: str, app_folder: str, output_folder: str, label: str}` |
| `GET /api/now` | `{ok, now: iso, last_feed: rec\|null, last_diaper: rec\|null, running: [rec…] (every live feed/sleep with end null), today: Core.totals shape, usual_gap_s: int\|null, next_feed_at: iso\|null, targets}` |
| `GET /api/day?date=` | `{ok, date, events: [rec], totals, has_prev, has_next}` — `events` = live events whose `time[:10] == date`, sorted; `has_prev`/`has_next` = any live event on an earlier/later date |
| `GET /api/events?from=&to=` | `{ok, events}` inclusive local dates |
| `GET /api/event/<id>` | `{ok, event: latest rec incl. tombstone, history: [every revision ascending]}` |
| `POST /api/event` | 201 `{ok, event}`. Body = client-owned fields `{event_id?, child_id?, type, time, end, data, note, logged_by?}`; `child_id` defaults to the current child; `logged_by` defaults to `settings.label` on a new event and is carried on a revision unless sent. The server stamps `device: "pc"`, `entered_from: "pc"`, `edited_by: settings.label` (revisions), ids and `created_at`. An `event_id` that is on file writes a revision; one that is not on file is a 404. |
| `DELETE /api/event/<id>` | `{ok, event: tombstone}`; JSON body `{reason?}` |
| `POST /api/event/<id>/restore` | `{ok, event}` |
| `GET /api/deleted` | `{ok, events}` newest tombstone first |
| `GET /api/needs-check` | `{ok, events}` live events whose `note` starts with `Check: ` or carries ` — Check: ` after the row's own note (the paper import writes both forms, §10) |
| `GET /api/children` · `POST /api/children` | `{ok, children}` · 201 `{ok, child}` (create, or revise when `child_id` is sent) |
| `GET /api/settings` · `POST /api/settings` | `{ok, settings}`; POST is a shallow merge of the listed keys only; unknown keys → 400 |
| `POST /api/rollup` | `{ok, path}` — regenerate `Baby Log.xlsx` now |
| `POST /api/daysheet/<date>` | `{ok, path}` — writes `Day sheets/<date>.html` in the output folder |
| `GET /print/day/<date>` | the printable day sheet (HTML) |
| `GET /print/range?from=&to=` | printable daily-totals summary |
| `GET /api/health` | `{ok: true, journal: stats, newest_file_at: iso\|null, rollup_at: iso\|null, version}` — `launch.py` polls this |
| `/api/heartbeat`, `/api/goodbye`, `/api/window` | exactly as whiskey's `launch.attach_lifecycle` expects |

**The rollup runs** at startup, 20 s after any API write, and whenever a background scan (every
60 s) finds a journal file the last rollup did not see (`Journal.fingerprint()`: file count and
newest mtime — not `created_at`, which a late phone upload can carry from hours earlier) — phones' entries arrive
through the OneDrive client with no API call, so this is what keeps `Baby Log.xlsx` current. All
of it is debounced into one background thread; skipped with a logged warning while
`~$Baby Log.xlsx` exists. Timers on the PC: `POST /api/event` with `data.timer` set and `end: null`
starts one; the client sends the folded revision on Switch/Stop. The server does no timer
arithmetic.

### 6.2 Screens (`static/index.html`, `app.js`, `style.css`)

Mockups are in the proposal artifact; build to them. Light theme, the palette from the proposal
(`--feed:#C4661A --diaper:#0E7773 --wet:#2A74BA --dirty:#85552A --bg:#F2F5F4`),
`font-variant-numeric: tabular-nums` on every number, a CJK fallback (`"Microsoft YaHei"`) in the
font stack. `<title>Baby Log</title>` exactly (the launcher finds the window by title) and the
goodbye handler sets `document.title = "Baby Log (closed)"` as whiskey's does.

- **Today** (the entry screen): the Now panel — since-last tiles for feed and diaper (each opens
  that entry's editor), every running feed/sleep as a card with the live timer and Switch/Stop
  (opens its editor; works whichever device started it), a stale-timer warning row, usual gap and
  next-feed guess, today's totals with targets when set — then the **day sheet** in the paper's
  two-column layout (feeding | diapers), followed by an **Other** section listing every sleep,
  pump, growth, health and note of the day in time order, `‹ prev / next ›` day navigation, and
  the log buttons: **Feed**, **Diaper Wet / Dirty / Both** (one click), **Sleep**, **Pump**,
  **Weight**, **More** (health, note). Each cell of the day sheet (feed side, diaper side, note) is
  its own click target with a hover outline; checkboxes are read-only glyphs (the dirty one tinted
  by stool colour); toggling happens in the editor.
- **Editor dialog**, one per type, used for new and existing entries alike. Common controls at the
  top: **Start** date-time, chips `−5 · −15 · −30 min` that shift the entry's current time (the
  resulting `Wed 23 Sep 02:45` shown beside them), **End** date-time for feed/sleep/pump (blank
  while running), **Who** chips (labels seen in the journal plus this device's), **Change type…**
  (keeps time, end, note, who and child; resets `data` to the new type's defaults), the child
  chooser when two children exist, note. Feed (bottle only, since 27 Sep 2026): portions, each
  with a kind toggle (Formula / Breast milk, formula preselected), the amount (−/+ by `step_ml`,
  the quick-amount chips of §8.1, typed), and for formula the **formula chips** — the names used
  most recently (`Core.formulaChoices`), the last one preselected so switching to plan B is one tap,
  plus **Other…** to type a new name; **Another portion**; made / leftover (when both are set and no
  portion was typed, one formula portion of made − leftover is filled in, editable; save refuses
  made < leftover). No side timers, no typed minutes; a paper row's breast minutes show as one
  read-only line. **End** is hidden for feeds (a bottle has no useful end). Existing entries have a
  **Delete** button at the foot. Save validates: `time` not before the child's `born` and not after
  now + 10 min, `end` not before `time`; refusals are in-page messages.
- **Feed** always opens a new bottle feed. (Running-feed cards, Merge and the stale-timer warning
  only ever appear for a record that still carries a `timer` — none will after 27 Sep 2026, but a
  reader must not crash on one.)
- **Catch up** (a button beside the log bar on the PC; under **More** on the phone): for the paper
  slips written when no phone was to hand. One screen: a date (default today), then a strip that
  logs one entry per tap and stays put for the next — a time field, **Feed** with the quick-amount
  chips (formula = the last used), or **Wet · Dirty · Both**; each tap saves an ordinary entry at
  that date and time and appends it to a list under the strip (each row opens its editor, swipeable
  on the phone), then clears only the time. The date stays until changed. Nothing is held back for a
  "save all": every tap is already a journal file.
- One-click diapers show a 6-second toast `Wet + dirty · 03:12 · Undo · Edit`. A one-click diaper
  within 2 minutes of the previous diaper logged from this device does not write; it opens that
  entry's editor with the line "Same as the 03:12 one? Save adds to it · Log another adds a new
  one". Every Delete shows a 6-second `Deleted · Undo` toast (Undo restores).
- **Trends**: daily totals table for the last 14 days with targets, and the 24-hour rhythm chart
  (inline SVG, no library: feeds as bars by start time and breast length, wet/dirty as dots, night
  shaded) for the last 7 days.
- **Growth**: weight/length/head list with change from birth weight; rows open the editor.
- **Health**: medicines and temperatures, "last given 5 h ago" per medicine name; rows open the
  editor.
- **Reports**: print day sheet, print a date range, Save day sheet to Yisen File, Rebuild
  Baby Log.xlsx, open the folder.
- **Settings**: this PC's label, units, step, quick amounts, night hours; the child (name, born,
  born time, birth weight, targets); **Deleted** (Restore); **Needs check (n)** (rows open the
  editor; the count shows on the Settings tab until zero).
- Top bar: child name + age, the journal pill (`N entries · newest 19:04`), the label.

### 6.3 `launch.py`, tray, exe, updater, setup

Port whiskey's `launch.py`, `run.bat`, `build_exe.bat`, `update.bat`, `tools/update.py`,
`tools/setup_machine.py`, `tools/make_shortcut.py` and their tests **with the names changed and
nothing else** (the port map is in the workflow scout report): window title and `<title>`
`Baby Log`; exe `Baby Log.exe`; mutex `Local\BabyLog.%d`; Edge profile dir `BabyLog\window`; tray
icon name `baby_log`, tooltip `Baby Log`; port 8766; `run.bat`'s minimised console titled
`Baby Log launcher` (distinct from the window title on purpose); `static/icon.ico` present
because the tray reads `app_mod.STATIC_DIR / "icon.ico"`; `update.py` clone URL
`https://github.com/RollingShuttle/baby-log.git` (placeholder until the repo exists). Env var
`BABY_LOG_APP_FOLDER` belongs to store/app/rollup, not the launcher. `setup_machine.py` finds
OneDrive, writes `paths.app_folder = <OneDrive>/Apps/Baby Log` and
`paths.output_folder = <OneDrive>/文档/Yisen File`, creates both if missing, and (best effort,
Windows only) pins the app folder with `attrib +P /S /D` so Files On-Demand never leaves
placeholders. Keep whiskey's rule that the tests assert `update.py`'s build flags match
`build_exe.bat` (both `--add-data` flags, §2).

---

## 7. The phone app — `docs/`

### 7.1 Transport (`graph.js`)

Port whiskey's `graph.js` (MSAL redirect flow, `consumers` authority, one scope
`Files.ReadWrite.AppFolder`, MSAL loaded on demand from
`https://cdn.jsdelivr.net/npm/@azure/msal-browser@4/lib/msal-browser.min.js` — v4 ≥ 4.26 keeps
the cache readable after iOS kills the app when the user answered **Yes** to "Stay signed in?";
SETUP.md says to answer Yes; `redirectUri` = the page URL without hash/query, as whiskey). Changes:

- `token({interactive: false})` is what every background call uses: on silent failure it throws
  `SignedOutError`, sets `meta.signed_out = true` and **never redirects**. Only an explicit tap on
  the pill or Settings → Sign in calls `acquireTokenRedirect`, and never while an editor is open.
- `listFolder(path)` → `[{name, size, eTag, isFolder, downloadUrl}]` from
  `GET /me/drive/special/approot:/<path>:/children?$select=id,name,size,eTag,file,folder,@microsoft.graph.downloadUrl&$top=500`,
  following `@odata.nextLink` until absent. 404 → `[]`.
- `getText(downloadUrl)` — a bare `fetch(url)` with **no headers** (the URL is pre-authenticated;
  adding a header forces a CORS preflight that the download host refuses). Never cache the URL.
  When the annotation is missing, fall back to `getJSON(path)` via `:/content` with the bearer
  token (what whiskey does).
- `putJSON(path, body)` — idempotent PUT to `:/content`. On 404 (the day folder does not exist),
  `POST /me/drive/special/approot:/events:/children` `{name: <day>, folder: {},
  "@microsoft.graph.conflictBehavior": "fail"}` (409 → ignore) and retry the PUT once.
- Every call classifies failures: **retryable** (network error, 408, 429, 5xx) — on 429/503 read
  `Retry-After` (seconds; if the header is not exposed, back off 10 s doubling to 5 min) and
  suspend *all* Graph calls, the poll timer included, for that long; **signed out** (401/403) —
  set `meta.signed_out`, stop background sync; **permanent** (other 4xx) — the caller decides.
  The error surfaced to the UI carries the Graph error `code` and `message` (the first-run
  provisioning problem on new AppFolder-only apps shows as `accessDenied` / `serviceReadOnly`;
  SETUP.md's troubleshooting names it).

### 7.2 Local store (`store.js`)

Records live in **IndexedDB** (database `baby-log`, object stores `events` keyed by `event_id`,
`children` keyed by `child_id`, `queue` keyed by `qid`) with an in-memory mirror loaded once by
`await Store.open()` at boot, so every read is synchronous from memory and every write goes to
memory *and* IndexedDB and is awaited before the UI says "Saved". A failed IndexedDB write reverts
the memory copy and throws `StorageError`; the UI shows "Not saved — storage full" and keeps the
editor open. `navigator.storage.persist()` is requested once after the first write. Small state
stays in localStorage under `bl.`: `settings` (§6.1 keys plus `device`), `meta`
(`last_sync_at`, `full_sync_at`, `signed_out`, `last_error`, `signed_in_as`, `backoff_until`),
`seen` (`{"<YYYY-MM-DD>": [names…]}` keyed by day folder, pruned to the three most recent keys),
`done` (day-folder dates fully caught up), `draft` (§7.4), `failed` (uploads Graph refused).
Every localStorage read and write is guarded with try/catch as in whiskey, and every write's
result is checked.

- `Store.newEvent(fields)` builds the record (§3.2) with `entered_from: "phone"`, `device`,
  `logged_by` (defaults to `settings.label`), validates with `Core.validate`, saves it, and queues
  `{qid: Core.newId("Q"), kind: "event", path: null, body, created_at}`. **The path is assigned on
  the first upload attempt** (`events/<utc-today>/<Core.fileName(id, rev)>`), written back to the
  queue item before the PUT, and reused on retries — except that if at flush time the path's
  folder is neither UTC today nor UTC yesterday, `Sync.flush` re-assigns
  `events/<utc today>/<id>-r<n>-<fresh w>.json` before sending (a stale duplicate is harmless:
  identical bytes, identical resolution).
- `Store.revise(held, fields)`, `Store.tombstone(held, reason)`, `Store.restore(held)` use
  `held.revision + 1`, carry `logged_by` (unless `fields.logged_by`), stamp `edited_by`, and queue
  likewise. `Store.reviseChild(held, fields)` the same for children (`kind: "child"`).
- `Store.applyRemote(record, fileName)` replaces the held record iff
  `Core.resolve([held, record]).get(id) === record` (record `_file` set to `fileName`) and returns
  `true` when it replaced. The queue is left untouched (a superseded queued revision still uploads;
  resolution ignores it).
- Pruning keeps records whose `time` is within the last **120 days** or in the future; a record
  referenced by any queue item is never pruned. RUNNING.md says the phone shows 120 days and the
  PC everything.
- `Store.usage()` for Settings (record count, queue length, storage estimate when available).

### 7.3 Sync (`sync.js`)

- `Sync.flush()` — uploads the queue in `created_at` order. Stops at the first retryable failure
  and keeps the rest. A permanent failure (4xx other than 401/403) moves the item to `bl.failed`
  with the status and message and continues; Settings lists failed items with **Retry** and
  **Discard**. 401/403 stop the flush and mark signed out. `drop(qid)` after a successful PUT.
- `Sync.pull()` — lists every UTC day folder from `localDate(meta.last_sync_at) − 3 days` through UTC
  today (capped at 120 folders, in which case it is a catch-up), downloads every listed file whose
  name is not in `seen[folder]` and whose `(id, rev)` from `Core.parseName` is not already held —
  an equal-`rev` file with a different `w` **is** downloaded — applies each with
  `Store.applyRemote`, records it as seen, then lists `children/` and applies. `meta.last_sync_at`
  is set only after a pull completes with no errors. **Catch-up** (first sign-in, or
  `meta.full_sync_at` older than 30 days): list `events/` (folders only); for every folder within
  120 days of today and not in `bl.done`, list it and download what is not held; add the date to
  `done` only when the pass was clean (no zero-byte listing, no unreadable download) and it is
  older than UTC yesterday; set `full_sync_at` when the loop finishes clean. Settings → **Sync now**
  clears `done` and forces a catch-up. **Collisions are named, not hidden:** when a downloaded
  record has the same revision as one this phone wrote (different `device`), the §3.4 winner still
  stands, but the id goes onto `meta.conflicts`, a toast says `Feed 02:10 · Updated from the PC`
  (or `Deleted on …`) with Edit, and Settings lists them under *Changed on two devices*.
- Runs on open (after `Graph.resume()` and `handleRedirectPromise`), on `visibilitychange` to
  visible, on `online`, after every local write (flush then pull), and every **45 s ± 10 s jitter**
  while the page is visible. Never while hidden, never while `meta.backoff_until` is in the future.
  After a pull changes a record an open editor or timer card is showing, that screen re-renders
  from the new record with a one-line notice `Updated from Mom's phone`. A Switch/Stop on a feed
  whose latest revision was written by another device runs flush-then-pull first and refuses with
  "Updated on Dad's phone — look again" if the pull changed it.
- A pull is mandatory before any revise/tombstone when `last_sync_at` is older than 5 minutes (the
  editor shows a `Syncing…` line and proceeds when it finishes or fails).
- **Sync is a button, and it shows its work.** Tapping the pill while signed in runs `Sync.run()`
  at once; while it runs the pill reads the phase and the count — `Syncing… sending 2 of 5`,
  `Syncing… checking 4 days`, `Syncing… reading 12 new` — and for six seconds afterwards the
  outcome — `Synced · 5 sent · 12 new` (or `Synced · nothing new`). `sync.js` emits
  `("progress", {phase, done, total})` through `Sync.onChange` for this; Settings → Sync shows the
  same line under a **Sync now** button (which also forces the catch-up, §7.3).
- The **status pill** sits on every screen: `Synced 1 min ago` · `Syncing…` · `Offline · 2
  waiting` · `Signed out · 3 waiting · tap to sign in` · `Signed out · showing data from 14:02` ·
  `Sync failed · 19:03 · tap for details` · `1 stuck · tap`. An item queued for more than 24 h
  turns the pill amber.

`sync.js` keeps its pure helpers (`Sync.foldersToList(lastSyncIso, todayUtc)`,
`Sync.pathFor(item, todayUtc)`, `Sync.classify(status, body)`, `Sync.backoffMs(retryAfter,
attempt)`) on the `Sync` object and ends with a Node `module.exports` guard so `tests/test_sync.py`
can run them under Node (skipping without Node): a 3-day-old `last_sync_at` yields seven folders;
a stale path is re-assigned; 429 → retryable, 400 → permanent, 401 → signed out.

### 7.4 Screens (`app.js`, `index.html`, `style.css`)

Build to the six phone mockups in the proposal: **Now**, **Log a feed**, **Diaper**, **Day**,
**Night mode**, **Settings**; tabs Now · Day · Trends · Settings. The sheets for sleep, pump,
growth (weight) sit on the Now log bar beside the diaper buttons (as the approved mockup shows);
health and note live under **More**. Rules:

- **Every surface that shows an entry opens its editor** (§8.3): Now's since-last tiles and running
  cards, Now's recent list (the last 10 events of any type), every cell of the Day sheet and every
  row of its Other section, the Deleted and Needs-check lists in Settings, the Undo toast's Edit.
- The editor has the same controls as the PC's (§6.2): Start with `−5 · −15 · −30 min` chips, End,
  Who chips, Change type…, note, Delete at the foot with an in-page confirm sheet (`Delete feed
  02:10?` with two 48 px buttons `Keep` / `Delete`; in night mode the destructive one is outlined
  and reads `Delete`, never an icon), and the same validation. Feed: bottle portions with the
  quick-amount chips and the formula chips, made / leftover; no side timers (§6.2). **Catch up**
  under More, as on the PC. One-tap diapers, the 2-minute same-diaper check, the `Undo · Edit` toast and the
  `Deleted · Undo` toast as on the PC. Toasts sit above the tab bar inside the bottom safe area
  with a 44 px Undo target.
- **Drafts.** Every open editor writes `bl.draft` = `{screen, event_id|null, fields, saved_at}` on
  each input (debounced 300 ms) and clears it on Save/Delete/Cancel. On open, a draft under 12 h old
  reopens that editor with the fields restored and a `Draft restored` line — iOS reloads a
  home-screen app freely and a redirect sign-in reloads it too.
- First run asks **"Who is holding this phone?"** — `Dad` / `Mom` / `Other…` — before anything
  else; the label can be changed in Settings. Sign-in is a button in Settings and on the pill.
- **Night mode** turns on between `night_from` and `night_to` (default 21:00–07:00) and the moon
  button overrides it; the override (`bl.settings.night_override: "on"|"off"|null`) persists until
  the next scheduled boundary, then clears. It is the dim red-on-black palette in the mockup,
  applied by a `night` class on `<body>` (the body carries the background so the safe areas are
  dark), and `app.js` sets `meta[name=theme-color].content` to `#000000` while night is on and
  back to `#F2F5F4` after.
- Trends on the phone in v1 is the 7-day daily totals table with targets.
- Settings: label, units, step, quick amounts, night hours, child (revise name/born/targets),
  sign in / out (`Signed in as …`), sync details (last sync, waiting, failed with Retry/Discard,
  storage usage), **Deleted**, **Needs check (n)**.

### 7.5 iOS rules (whiskey SPEC §9.2 — all of them still apply)

`viewport-fit=cover`; safe-area insets on every edge; `100dvh` never `100vh`; 44 px touch targets;
16 px inputs; `inputmode="numeric"` on ml amounts and `"decimal"` on oz amounts and temperatures;
the tab bar hides for the keyboard; every pushed screen has its own back chevron;
`apple-mobile-web-app-capable`, `mobile-web-app-capable`,
`apple-mobile-web-app-status-bar-style` **`black-translucent`**; a 180×180 `apple-touch-icon`;
`manifest.webmanifest` with `display: standalone`, `start_url: "."`, `scope: "."`,
`theme_color: "#F2F5F4"`; `<meta name="theme-color" content="#F2F5F4">`; `color-scheme: light`
(night is a class, not a scheme); a service worker that precaches the shell (**bump `VERSION` on
every change to `docs/`**); no `confirm()`/`alert()` anywhere. `tests/test_phone.py` ports
whiskey's checks — every precached file exists, the manifest is valid with those fields, the icon
is a real 180-square PNG, `CLIENT_ID` is blank in the committed `config.js`, the iOS rules above
are present in the markup/CSS, every `type` in §3.2 has a row renderer carrying `data-event-id`,
`bl.draft` is written on input, and `confirm(` does not appear in the code.

### 7.6 Signed-out behaviour

First open: the label prompt, then the Now screen. Everything except sync works signed out — the
store needs no token. `Sync.flush`/`pull` return early with `{skipped: "signed_out"}` when
`Graph.isSignedIn()` is false and do not set `last_error`; the pill reads `Signed out · N waiting ·
tap to sign in`, or `Signed out · showing data from <clock>` when the queue is empty. The first
successful sign-in runs flush, then the catch-up pull, and records `meta.signed_in_as`. Signed out
never blocks logging; entries queue and upload after the next sign-in — RUNNING.md says so in
those words.

---

## 8. Behaviour shared by both front ends

### 8.1 Bottle amounts (the "grows with him" rule)

Stored whole ml; displayed in the device's unit; `Core.fromUnit` rounds to the nearest ml, and an
editor keeps the stored ml for any amount control the user did not touch (a note edit in oz mode
must not turn 22 ml into 22.18). `step_ml` (−/+) defaults to `Core.stepMl`; quick amounts are
`Same as last · N` plus, by `quick_mode`: **range** (the default since 27 Sep 2026) —
`Core.quickRange(quick_from, quick_to, quick_step)`, e.g. 50 · 60 · 70 · 80 · 90 · 100, with a
small **range** control right beside the chips in the feed editor (from / to / step, saved to
settings the moment they change, so the range moves up the week his feeds do) as well as in
Settings; **recent** — `Core.quickAmounts`; **custom** — the typed list. No maximum anywhere;
`Core.unusual` makes Save ask "That's more than twice his biggest recent feed. Save anyway?" once.

**Formula memory.** `Core.formulaChoices` takes the formula names of the most recent portions
(newest first, from the events this device holds) and the feed editor preselects the first; a name
typed under **Other…** becomes the first choice on the next feed by virtue of being the newest.
Nothing is stored in settings for this, so both phones and the PC agree without configuration.

### 8.2 Since-last and next feed

`last_feed` is the most recent feed by `time`.
`usual_gap` is `Core.usualGapMs`; `next_feed_at = last_feed.time + usual_gap`. Hints, never alarms.

### 8.3 Editing and deleting — the rule the owner asked for

These surfaces open the entry's editor on tap/click, on both PC and phone: since-last tiles,
running-timer cards, the recent list, every day-sheet cell and Other row, the Growth and Health
lists, the Trends tables' rows where they name an entry, the Deleted list (Restore), the Needs-check
list, and the Undo toast's Edit. The editor shows every field including date and time, end, who,
and type. Save writes a revision; Delete writes a tombstone after an in-page confirm and shows
`Deleted · Undo`; deleted entries stay listed under Settings → Deleted with Restore. A change made
on one device reaches the other on its next pull, and the PC on the OneDrive client's next sync.

### 8.4 Device label

Each device has a label (`Dad`, `Mom`, free text), stamped into `logged_by` by default and into
`edited_by` on revisions. Every entry shows its `logged_by` tag; the PC's history view shows
`edited_by` per revision.

---

## 9. `rollup.py` — the readable files in Yisen File

Regenerated whole from the journal (whiskey's `_backup` with microsecond names, `is_locked`, atomic
replace); never hand-edited; regenerates if deleted; refuses while `~$Baby Log.xlsx` exists; keeps
the last 30 backups in `data/backups/`; skips an unreadable journal file with a log line rather
than aborting.

`Baby Log.xlsx` sheets, header row 1, one row per live event, oldest first: `Feeds`
(`date time end logged_by breast_min left_min right_min bottle_ml formula_ml breast_milk_ml made_ml
leftover_ml note event_id`), `Diapers` (`date time logged_by wet dirty color texture size rash
blowout note event_id`), `Sleep` (`date start end minutes where logged_by note event_id`),
`Pumping`, `Growth`, `Health`, `Notes`, and `Daily` (`date feeds bottle_ml breast_min wet dirty
sleeps sleep_min pumps pump_ml`) — one row for every local date from the first event to today,
zeros when empty; `*_min` columns are `round(seconds / 60, 1)`.

`rollup.day_sheet_html(child, events, date, settings) -> str` is the **one renderer**:
`/print/day/<date>` returns it and `/api/daysheet/<date>` writes it to `Day sheets/<date>.html`.
Content: heading `<name> — Feeding & Diapering — <Core.fmtDay> (day <n>)`; left table `Time ·
Breast (min, L/R, ~ when approx) · Bottle (unit, kind) · Made / Leftover · By · Note`; right table
`Time · Wet · Dirty · Colour / texture · By · Note`; an Other table when there are other types; a
footer line from the totals (`8 feeds · 135 ml bottle · 57 min breast · 6 wet · 4 dirty`) with
targets alongside when set; `<style>` is the inlined `static/print.css` with
`@page { size: Letter; margin: 0.5in }`; black on white; no external URLs. `/print/range` is one
table with the `Daily` columns.

---

## 10. `paper.py` — importing the paper sheet

`tools/paper_sheet.json` = `{source: str, child: {name, born}, feeds: [{date: "YYYY-MM-DD", time:
"HH:MM", written: str, breast_s: int|null, approx: bool, bottles_ml: [number], note?: str, check?:
str}], diapers: [{date, time, wet: bool, dirty: bool, note?: str, color?: enum, texture?: enum,
check?: str}]}`.

Mapping: feed → `data.breast = {left_s: null, right_s: null, total_s: breast_s, last_side: null,
approx}`, `data.bottles = [{kind: "formula", ml} for ml in bottles_ml]`, `made_ml`/`leftover_ml`
null, `end` null; diaper → the listed keys over the defaults. `note` = the row's `note`, then, if
`check` is present, `Check: <check>` (joined with ` — ` when both); the `written` text is not
stored. `logged_by: "paper"`, `device: "paper"`, `entered_from: "paper"`.
`event_id = E-paper-<YYYYMMDD>-<HHMM>-<type>`; the import **refuses to run** if two rows produce
the same id. `time` = the naive local date+time resolved with the PC zone's offset **on that date**
(`datetime(...).astimezone()`), `timespec="seconds"`.

Idempotent: `paper.py` calls `journal.event(event_id)` before each row and skips the row when any
revision (tombstone included) is on file, and passes `revision=1` so the store's guard is a second
line of defence. It prints and returns `{"written": n, "skipped": m, "child_id": …}`;
`tests/test_paper.py` asserts a second run writes zero files. Run by hand:
`python paper.py` (uses `config.yaml`; `--root` overrides). Creates the child only when the journal
has none.

---

## 11. Version 1 scope and build order

1. `store.py` + `tests/test_store.py`; `docs/core.js` + `tests/test_core.py` — both against
   `tests/fixtures/data_cases.json`. Prove the data model and the shared arithmetic first.
2. `app.py` + `rollup.py` + `static/print.css` + tests; `static/` screens; `docs/` transport,
   store and sync + `tests/test_sync.py`; `docs/` screens + `tests/test_phone.py`; `paper.py` +
   `tests/test_paper.py`.
3. `launch.py`, the `.bat` files, `tools/`, their tests — ported. `guide/SETUP.md`,
   `guide/RUNNING.md`, `README.md`, `CLAUDE.md`.
4. Full suite green; run `paper.py` for real; launch the PC app; review.

Day-one features (all in v1): since-last + usual gap + next feed guess; breast timer with sides,
last-side reminder, stale-timer warning; one-tap diapers with Undo/Edit; night mode;
edit/delete/restore everywhere; daily counts against targets; weight log with change from birth
weight; medicine log with "last given"; `Baby Log.xlsx`; printable day sheet; the paper import
with Needs check; device labels; sync status; editor drafts.

Not in v1 (documented as "Next" in RUNNING.md): sleep pattern charts beyond the PC rhythm chart,
milk stash, WHO percentile charts, vaccines, solids, milestones with photos, monthly archive
bundles for faster phone catch-up, a read-only view for others, Graph delta sync.

---

## 12. Setup the owner does (SETUP.md must walk through it)

1. Entra: **New registration** named exactly `Baby Log`, *Personal accounts only*, platform
   *Single-page application*, redirect URI = the exact GitHub Pages URL **with trailing slash**
   (added once Pages exists; nothing for localhost), delegated permission
   `Files.ReadWrite.AppFolder` only, no client secret. Copy the client ID into `docs/config.js` —
   tests enforce that the committed value is blank, so relax that test when it is filled in, as the
   whiskey project did. Troubleshooting note for the Aug–Sep 2026 provisioning problem on new
   AppFolder-only apps (`accessDenied` / `serviceReadOnly` on first sign-in): the one-time escape
   hatch is consenting to `Files.ReadWrite` once, then removing it.
2. GitHub: new repository, push, Pages from `main` `/docs`.
3. PC first: `python tools/setup_machine.py`, `pip install -r requirements.txt`, `python paper.py`
   (creates Yisen and the first three days), `build_exe.bat`, `python tools/make_shortcut.py`.
4. Both iPhones: Safari → the Pages URL → Add to Home Screen → open → choose Dad/Mom → Settings →
   Sign in with the owner's Microsoft account, answer **Yes** to "Stay signed in?".
