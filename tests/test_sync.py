"""
test_sync.py — docs/sync.js's pure helpers under Node, plus the shell files it ships with.

    python tests/test_sync.py

One Node script loads core.js and sync.js (which pulls graph.js in for the failure rules) with no
browser at all, exercises the folder plan, the upload path rule, the failure classes, the backoff
and the pill text, and prints a JSON list of {name, ok, detail}. Python asserts every ok. Without
a Node binary that half skips with a message; the static checks on sw.js, the manifest and
config.js run regardless.
"""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path[:0] = [str(HERE), str(ROOT)]

import json
import re
import unittest

import _node

DOCS = ROOT / "docs"

# Exactly what docs/ holds once every phone file exists (SPEC.md §2); sw.js must promise all of
# it and nothing else, itself excepted.
SHELL = {"index.html", "style.css", "config.js", "core.js", "graph.js", "store.js", "sync.js",
         "app.js", "manifest.webmanifest", "icon-180.png"}


def text(name):
    return (DOCS / name).read_text(encoding="utf-8")


def code(name):
    """A file with its comments stripped: the rules below are about what the code does."""
    src = re.sub(r"/\*.*?\*/", " ", text(name), flags=re.DOTALL)
    return re.sub(r"^\s*//.*$", " ", src, flags=re.MULTILINE)


class TestShell(unittest.TestCase):
    def test_the_service_worker_lists_the_shell_and_nothing_else(self):
        listed = re.findall(r'"\./([^"]*)"', text("sw.js"))
        self.assertIn("", listed, "sw.js must cache ./ — the start_url")
        names = {n for n in listed if n}
        self.assertEqual(names, SHELL)
        self.assertNotIn("sw.js", names, "a worker must not cache itself")
        self.assertEqual(len(listed), len(set(listed)), "a name is listed twice")

    def test_every_file_present_in_docs_is_cached(self):
        """Names, not existence: test_phone.py checks the files exist once every agent is done."""
        present = {p.name for p in DOCS.iterdir() if p.is_file() and p.name != "sw.js"}
        self.assertTrue(present <= SHELL, f"docs/ holds files sw.js does not cache: {present - SHELL}")

    def test_the_worker_has_a_version_to_bump(self):
        self.assertRegex(text("sw.js"), r'const VERSION = "v\d+";')
        self.assertIn('if (e.request.method !== "GET") return;', text("sw.js"))
        self.assertIn("url.origin !== self.location.origin", text("sw.js"))

    def test_the_manifest_is_valid_and_points_at_the_icon(self):
        m = json.loads(text("manifest.webmanifest"))
        self.assertEqual(m["name"], "Baby Log")
        self.assertEqual(m["short_name"], "Baby Log")
        self.assertEqual(m["start_url"], ".")
        self.assertEqual(m["scope"], ".")
        self.assertEqual(m["display"], "standalone")
        self.assertEqual(m["orientation"], "portrait")
        self.assertEqual(m["theme_color"], "#F2F5F4")
        self.assertEqual(m["background_color"], "#F2F5F4")
        self.assertEqual([i["src"] for i in m["icons"]], ["icon-180.png"])
        self.assertEqual(m["icons"][0]["sizes"], "180x180")


class TestConfig(unittest.TestCase):
    def test_the_client_id_is_blank_in_the_committed_file(self):
        """Blank until the Entra registration exists (SPEC.md §12); relax to whiskey's
        blank-or-GUID form when it is filled in."""
        m = re.search(r'CLIENT_ID:\s*"([^"]*)"', text("config.js"))
        self.assertIsNotNone(m, "config.js lost its CLIENT_ID line")
        self.assertEqual(m.group(1).strip(), "")

    def test_the_rest_of_the_configuration(self):
        cfg = code("config.js")
        self.assertIn('AUTHORITY: "https://login.microsoftonline.com/consumers"', cfg)
        self.assertIn('SCOPES: ["Files.ReadWrite.AppFolder"]', cfg)
        self.assertIn('MSAL_SRC: "https://cdn.jsdelivr.net/npm/@azure/msal-browser@4/lib/msal-browser.min.js"', cfg)
        self.assertIn('GRAPH: "https://graph.microsoft.com/v1.0"', cfg)
        self.assertIn('APP: "Baby Log"', cfg)
        for wider in ("Files.ReadWrite.All", "Files.Read.All", "Sites.", "User.ReadWrite"):
            self.assertNotIn(wider, cfg, f"{wider} would reach beyond the app folder")
        for bad in ("client_secret", "clientSecret", "CLIENT_SECRET", "password"):
            self.assertNotIn(bad, text("config.js"))


class TestSource(unittest.TestCase):
    """What can be checked about the transport and the store without a browser."""

    def test_uploads_go_only_to_the_app_folder_root(self):
        self.assertIn("/me/drive/special/approot:", text("graph.js"))

    def test_the_listing_selects_what_pull_needs(self):
        self.assertIn("$select=id,name,size,eTag,file,folder,@microsoft.graph.downloadUrl&$top=500", text("graph.js"))
        self.assertIn("@odata.nextLink", text("graph.js"))

    def test_the_download_url_is_fetched_bare(self):
        src = code("graph.js")
        body = src[src.index("async function getText"):src.index("async function listFolder")]
        self.assertIn("fetch(downloadUrl)", body)
        self.assertNotIn("Authorization", body)

    def test_background_token_calls_never_redirect(self):
        src = code("graph.js")
        body = src[src.index("async function token"):src.index("function classify")]
        self.assertIn("opts.interactive", body)
        self.assertIn("SignedOutError", body)
        self.assertLess(body.index("opts.interactive"), body.index("acquireTokenRedirect"))

    def test_msal_is_configured_as_whiskey_does(self):
        src = text("graph.js")
        self.assertIn('redirectUri: location.href.split("#")[0].split("?")[0],', src)
        self.assertIn('cache: { cacheLocation: "localStorage" }', src)
        self.assertIn("handleRedirectPromise()", src)
        self.assertIn("loginRedirect(", src)

    def test_a_missing_day_folder_is_created_once(self):
        src = code("graph.js")
        self.assertIn('"@microsoft.graph.conflictBehavior": "fail"', src)
        self.assertIn("e.status !== 409", src)

    def test_storage_access_is_guarded(self):
        """Private browsing and a full quota both throw; a lost draft must not take the app down."""
        self.assertGreaterEqual(text("store.js").count("catch"), 2)
        for key in ("bl.settings", "bl.meta", "bl.seen", "bl.done", "bl.draft", "bl.failed"):
            self.assertIn(f'"{key}"', text("store.js"))
        self.assertIn('"baby-log"', text("store.js"))
        self.assertIn("navigator.storage.persist()", text("store.js"))

    def test_the_record_is_saved_before_the_ui_hears_saved(self):
        src = code("store.js")
        body = src[src.index("async function save("):src.index("function askPersist")]
        self.assertIn("await commit(ops)", body)
        self.assertIn("revert()", body)
        self.assertIn("StorageError", body)

    def test_sync_exports_for_node(self):
        src = text("sync.js").rstrip()
        self.assertTrue(src.endswith('if (typeof module !== "undefined") module.exports = Sync;'))
        self.assertIn("const Sync = (() => {", src)
        for bad in ("??=", ".at(", "structuredClone"):
            self.assertNotIn(bad, code("sync.js"))

    def test_the_schedule_never_runs_hidden_or_during_backoff(self):
        src = code("sync.js")
        self.assertIn("visibilitychange", src)
        self.assertIn('addEventListener("online"', src)
        self.assertIn("POLL_MS = 45000, JITTER_MS = 10000", src)
        body = src[src.index("async function tick"):src.index("function start")]
        self.assertIn("visible() && !inBackoff()", body)


SCRIPT = r"""
process.env.TZ = "America/Chicago";
global.Core = require(%(core)s);
const Sync = require(%(sync)s);
const out = [];
const canon = (x) => JSON.stringify(sortKeys(x));
function sortKeys(x) {
  if (Array.isArray(x)) return x.map(sortKeys);
  if (x && typeof x === "object") {
    const o = {};
    for (const k of Object.keys(x).sort()) o[k] = sortKeys(x[k]);
    return o;
  }
  return x;
}
function t(name, fn) {
  try {
    const r = fn();
    if (r === true) out.push({ name, ok: true, detail: "" });
    else out.push({ name, ok: false, detail: String(r) });
  } catch (e) { out.push({ name, ok: false, detail: "threw " + (e && e.stack || e) }); }
}
const eq = (got, want) => canon(got) === canon(want) ? true : "got " + canon(got) + " want " + canon(want);

const DAY = 86400000;
const TODAY = "2026-09-24";
const day = (n) => new Date(Date.parse(TODAY + "T00:00:00Z") + n * DAY).toISOString().slice(0, 10);
const at = (n, hhmm) => `${day(n)}T${hhmm}:00.000000+00:00`;

// -- foldersToList -------------------------------------------------------------------------------
t("a pull two days after the last lists four folders", () =>
  eq(Sync.foldersToList(at(-2, "10:15"), TODAY), { folders: [day(-3), day(-2), day(-1), TODAY], catch_up: false }));
t("the day before the last pull is always included", () =>
  eq(Sync.foldersToList(at(0, "00:00"), TODAY), { folders: [day(-1), TODAY], catch_up: false }));
t("three days back means five folders", () => eq(Sync.foldersToList(at(-3, "23:59"), TODAY).folders.length, 5));
t("no last pull is a catch-up", () => eq(Sync.foldersToList(null, TODAY), { folders: [], catch_up: true }));
t("garbage is a catch-up", () => eq(Sync.foldersToList("never", TODAY).catch_up, true));
t("more than 120 folders is capped and a catch-up", () => {
  const r = Sync.foldersToList(at(-400, "12:00"), TODAY);
  if (!r.catch_up) return "not flagged";
  if (r.folders.length !== 120) return "listed " + r.folders.length;
  return r.folders[r.folders.length - 1] === TODAY ? true : "does not end today";
});
t("exactly 120 folders is still a normal pull", () => {
  const r = Sync.foldersToList(at(-118, "12:00"), TODAY);
  return r.folders.length === 120 && !r.catch_up ? true : canon(r);
});
t("a clock that ran ahead never lists the future", () =>
  eq(Sync.foldersToList(at(+3, "12:00"), TODAY), { folders: [TODAY], catch_up: false }));

// -- pathFor -------------------------------------------------------------------------------------
const body = { event_id: "E-20260921-120000-a1b2", revision: 2 };
t("a new item gets today's folder and a journal name", () => {
  const p = Sync.pathFor({ kind: "event", path: null, body }, TODAY);
  const parts = p.split("/");
  const parsed = Core.parseName(parts[2]);
  if (parts[0] !== "events" || parts[1] !== TODAY) return p;
  return parsed && parsed.id === body.event_id && parsed.rev === 2 ? true : p;
});
t("a path in today's folder is kept", () => {
  const path = `events/${TODAY}/E-20260921-120000-a1b2-r2-0e9f.json`;
  return eq(Sync.pathFor({ kind: "event", path, body }, TODAY), path);
});
t("a path in yesterday's folder is kept", () => {
  const path = `events/${day(-1)}/E-20260921-120000-a1b2-r2-0e9f.json`;
  return eq(Sync.pathFor({ kind: "event", path, body }, TODAY), path);
});
t("a path older than yesterday is re-assigned with a fresh w, same id and rev", () => {
  const path = `events/${day(-2)}/E-20260921-120000-a1b2-r2-0e9f.json`;
  const p = Sync.pathFor({ kind: "event", path, body }, TODAY);
  const parts = p.split("/");
  const parsed = Core.parseName(parts[2]);
  if (parts[1] !== TODAY) return p;
  if (!parsed || parsed.id !== body.event_id || parsed.rev !== 2) return p;
  return parsed.w !== "0e9f" ? true : "w was not refreshed";
});
t("a child item has no day folder", () => {
  const p = Sync.pathFor({ kind: "child", path: null, body: { child_id: "C-20260923-220000-0a1b", revision: 3 } }, TODAY);
  const parsed = Core.parseName(p.split("/")[1]);
  return p.startsWith("children/") && parsed && parsed.id === "C-20260923-220000-0a1b" && parsed.rev === 3 ? true : p;
});
t("a child item keeps its path", () =>
  eq(Sync.pathFor({ kind: "child", path: "children/C-x-r3-aaaa.json", body: {} }, TODAY), "children/C-x-r3-aaaa.json"));

// -- classify ------------------------------------------------------------------------------------
for (const s of [429, 503, 500, 502, 504, 408, 0]) t("classify " + s + " retryable", () => eq(Sync.classify(s, null), "retryable"));
for (const s of [401, 403]) t("classify " + s + " signed_out", () => eq(Sync.classify(s, { error: { code: "InvalidAuthenticationToken" } }), "signed_out"));
for (const s of [400, 404, 413, 409, 422]) t("classify " + s + " permanent", () => eq(Sync.classify(s, null), "permanent"));

// -- backoffMs -----------------------------------------------------------------------------------
t("Retry-After seconds are honoured", () => eq([Sync.backoffMs("30", 0), Sync.backoffMs(45, 3), Sync.backoffMs("7", 9)], [30000, 45000, 7000]));
t("Retry-After as an HTTP date is honoured", () => {
  const ms = Sync.backoffMs(new Date(Date.now() + 90000).toUTCString(), 0);
  return ms > 80000 && ms <= 91000 ? true : "got " + ms;
});
t("without the header: 10 s doubling", () =>
  eq([0, 1, 2, 3, 4].map((a) => Sync.backoffMs(null, a)), [10000, 20000, 40000, 80000, 160000]));
t("capped at 300 s", () => eq([Sync.backoffMs(null, 5), Sync.backoffMs(null, 12), Sync.backoffMs("", 20)], [300000, 300000, 300000]));
t("a missing attempt counts as the first", () => eq(Sync.backoffMs(undefined, undefined), 10000));

// -- stalePull -----------------------------------------------------------------------------------
const NOW = Date.parse("2026-09-24T12:00:00Z");
t("stalePull after 24 h or never", () => eq([
  Sync.stalePull({ last_sync_at: "2026-09-24T11:00:00.000000+00:00" }, NOW),
  Sync.stalePull({ last_sync_at: "2026-09-23T11:00:00.000000+00:00" }, NOW),
  Sync.stalePull({ last_sync_at: null }, NOW),
  Sync.stalePull({}, NOW),
], [false, true, true, true]));

// -- statusText ----------------------------------------------------------------------------------
const base = { syncing: false, online: true, signed_in: true, waiting: 0, failed: 0,
               last_sync_at: null, last_error: null, stale: false, now: NOW };
const S = (patch) => ({ ...base, ...patch });
const synced = "2026-09-24T11:59:00.000000+00:00";      // 1 min before NOW
t("Syncing…", () => eq(Sync.statusText(S({ syncing: true, waiting: 3 })), "Syncing…"));
t("Synced 1 min ago", () => eq(Sync.statusText(S({ last_sync_at: synced })), "Synced 1 min ago"));
t("Synced just now", () => eq(Sync.statusText(S({ last_sync_at: "2026-09-24T11:59:40.000000+00:00" })), "Synced just now"));
t("Synced hours ago", () => eq(Sync.statusText(S({ last_sync_at: "2026-09-24T09:30:00.000000+00:00" })), "Synced 2 h ago"));
t("Offline · 2 waiting", () => eq(Sync.statusText(S({ online: false, waiting: 2 })), "Offline · 2 waiting"));
t("Offline with nothing waiting", () => eq(Sync.statusText(S({ online: false })), "Offline"));
t("Signed out · 3 waiting · tap to sign in", () => eq(Sync.statusText(S({ signed_in: false, waiting: 3 })), "Signed out · 3 waiting · tap to sign in"));
t("Signed out · showing data from 14:02", () => eq(Sync.statusText(S({ signed_in: false, last_sync_at: "2026-09-24T19:02:00.000000+00:00" })), "Signed out · showing data from 14:02"));
t("Signed out before any sync", () => eq(Sync.statusText(S({ signed_in: false })), "Signed out · tap to sign in"));
t("Sync failed · 19:03 · tap for details", () => eq(Sync.statusText(S({ last_sync_at: synced,
  last_error: { at: "2026-09-25T00:03:10.000000+00:00", status: 500, code: "generalException", message: "x" } })),
  "Sync failed · 19:03 · tap for details"));
t("an error older than the last sync is not shown", () => eq(Sync.statusText(S({ last_sync_at: synced,
  last_error: { at: "2026-09-24T10:00:00.000000+00:00", message: "old" } })), "Synced 1 min ago"));
t("1 stuck · tap", () => eq(Sync.statusText(S({ failed: 1, last_sync_at: synced })), "1 stuck · tap"));
t("Not synced yet", () => eq(Sync.statusText(S({})), "Not synced yet"));
t("signed out is never an error, offline wins over signed out", () => eq(Sync.statusText(S({ online: false, signed_in: false, waiting: 1 })), "Offline · 1 waiting"));
t("the tone goes amber for an item queued over 24 h", () => eq([
  Sync.status(S({ stale: true, waiting: 1, last_sync_at: synced })).tone,
  Sync.status(S({ syncing: true })).tone,
  Sync.status(S({ failed: 2 })).tone,
  Sync.status(S({ signed_in: false })).tone,
  Sync.status(S({ last_sync_at: synced })).tone,
], ["amber", "busy", "error", "warn", "ok"]));

console.log(JSON.stringify(out));
"""


class TestUnderNode(unittest.TestCase):
    def test_sync_helpers_pass_every_case(self):
        if not _node.NODE:
            self.skipTest("no Node binary found (set BABY_LOG_NODE or install node); "
                          "sync.js was not executed")
        script = SCRIPT % {"core": json.dumps(str(DOCS / "core.js")),
                           "sync": json.dumps(str(DOCS / "sync.js"))}
        rc, out, err = _node.run_js(script)
        self.assertEqual(rc, 0, f"node exited {rc}\n{err}\n{out}")
        lines = [ln for ln in out.splitlines() if ln.strip()]
        results = json.loads(lines[-1])
        self.assertGreater(len(results), 40, "the script ran too few cases")
        failed = [r for r in results if not r["ok"]]
        report = "\n".join(f"  {r['name']}: {r['detail']}" for r in failed)
        self.assertEqual(failed, [], f"{len(failed)} of {len(results)} cases failed:\n{report}")
        print(f"\n  {len(results)} JS cases passed under {_node.NODE}", file=sys.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
