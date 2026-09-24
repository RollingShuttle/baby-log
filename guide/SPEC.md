# Baby Log — Build Spec

A feeding, diaper, sleep and health log for one child (more later), shared by two iPhones and one
PC through the owner's personal OneDrive. It replaces the hospital's paper *Feeding & Diapering*
sheet. Written 2026-09-23, from the approved proposal (https://claude.ai/artifact/Mva9Y3fzFx9dgqrJZ6NF7K)
and the decisions the owner confirmed the same day.

It is built on the structure of `E:\Claude Code\whiskey-tasting` (the Whiskey Tasting Book):
a Python/Flask PC app in its own window, a static iPhone web app on GitHub Pages, and a folder of
small immutable JSON files in OneDrive as the only transport. **Read that project's `CLAUDE.md`,
`launch.py`, `store.py` and `docs/graph.js` / `docs/store.js` before building the matching part
here** — the working style, the file-naming rules and the iOS rules all carry over. What does not
carry over is anything about the whiskey collection workbook: there is no master workbook here,
nothing is read-only, and no surgical zip write exists.

---

## 0. Decisions already made (do not reopen)

| Question | Decision |
|---|---|
| Accounts | Both phones sign in with the **owner's** personal Microsoft account. Each device carries a label saying who holds it. |
| Where the journal lives | `OneDrive\Apps\Baby Log\` — the Entra app folder, reached by phones with the `Files.ReadWrite.AppFolder` scope only. |
| Where the readable files live | `C:\Users\mikey\OneDrive\文档\Yisen File\` — `Baby Log.xlsx` and `Day sheets\`. The PC writes these; phones never touch them. |
| Phones | Both iPhones. Build to iOS conventions (§9). |
| Units | Stored in **ml**. Shown in ml by default; oz is a per-device display switch. |
| Version 1 scope | The "Day one" list in §11. Nothing from "Next" unless it is free. |
| The child | **Yisen**, born 2026-09-21 (time unknown — the first feed on the sheet is 14:00, the first diaper 15:00; store the date only until the owner fills in the time). |
| The paper sheet | Imported as the first three days (§10), with the eight uncertain readings flagged in the note so they can be corrected in the app. |
| Editing | **Every entry can be changed or deleted from every device, and it must be obvious how.** The owner asked for this explicitly. Tapping/clicking any entry anywhere opens its editor. Deleted entries are recoverable. |
| Name of the Entra registration | `Baby Log` — it becomes the folder name `OneDrive/Apps/Baby Log`. |
| PC port | **8766** (the whiskey app holds 8765; both may run at once). |

---

## 1. Project rules that carry over from the whiskey app

1. **Every generated filename is unique at sub-second resolution.** Ids carry a UTC timestamp *and*
   a random suffix. Two devices logging in the same second must never share a name. The whiskey
   project hit this bug three times; every one was silent.
2. **Journal files are immutable.** A correction is a new revision file; a deletion is a tombstone
   revision. Writers refuse to overwrite an existing revision file.
3. **Nothing is ever held only in memory on a phone.** Save locally, then queue the upload.
4. **Save each step as it is finished and run its tests before starting the next.** Every module
   has `tests/test_<module>.py` that runs standalone (`python tests/test_store.py`) and under
   discovery (`python -m unittest discover -s tests`). Tests use temp folders, never the real
   OneDrive folder, and fixtures are synthetic — the committed tree carries no personal data
   beyond the child's first name in `tools/paper_sheet.json`.
5. Commits use the repo-local noreply identity already configured (`RollingShuttle`), because the
   repository may be public for GitHub Pages.

---

## 2. Layout

```
baby-logging/
  app.py                  Flask server + JSON API at 127.0.0.1:8766, serves static/
  launch.py               window + tray + single instance (ported from whiskey; port 8766, names changed)
  store.py                the journal: children and events, revisions, tombstones, resolution
  rollup.py               writes Baby Log.xlsx and day-sheet HTML into Yisen File
  paper.py                the paper-sheet import (reads tools/paper_sheet.json)
  config.yaml             machine paths + device label            (gitignored)
  config.example.yaml     the template
  requirements.txt        openpyxl, PyYAML, Flask, pystray  (same pins as whiskey)
  run.bat  update.bat  build_exe.bat   icon.ico
  static/                 the PC front end (bundled into the exe)
    index.html  style.css  app.js  print.css
  docs/                   the iPhone client — GitHub Pages serves only / or /docs
    index.html  style.css  config.js  core.js  graph.js  store.js  sync.js  app.js
    sw.js  manifest.webmanifest  icon-180.png
  tests/                  test_store.py  test_app.py  test_rollup.py  test_paper.py
                          test_launch.py  test_phone.py  test_core.py  test_update.py  test_setup_machine.py
  tools/                  setup_machine.py  make_shortcut.py  update.py  paper_sheet.json
  guide/                  SPEC.md (this)  SETUP.md  RUNNING.md
  data/                   settings.json, backups/                  (gitignored)
```

`docs/core.js` is **shared**: the PC front end loads it too. `app.py` serves it at `/core.js` from
`docs/core.js` (resolved under `sys._MEIPASS` in the exe — `build_exe.bat` adds `docs/core.js`
as data alongside `static/`). One copy, no drift. `tests/test_app.py` checks `/core.js` serves
the same bytes as `docs/core.js`.

---

## 3. The OneDrive app folder — the journal

```
OneDrive/Apps/Baby Log/
  children/   C-<stamp>-<rand>-r<n>.json        one child, revisions for edits
  events/     <YYYY-MM-DD>/E-<stamp>-<rand>-r<n>.json   one feed / diaper / … per file
  meta/       (reserved; nothing in v1)
```

- `<stamp>` is UTC `YYYYMMDD-HHMMSS` (`store._stamp()` in whiskey); `<rand>` is 4 hex characters
  (`secrets.token_hex(2)` / `crypto.getRandomValues`). The random suffix is load-bearing (§1.1).
- **The day folder is the UTC date when the file is written** — on the PC, the moment of the write;
  on a phone, the moment of the *first upload attempt* (fixed then, so retries are idempotent). It is
  **not** the event's own date. A revision of a week-old event lands in *today's* folder. This is what
  lets a phone find every change by listing only the last two day folders (§7).
- **The event id never changes across revisions.** `E-20260923-225012-a1b2-r1.json`, `-r2.json`, …
  Readers take the highest revision per `event_id`. A missing lower revision is harmless.
- A **tombstone** is a full copy of the latest record with `"deleted": true` and a `reason`, as the
  next revision. Restoring writes another revision with `"deleted": false`. Nothing is ever unlinked,
  so the PC can list deleted entries and bring one back.
- The PC reads and writes this folder as ordinary files through the OneDrive client
  (`config.yaml: paths.app_folder`). Phones reach it only through Microsoft Graph with
  `Files.ReadWrite.AppFolder` (§7).
- Two files may be written for the same event by two devices at once (both edit the same feed):
  both are `-r2`. **Both names differ only if their revision numbers differ, so they do not** — a
  concurrent edit *can* collide on the filename. Guard: a revision filename is
  `<event_id>-r<n>-<rand>.json` where `<rand>` is fresh per write; the reader takes the highest
  `n`, and among equal `n` the latest `created_at`. So the full pattern is
  `E-20260923-225012-a1b2-r2-7c1d.json`. The same rule applies to children.

### 3.1 The event record

Written identically by `store.py` (Python) and `docs/store.js` (phone). Keys are fixed; unknown
keys are preserved by readers.

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
  "device": "d-3f9a",
  "entered_from": "phone",
  "created_at": "2026-09-23T22:50:12.123456+00:00"
}
```

- `time` is the moment the thing **started**, as an ISO-8601 local time **with its UTC offset**,
  whole seconds. `end` is the same shape for feeds, sleeps and pumps, `null` if not ended or not
  applicable. Days are grouped by the *local* date of `time` on the device doing the displaying —
  both parents live in one time zone, and the offset makes the instant unambiguous regardless.
- `created_at` is UTC with microseconds (`store._now_iso()` in whiskey). It orders revisions that
  tie on number and is never shown.
- `logged_by` is the device's label (§8.4): the literal string shown in the app — `Dad`, `Mom`, or
  whatever the owner typed. `device` is a per-install random id, for diagnostics only.
- `entered_from` is `pc`, `phone` or `paper` (the import).
- `type` is one of `feed diaper sleep pump growth health note`. `data` per type:

| type | data |
|---|---|
| `feed` | `{"breast": {"left_s": int\|null, "right_s": int\|null, "total_s": int\|null, "last_side": "left"\|"right"\|null, "approx": bool}, "bottles": [{"kind": "formula"\|"breast_milk", "ml": number}], "made_ml": number\|null, "left_ml": number\|null, "timer": {"side": "left"\|"right", "side_started": iso} \| null}` — `total_s` is the sum of the sides when they are known, or the typed "~15 min" (900, `approx: true`) when they are not. A running feed has `end: null` and `timer` set; the running side's elapsed time is `now − side_started` and is folded into `left_s`/`right_s` on switch or stop (each a revision). |
| `diaper` | `{"wet": bool, "dirty": bool, "color": "black"\|"dark_green"\|"green"\|"yellow"\|"brown"\|"other"\|null, "texture": "sticky"\|"seedy"\|"soft"\|"solid"\|"watery"\|null, "size": "small"\|"medium"\|"large"\|null, "rash": bool, "blowout": bool}` |
| `sleep` | `{"where": string\|null, "timer": {"running": true} \| null}` — `time`/`end` carry the span. |
| `pump` | `{"left_ml": number\|null, "right_ml": number\|null, "minutes": number\|null}` |
| `growth` | `{"weight_g": number\|null, "length_cm": number\|null, "head_cm": number\|null}` |
| `health` | `{"temp_c": number\|null, "medicine": string\|null, "dose": string\|null, "symptom": string\|null}` — vitamin D is a medicine named `Vitamin D`. |
| `note` | `{"milestone": bool}` |

Derived, never stored: bottle ml = sum of `bottles[].ml`; a feed's breast minutes = `total_s/60`.

### 3.2 The child record

`children/C-<stamp>-<rand>-r<n>-<rand>.json`:

```json
{"child_id": "C-…", "revision": 1, "deleted": false, "name": "Yisen", "born": "2026-09-21",
 "born_time": null, "sex": null, "birth_weight_g": null,
 "targets": {"feeds_per_day": null, "wet_per_day": null, "dirty_per_day": null},
 "created_at": "…"}
```

`born` is a local date; `born_time` `"HH:MM"` or null. Targets are what the pediatrician said, typed
by the owner; the app never invents them. Every event carries a `child_id`; with one child every
screen just uses the first non-deleted child. The chooser appears only when there are two.

---

## 4. `store.py` — the journal (Python)

`Journal(root)` mirrors whiskey's `store.Journal`, with these methods:

- `ensure()` — creates `children/`, `events/`, `meta/`.
- `write_child(name, born, ..., child_id=None)` → record; a `child_id` writes a revision.
- `children()` → resolved list (highest revision, tombstones dropped).
- `write_event(*, child_id, type, time, end=None, data=None, note="", logged_by, device,
  entered_from="pc", event_id=None)` → record. Validates `type` and the `data` keys for that type
  (§3.1) — unknown keys inside `data` raise `ValueError`; missing keys are filled with their null
  or false default. `time`/`end` must parse as ISO with an offset. Omit `event_id` for a new event;
  pass it to write a revision (revision = highest on file + 1).
- `delete_event(event_id, reason=None)` → tombstone; `restore_event(event_id)`.
- `events(include_deleted=False)` → resolved list sorted by `time` ascending;
  `events_on(local_date, tz)`; `event(event_id)` → latest record or None;
  `history(event_id)` → every revision, ascending.
- `write_running_feed / switch_side / stop_feed` helpers are **not** in store — the app layer does
  the folding and calls `write_event` with the event id.
- Day folder for a write: `datetime.now(timezone.utc).strftime("%Y-%m-%d")`.
- `stats()` for the status pill.

`_atomic_write_json` and the "refuse to overwrite an existing revision file" guard are copied from
whiskey. `resolve(records)` is a module-level pure function (highest revision, then latest
`created_at`) so `rollup.py` and `paper.py` share it.

---

## 5. `docs/core.js` — shared logic for both front ends

A single global `Core` (no modules, no build step) of pure functions with no DOM and no storage.
`tests/test_core.py` runs them under Node if `node` is on PATH and skips otherwise (do not make the
suite depend on Node); `tests/test_app.py` verifies `/core.js` serves it.

```
Core.stamp(date)             UTC "YYYYMMDD-HHMMSS"        Core.rand4()
Core.newId(prefix, date)     "E-<stamp>-<rand>"
Core.isoLocal(date)          "2026-09-23T17:50:00-05:00" (whole seconds, device offset)
Core.localDate(iso)          "2026-09-23" in the device zone
Core.resolve(records)        Map event_id -> latest record (revision, then created_at); deleted kept
Core.live(records)           the resolved records with deleted ones removed, sorted by time
Core.onDay(events, "YYYY-MM-DD")
Core.lastOf(events, type, before?)         Core.sinceText(ms)  "1 h 15 m"
Core.usualGapMs(events, type, n=6)         Core.nextFeedAt(events)
Core.totals(events, day)     {feeds, bottle_ml, breast_s, wet, dirty, sleeps, sleep_s, pumps, pump_ml}
Core.bottleMl(ev)            Core.breastSeconds(ev, now)   (folds a running timer)
Core.describe(ev, unit)      "5 min + 22 ml formula", "Wet + dirty · yellow", "Sleep 1 h 20 m"
Core.fmtAmount(ml, unit)     "22 ml" / "0.75 oz"          Core.toUnit / Core.fromUnit
Core.stepMl(recentMls, unit) 1|5|10 ml or 0.25|0.5 oz, from the median of the last 10 feeds
Core.quickAmounts(recentMls, unit, custom?)  four suggestions around the median, or the custom list
Core.unusual(ml, recentMls)  true above twice the biggest recent feed
Core.ageText(born, now)      "2 days old", "3 weeks 2 days", "4 months 1 week"
Core.isNight(now, {night_from: "21:00", night_to: "07:00"})
Core.fmtTime(iso)  "17:50"   Core.fmtDay(iso)  "Wed 23 Sep"
```

---

## 6. The PC app — `app.py`, `static/`, `launch.py`

### 6.1 Server

Flask at `127.0.0.1:8766` (`server.bind_lan: true` serves the home network too, as in whiskey).
Reads `config.yaml` beside itself (or beside the exe). Local settings that are per-machine but not
paths live in `data/settings.json`: `{"label": "Dad", "units": "ml", "step_ml": 1,
"quick_mode": "recent"|"custom", "quick_custom": [], "night_from": "21:00", "night_to": "07:00"}`.

JSON API (all responses `{"ok": true, ...}` or `{"ok": false, "error": "…"}` with 4xx):

| Route | Does |
|---|---|
| `GET /` | `static/index.html`; `GET /core.js` → `docs/core.js` |
| `GET /api/config` | child (first live), children, settings, `version`, `app_folder` |
| `GET /api/now` | `last_feed`, `last_diaper`, `running` (feeds/sleeps with `end: null`), `today` totals, `usual_gap_s`, `next_feed_at` |
| `GET /api/day?date=YYYY-MM-DD` | resolved events whose local date is `date`, sorted; totals; `has_prev`, `has_next` |
| `GET /api/events?from=&to=` | resolved events in a local-date range (inclusive) |
| `GET /api/event/<id>` | latest record + `history` |
| `POST /api/event` | new event, or a revision when `event_id` is on file. Body = the record fields the client owns (`child_id type time end data note logged_by`); the server stamps `device: "pc"`, `entered_from: "pc"`, ids and `created_at`. 201 with the record. |
| `DELETE /api/event/<id>` | tombstone (`reason` in JSON body optional) |
| `POST /api/event/<id>/restore` | revision with `deleted: false` |
| `GET /api/deleted` | tombstoned events, newest first, for the Deleted list |
| `GET/POST /api/children` | list / create or revise (by `child_id`) |
| `GET/POST /api/settings` | `data/settings.json` |
| `POST /api/rollup` | regenerate `Baby Log.xlsx` now; returns the path |
| `POST /api/daysheet/<date>` | writes `Day sheets/<date>.html` in Yisen File; returns the path |
| `GET /print/day/<date>` | the printable day sheet (self-contained HTML, `static/print.css` inlined) |
| `GET /print/range?from=&to=` | printable daily-totals summary for the pediatrician |
| `GET /api/health` | `{"ok": true, "journal": stats, "newest_file_at": iso}` |

The rollup also runs automatically **20 s after any write** (debounced, background thread) so the
Excel file stays current without a button. It is skipped, with a logged warning, while
`~$Baby Log.xlsx` exists (Excel has it open).

Timers on the PC: `POST /api/event` with `data.timer` set and `end: null` starts one; the client
sends the folded revision on switch/stop. The server does no timer arithmetic.

### 6.2 Screens (`static/index.html`, `app.js`, `style.css`)

Mockups are in the proposal artifact; build to them. Light theme (the PC is used in daylight),
the palette from the proposal (`--feed:#C4661A --diaper:#0E7773 --wet:#2A74BA --dirty:#85552A`),
`font-variant-numeric: tabular-nums` on every number, a CJK fallback in the font stack.

- **Today** (the entry screen): the Now panel (since-last tiles, usual gap, next feed guess, today's
  totals), the day sheet in the paper's two-column layout (feeding | diapers, with the dirty
  checkbox tinted by stool colour and the note column), `‹ prev / next ›` day navigation, and the
  log buttons: **Feed**, **Diaper Wet / Dirty / Both** (one click, with a 6-second Undo toast),
  **Sleep**, **Pump**, **Weight**, **More** (health, note).
- **Log / edit dialog**: one dialog per type. The feed dialog has the breast side timers (Left /
  Right, tap to start, tap the other to switch, Stop), a "or type minutes" box, bottle portions
  (kind toggle, amount with −/+ stepping by `step_ml`, quick amounts, "Another portion"), made/left,
  note, and the time (default now; a `−5 min` chip and a full date-time field). **Every row in the
  day sheet and the recent list opens this dialog for that entry; the dialog for an existing entry
  has a Delete button.** Editing writes a revision.
- **Trends**: daily totals table for the last 14 days, and the 24-hour rhythm chart (inline SVG,
  no chart library: feeds as bars by start time and breast length, wet/dirty as dots, night
  shaded) for the last 7 days.
- **Growth**: weight/length/head list with change from birth weight; add/edit.
- **Health**: medicines and temperatures, "last given 5 h ago" per medicine name; add/edit.
- **Reports**: print day sheet, print a date range, "Save day sheet to Yisen File", "Rebuild
  Baby Log.xlsx", open the folder.
- **Settings**: this PC's label, units, step, quick amounts, night hours, the child (name, born,
  targets), and the **Deleted** list with Restore.
- Top bar: child name + age, a journal pill (`N entries · newest 19:04`), and the label.

### 6.3 `launch.py`, tray, exe, updater, setup

Port whiskey's `launch.py`, `build_exe.bat`, `run.bat`, `update.bat`, `tools/update.py`,
`tools/setup_machine.py`, `tools/make_shortcut.py` and their tests **with the names changed and
nothing else**: window title `Baby Log`, exe `Baby Log.exe`, mutex/tray names `baby_log`, port
8766, env var `BABY_LOG_APP_FOLDER`, `icon.ico`. `setup_machine.py` finds OneDrive, writes
`paths.app_folder` = `<OneDrive>/Apps/Baby Log` and `paths.output_folder` = `<OneDrive>/文档/Yisen File`,
and creates both if missing. Keep whiskey's rule that the tests assert `update.py`'s build flags
match `build_exe.bat`.

---

## 7. The phone app — `docs/`

### 7.1 Transport (`graph.js`)

Port whiskey's `graph.js` (MSAL redirect flow, `consumers` authority, one scope
`Files.ReadWrite.AppFolder`, MSAL loaded on demand from jsDelivr) and add:

- `listFolder(path)` → `[{name, size, eTag, downloadUrl}]` for
  `GET /me/drive/special/approot:/<path>:/children?$select=name,size,eTag,file,@microsoft.graph.downloadUrl&$top=500`,
  following `@odata.nextLink`. 404 → `[]`.
- `getText(downloadUrl)` — plain `fetch` with **no** Authorization header (the URL is
  pre-authenticated); on failure fall back to `getJSON(path)` via `:/content`.
- `putJSON(path, body)` as in whiskey — idempotent PUT to `:/content`; Graph creates missing
  parent folders for a path PUT.

### 7.2 Local store (`store.js`)

localStorage keys prefixed `bl.`: `events` (a map `event_id → latest record`, kept to the last
**120 days** by `time` — say so in RUNNING.md), `children`, `seen` (filenames already read, per day
folder, last 3 folders only), `queue` (`[{path, body, kind, created_at}]`), `settings`
(label, units, step, quick, night hours, `device` id), `meta` (`last_sync_at`, `last_error`,
`signed_in_as`). Every read and write is guarded with try/catch as in whiskey.

`Store.newEvent(fields)` builds the record (§3.1) with `entered_from: "phone"`, saves it into
`events`, and queues `{path: null, body}` — **the path is assigned on the first upload attempt**
(`events/<utc-date-now>/<event_id>-r<n>-<rand>.json`) and then kept, so a retry writes the same
bytes to the same place. `Store.revise(previous, fields)`, `Store.tombstone(previous, reason)`,
`Store.restore(previous)` likewise. `Store.applyRemote(record)` merges a downloaded record (only if
it is a newer revision than what is held).

### 7.3 Sync (`sync.js`)

- `Sync.flush()` — uploads the queue in order; stops at the first failure and keeps the rest.
- `Sync.pull()` — lists `events/<utc today>` and `events/<utc yesterday>`, downloads every file not
  in `seen` (skipping names whose `event_id-r<n>` is already held), applies them, records them as
  seen, then lists `children/` and applies. Also on first sign-in or when `meta.full_sync_at` is
  older than 30 days: **catch-up** — list `events/`, and every day folder within the 120-day window
  that is not fully seen. Log counts.
- Runs on open, on `visibilitychange` to visible, on `online`, after every local write (flush
  then pull), and every **45 s** while the page is visible. Never while hidden.
- The status pill: `Synced 1 min ago` / `Syncing…` / `Offline · 2 waiting` / `Signed out · showing
  data from 14:02` / `Sync failed · 19:03 (tap for details)`. It sits on every screen.
- A running timer started on the other phone appears on this one when its record arrives.

### 7.4 Screens (`app.js`, `index.html`, `style.css`)

Build to the six phone mockups in the proposal: **Now**, **Log a feed**, **Diaper**, **Day**,
**Night mode**, **Settings**; tabs Now · Day · Trends · Settings. Add the sheets for sleep, pump,
growth (weight), health and note under **More**. **Every row (Now's recent list, the Day sheet)
opens the editor for that entry; the editor has Delete at the foot and a `−5 min` / date-time
control.** One-tap diapers show a 6-second Undo toast (Undo writes a tombstone).

First run asks **"Who is holding this phone?"** — `Dad` / `Mom` / `Other…` — and stores the label;
it can be changed in Settings. Night mode turns on between the configured hours (default
21:00–07:00) and can be overridden by the moon button; it is the dim red-on-black palette in the
mockup, applied by a `night` class on `<body>`.

Trends on the phone in v1 is the 7-day daily totals table only.

### 7.5 iOS rules (whiskey SPEC §9.2 — all of them still apply)

`viewport-fit=cover`, safe-area insets on every edge, `100dvh` never `100vh`, 44 px touch
targets, 16 px inputs, `inputmode="decimal"` on amounts, the tab bar hides for the keyboard, every
pushed screen has its own back chevron, `apple-mobile-web-app-capable`, a 180×180
`apple-touch-icon`, `manifest.webmanifest` with `display: standalone`, a service worker that
precaches the shell (bump its `VERSION` on every change), theme colour `#F2F5F4` (light shell; the
night palette is applied by class, so `color-scheme` stays `light`). `tests/test_phone.py` ports
whiskey's checks: every precached file exists, the manifest is valid, the icon is a real 180-square
PNG, `CLIENT_ID` is blank in the committed `config.js`, and the iOS rules above are present in the
markup/CSS.

---

## 8. Behaviour shared by both front ends

### 8.1 Bottle amounts (the "grows with him" rule)

- Stored ml; displayed in the device's unit. `step_ml` is the −/+ increment: default from
  `Core.stepMl` (1 ml while the median of the last 10 feeds is under 40 ml, 5 ml under 100, then
  10; in oz 0.25 under 1.5 oz then 0.5). The owner can pin a step in Settings.
- Quick amounts: `Core.quickAmounts` — "Same as last · N" plus four values around the median at the
  chip step, or a custom list. No maximum anywhere.
- `Core.unusual(ml, recent)` — above twice the biggest of the last 10 feeds the Save button asks
  "That's more than twice his biggest recent feed. Save anyway?" once.

### 8.2 Since-last and next feed

`last_feed` is the most recent feed by `time` (a running one counts, and shows as "feeding now").
`usual_gap` is the median gap between the last six feed starts; `next_feed_at = last_feed.time +
usual_gap`. Shown as hints, never as alarms.

### 8.3 Editing and deleting — the rule the owner asked for

Any entry, anywhere it is shown, opens its editor on tap/click. The editor shows every field
including the time and date. Save writes a revision; Delete writes a tombstone after a single
confirmation *inside the page* (no `confirm()`); deleted entries are listed under Settings →
Deleted (PC and phone) with Restore. A change made on one device reaches the other on its next
pull, and the PC on the OneDrive client's next sync.

### 8.4 Device label

Each device has a label (`Dad`, `Mom`, free text). It is stamped into `logged_by`. Shown as a
small tag on every entry ("Mom" / "Dad"), so at 3 a.m. it is clear who fed him last.

---

## 9. `rollup.py` — the readable files in Yisen File

Regenerated whole from the journal, like whiskey's `Whiskey Tastings.xlsx`; never hand-edited;
regenerates if deleted; refuses while `~$Baby Log.xlsx` exists; keeps the last 30 backups in
`data/backups/`.

`Baby Log.xlsx` sheets, header row 1, one row per resolved live event, oldest first:
`Feeds` (`date time end logged_by breast_min left_min right_min bottle_ml formula_ml breast_milk_ml
made_ml left_ml note event_id`), `Diapers` (`date time logged_by wet dirty color texture size rash
blowout note event_id`), `Sleep`, `Pumping`, `Growth`, `Health`, `Notes`, and `Daily` (`date feeds
bottle_ml breast_min wet dirty sleeps sleep_min pumps pump_ml`) — one row per local date from the
first event to today.

`Day sheets/<YYYY-MM-DD>.html` — written on request (`POST /api/daysheet/<date>`), the same HTML
as `/print/day/<date>`: the paper's layout, black on white, fits one Letter page.

---

## 10. `paper.py` — importing the paper sheet

`tools/paper_sheet.json` holds the transcription (18 feeds, 19 diapers, 21–23 Sep 2026, local
time `-05:00`… **check the owner's zone: use the PC's current offset at import time**). Each row
becomes an event with `entered_from: "paper"`, `logged_by: "paper"`, `device: "paper"`, and a
**deterministic** `event_id` (`E-paper-20260921-1400-feed`) so re-running the import is a no-op:
the writer's refuse-to-overwrite guard makes the second run skip every row and report it. The
random-suffix rule exists to separate concurrent writers; a one-off import with explicit identity
is the intended exception. Uncertain readings (eight of them, listed in the proposal) carry their
question in `note` prefixed `Check: ` — e.g. `Check: bottle amount unclear, written "4ml 1min + 1ml"`.
Bottle portions on the sheet ("5ml + 15ml") become two `formula` portions. Breast minutes written
"~15 min" become `total_s: 900, approx: true`; "<5 mins" → 300, approx.

Run by hand: `python paper.py --child <child_id>` (or `--child first`). Also creates the child if
the journal has none: Yisen, born 2026-09-21.

---

## 11. Version 1 scope ("Day one") and build order

1. `store.py` + `tests/test_store.py`; `docs/core.js` + `tests/test_core.py`. Prove the data
   model and the shared arithmetic first.
2. `app.py` + `tests/test_app.py` (Flask test client; a temp journal). `static/` screens.
3. `launch.py`, the `.bat` files, `tools/`, their tests — ported.
4. `docs/` phone app: transport, store, sync, screens; `tests/test_phone.py`.
5. `rollup.py` + `tests/test_rollup.py`; the print views.
6. `paper.py` + `tests/test_paper.py`; run it for real once the owner confirms the journal path.
7. `guide/SETUP.md` (Entra registration `Baby Log`, GitHub Pages, both phones), `guide/RUNNING.md`,
   `README.md`, `CLAUDE.md`.

Day-one features (all in v1): since-last + usual gap + next feed guess; breast timer with sides
and last-side reminder; one-tap diapers with Undo; night mode; edit/delete/restore everywhere;
daily counts against targets; weight log with change from birth weight; medicine log with "last
given"; `Baby Log.xlsx`; printable day sheet; the paper import; device labels; sync status.

Not in v1 (documented as "Next" in RUNNING.md): sleep pattern charts beyond the PC rhythm chart,
milk stash, WHO percentile charts, vaccines, solids, milestones with photos, monthly archive
bundles for faster phone catch-up, a read-only view for others.

---

## 12. Setup the owner does (SETUP.md must walk through it)

1. Entra: **New registration** named exactly `Baby Log`, *Personal accounts only*, platform
   *Single-page application*, redirect `http://localhost:8766` now and the Pages URL later,
   delegated permission `Files.ReadWrite.AppFolder` only, no client secret. Copy the client ID
   into `docs/config.js` — tests enforce that the committed value is blank, so relax that test when
   it is filled in, as the whiskey project did.
2. GitHub: new repository, push, Pages from `main` `/docs`.
3. Both iPhones: Safari → the Pages URL → Add to Home Screen → open → Settings → Sign in with the
   owner's Microsoft account → choose the label.
4. PC: `python tools/setup_machine.py`, `pip install -r requirements.txt`, `build_exe.bat`,
   `python tools/make_shortcut.py`.
