# Baby Log

A feeding, diaper, sleep and health log for one child, shared by two iPhones and one PC through
the owner's personal OneDrive. It replaces the hospital's paper *Feeding & Diapering* sheet, and
starts with that sheet imported.

Built on the structure of the Whiskey Tasting Book: a Python/Flask PC app in its own window, a
static iPhone web app on GitHub Pages, and a folder of small immutable JSON files in the OneDrive
app folder as the only transport.

## Shape

- **PC app** (Python, `app.py` + `static/`) reads and writes the journal through the OneDrive
  client as ordinary files, and regenerates the readable `Baby Log.xlsx` and printable day
  sheets into `Yisen File`.
- **Phone app** (static web, `docs/`) logs anywhere, with no signal — every entry is written to
  the phone first and queued — and reaches the journal through Microsoft Graph with the
  `Files.ReadWrite.AppFolder` scope only.
- **Sync** is the folder `OneDrive/Apps/Baby Log/`: one file per entry and per revision. No
  server runs. `docs/core.js` is shared by both front ends so they never disagree about a number.

## Ground rules

1. **Journal files are immutable.** A correction is a new revision file; a deletion is a
   tombstone revision; a restore is another revision. Nothing is edited in place, so two devices
   writing at once cannot damage each other's work and nothing deleted is lost.
2. **One filename rule** (`<id>-r<n>-<w>.json`, SPEC §3.1) with a fresh random `<w>` on every
   write, so two devices writing the same revision in the same second produce two files. The
   whiskey project hit the sub-second-collision bug three times.
3. **Both writers validate identically.** `store.py` and `docs/core.js` run every case in
   `tests/fixtures/data_cases.json`; a record either passes both or neither.
4. **Every entry can be changed or deleted from every device**, and every surface that shows an
   entry opens its editor (SPEC §8.3).
5. The phone never creates a child and never sees `Yisen File`; the PC never signs in to
   anything.

## Layout

```
*.py                    the app: server, journal, rollup, paper import (launcher: launch.py)
static/                 the PC front end, bundled into the exe
docs/                   the iPhone client (GitHub Pages serves only / or /docs)
tests/                  one file per module — python tests/test_<module>.py
tests/fixtures/         data_cases.json, the shared validation fixture
tools/                  scripts run by hand: setup_machine, make_shortcut, update; paper_sheet.json
guide/                  SPEC.md, SETUP.md, RUNNING.md
run.bat update.bat push.bat build_exe.bat   the things you double-click
```

## Modules

| File | What it does | Tests |
|---|---|---|
| `store.py` | the journal — children, events, revisions, tombstones, resolution, the defensive reader | `tests/test_store.py` |
| `docs/core.js` | the shared logic: ids, validation, resolution, totals, since-last, amounts, formatting | `tests/test_core.py` (runs under Node when one is found) |
| `app.py` | Flask server + JSON API at `127.0.0.1:8766`, the debounced background rollup | `tests/test_app.py` |
| `rollup.py` | `Baby Log.xlsx` and the day-sheet HTML, plus the Python port of the Core arithmetic | `tests/test_rollup.py` |
| `paper.py` | imports the transcribed hospital sheet, idempotently, with `Check:` notes | `tests/test_paper.py` |
| `launch.py` | window + tray + single instance, ported from whiskey; packaged by `build_exe.bat` | `tests/test_launch.py` |
| `static/` | the PC front end — `index.html`, `app.js`, `style.css`, `print.css` | — (via `test_app.py`) |
| `docs/graph.js` `store.js` `sync.js` | MSAL + Graph transport, IndexedDB store and upload queue, the flush/pull loop | `tests/test_sync.py` |
| `docs/index.html` `app.js` `style.css` `sw.js` | the phone screens, service worker, manifest | `tests/test_phone.py` |
| `tools/` | `setup_machine.py`, `make_shortcut.py`, `update.py` | `tests/test_setup_machine.py`, `tests/test_update.py` |

Node is not on PATH on the build machine; `tests/_node.py` finds Adobe's bundled Node 16 for the
JS tests and the suite skips them cleanly when none exists.

## Views

**PC** — Today (the Now panel, the hospital-style two-column day sheet, the log buttons),
Trends (14-day table and the hand-drawn 24-hour rhythm chart), Growth, Health, Reports, Settings,
and one editor dialog for every type of entry, with the entry's revision history at its foot.

**Phone** — Now, Day, Trends, Settings, with Sleep · Pump · Weight beside the diaper buttons and
health / note under More;
one-tap diapers with `Undo · Edit`; bottle feeds in two taps with the formula remembered and an
adjustable quick-amount range; Catch up for paper slips; a sync pill that shows its progress;
night mode; editor drafts that survive iOS killing the app; a status pill on every screen.

To deploy the phone app: put the client ID in `docs/config.js`, register the Pages URL as the
single-page-application redirect URI, and enable Pages on the `docs/` folder of `main`
([guide/SETUP.md](guide/SETUP.md) walks through it).

## Run

```
pip install -r requirements.txt
python tools/setup_machine.py        # writes config.yaml for this machine (or copy config.example.yaml)
python tests/test_store.py           # each test file runs standalone; discovery works too
python paper.py                      # once: the child and the first three days from the paper sheet
python launch.py                     # start it and open its own window
```

For the desktop version, build it once and make an icon for it:

```
build_exe.bat                        # -> "Baby Log.exe", no console window
python tools/make_shortcut.py        # Desktop / Start menu icon
```

The exe is gitignored. It reads `config.yaml` and `data/` from the folder it sits in, which is
why it builds here rather than into `dist/`.

**[guide/RUNNING.md](guide/RUNNING.md) is the plain-language guide to using both halves** —
start there. [guide/SPEC.md](guide/SPEC.md) is the build spec and
[guide/SETUP.md](guide/SETUP.md) the one-time Microsoft, GitHub, PC and phone setup.
`config.yaml` is gitignored (its paths contain a local username); `config.example.yaml` is the
template.
