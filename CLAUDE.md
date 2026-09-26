# Baby Log — project context

Read `guide/SPEC.md` before changing anything. It is the build spec (v2, after the adversarial
review) and it is current; where it pins a name, shape, route or rule, follow it exactly.
`guide/SETUP.md` is the owner's one-time setup (Entra, GitHub Pages, the PC, both phones) and
`guide/RUNNING.md` the plain-language guide to using it — keep both accurate when behaviour
changes, and quote real button and pill texts from the code, not the spec, when they differ.

This project is built on `E:\Claude Code\whiskey-tasting` (the Whiskey Tasting Book): same
shape, same working style, same file-naming and iOS rules. Read that project's `CLAUDE.md`,
`launch.py`, `store.py`, `docs/graph.js` and `docs/store.js` before touching the matching part
here. Nothing about the whiskey *collection workbook* carries over — there is no master
workbook, nothing is read-only, no surgical zip write.

## Where things are

The app modules, the `.bat` files and `config.yaml` stay at the root: the exe reads `config.yaml`
and `data/` from the folder it sits in. Everything else has a folder — `tests/`, `tools/`
(scripts run by hand), `guide/`, `static/` (the PC front end, bundled into the exe) and `docs/`
(the phone client — GitHub Pages serves only `/` or `/docs`, so that name is fixed).

`docs/core.js` is **shared**: the PC page loads it at `/core.js`, served straight from `docs/`
(and from `<sys._MEIPASS>/docs/core.js` in the exe, which is why `build_exe.bat` and
`tools/update.py` both pass `--add-data "%~dp0docs\core.js;docs"` as well as the `static` one).
`rollup.py` carries the Python port of the same arithmetic, function for function.

The journal is `OneDrive/Apps/Baby Log/` (`config.yaml: paths.app_folder`, env
`BABY_LOG_APP_FOLDER` overrides). The readable files go to `OneDrive/文档/Yisen File/`
(`paths.output_folder`, `BABY_LOG_OUTPUT_FOLDER`). Port **8766**; the whiskey app holds 8765 and
both may run at once.

## Non-negotiable

1. **Journal files are immutable.** A correction is a new revision file, a deletion is a
   tombstone revision, a restore is another revision. `write_event(revision=1)` on an id already
   on file raises `FileExistsError` — the paper import relies on that guard; leave it.
2. **One filename rule:** `<id>-r<n>-<w>.json`, parsed by exactly one regex in `store.NAME_RE`
   and `Core.parseName`, with a fresh 4-hex `<w>` on *every* write. Sub-second uniqueness is the
   bug the whiskey project hit three times, always silently. The day folder is the UTC date of
   the *write*, never the event's date.
3. **Both validators run against `tests/fixtures/data_cases.json`.** `store.validate_data` and
   `Core.validate` must accept and reject the same cases and report the same defaults. A new
   field or enum goes into the fixture first, then into both writers.
4. **Resolution is one rule** (SPEC §3.4): highest revision; then for feed/sleep/pump an `end`
   beats a null `end`; then `created_at`; then `device`; then `<w>`. Implemented in
   `store.resolve` and `Core.resolve`; nothing else decides a winner.
5. **Bump `VERSION` in `docs/sw.js` on any change to `docs/`**, or an installed phone serves the
   old shell for ever. `tests/test_sync.py` checks the shell list matches the folder.
6. **No personal data in the tree.** `config.yaml`, `data/` and every `.xlsx` are gitignored;
   fixtures are synthetic; the only real thing committed is the child's first name and birth
   date in `tools/paper_sheet.json`. The repo may be public for Pages, so commits use the
   repo-local noreply identity (`RollingShuttle`) — never a personal email.
7. **The phone never creates a child** and only reaches the app folder
   (`Files.ReadWrite.AppFolder`, the one scope — never widen it). The PC never calls Graph.
8. Every file read and write says `encoding="utf-8"`; paths and notes carry CJK. LF endings, no
   BOM. Plain browser globals in JS, no build step, and every JS file must also parse under
   Node 16 (no top-level await outside a function, no `??=`, no `.at()`).

## Working style

Save each step as it is finished and run its tests before starting the next. Every module has a
matching `tests/test_<module>.py` that runs standalone as well as under discovery; tests use
temp folders, never the real OneDrive folders, and `test_app.py` asserts nothing is written
outside its temp dir. Comments explain *why*, not what; short docstrings; standard library plus
the pinned requirements only.

```
pip install -r requirements.txt
python tests/test_store.py               # one module; python -m unittest discover -s tests for all
python paper.py --dry-run                # the import plan, writes nothing
python store.py                          # journal status, writes nothing
python launch.py                         # the app in its own window; python app.py for a console
```

Node is not on PATH; `tests/_node.py` finds Adobe's bundled Node 16 (`BABY_LOG_NODE` overrides)
and the JS tests skip with a message without it. The suite must never depend on Node.

## State as of 24 Sep 2026

**Built and committed, 473 tests passing** (`python -m unittest discover -s tests`): `store.py` (the journal, defensive
reader, index keyed by path/size/mtime), `docs/core.js` (shared logic; `test_core.py` runs the
whole fixture under Node), `app.py` (every §6.1 route, the debounced `Rollup` worker: startup,
20 s after an API write, and a 60 s scan for files the phones dropped through OneDrive),
`rollup.py` (`Baby Log.xlsx` with sheets Feeds · Diapers · Sleep · Pumping · Growth · Health ·
Notes · Daily · About, microsecond-stamped backups, refused while `~$Baby Log.xlsx` exists; the
one day-sheet renderer behind `/print/day/<date>` and `/api/daysheet/<date>`; `/print/range`),
`paper.py` (idempotent import of `tools/paper_sheet.json`: 18 feeds, 19 diapers, 8 `Check:`
notes; creates Yisen only when the journal has no child), `docs/{config,graph,store,sync,sw}.js`
+ `manifest.webmanifest`, and the PC screens `static/{index.html,style.css,app.js,print.css}`.

The PC front end is one page: Today (Now panel, the two-column day sheet, `‹ prev` / `next ›`,
log buttons **Feed · Wet · Dirty · Both · Sleep · Pump · Weight · More ▾**), Trends, Growth,
Health, Reports, Settings, and one editor dialog for every type. Things worth knowing that the
spec does not spell out: a feed typed in after the fact with no timer gets its `end` computed
from its breast seconds on Save (so `Core.isRunning` does not read it as running); a sleep saved
with no end keeps `timer: {running: true}`; the 2-minute same-diaper rule survives a reload via
`localStorage["bl.pc.last_diaper"]`; the editor's **History** shows `edited_by` per revision;
`knownLabels()` drops `paper` from the Who chips but keeps an entry's own label. Reports has no
"open the folder" button — it shows the paths instead.

Phone transport: `Graph.token()` never redirects (throws `SignedOutError`, sets
`meta.signed_out`); only `signIn()` and the pill/Settings tap may leave the page. 429/503 park
every Graph call until `backoff_until`. `Sync.pull` lists day folders from `last_sync_at − 1 day`
(cap 120, else a catch-up over `events/`), skips zero-byte listings, and marks its own uploads
seen. Pill texts live in `Sync.statusText`.

Also built: the phone screens `docs/{index.html,style.css,app.js}` + `tests/test_phone.py`
(which also runs the bundle under Node on a fake DOM and IndexedDB); `launch.py`, `run.bat`,
`update.bat`, `build_exe.bat`, `push.bat` + `tools/push.py` (the owner's no-command-line push:
bumps `docs/sw.js` when docs/ changed, runs the suite, commits under the noreply identity,
pushes), `tools/{setup_machine,make_shortcut,update}.py` and their tests
(ported from whiskey with the names changed: title `Baby Log`, exe `Baby Log.exe`, mutex
`Local\BabyLog.%d`, Edge profile `BabyLog\window`, tray `baby_log`, launcher console
`Baby Log launcher`, clone URL `https://github.com/RollingShuttle/baby-log.git` as a placeholder
until the repository exists).

**Running means a timer is going.** `Core.isRunning` and `rollup.is_running` require
`end === null` *and* `data.timer`; "no end" alone is a feed typed in after the fact or a paper
row, which is over. The first browser test of the PC app showed every imported feed as a
60-hour timer before this was tightened. Two other lessons from that session: every stylesheet
needs `[hidden] { display: none !important; }` above its `display: flex` classes (an empty
dialog overlay was swallowing every click), and `replaceChildren(null)` prints the word "null".

**Reviewed 24–26 Sep 2026.** An adversarial review (five finders, a skeptic each) produced 21
findings; every one is fixed and ticked in `guide/REVIEW.md`, which also keeps the refuted ones
with the skeptic's reason. Lessons that changed the code: the journal needs a lock under Flask's
threads; rounding is half-up everywhere (`rollup._round_half_up`, never `round()`); the rollup
scan keys on `Journal.fingerprint()`, not `created_at`; the phone looks back three day folders,
marks a folder done only after a clean pass, names a collision instead of hiding it, and renders
before MSAL loads; `run.bat` must not forward `%*`; and `tools/setup_machine.py` must never let
the school OneDrive (listed first, with its own 文档 folder) win — Yisen File decides.

**Done on the owner's PC (26 Sep 2026):** `config.yaml` written by `setup_machine.py`
(journal `C:/Users/mikey/OneDrive/Apps/Baby Log`, output `…/OneDrive/文档/Yisen File`), the paper
sheet imported for real (37 entries + Yisen; a second run skips 37), `Baby Log.exe` built and
launched once, Desktop and Start-menu shortcuts made, and `Baby Log.xlsx` written into Yisen File
by the startup rollup.

**Deployed 26 Sep 2026:** the repository is https://github.com/RollingShuttle/baby-log (public,
branch `main`), the Entra registration `Baby Log` exists and its client ID is in `docs/config.js`
(`test_sync.py` and `test_phone.py` now check it is a GUID), with
`https://rollingshuttle.github.io/baby-log/` as the SPA redirect URI. **Still the owner's:** turning
on GitHub Pages for `/docs` on `main` if not yet done, and the phones' first sign-in. Until then the PC app runs from `python launch.py` against whatever
`config.yaml` points at, and the phone app logs but cannot upload.


