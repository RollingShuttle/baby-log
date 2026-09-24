/* Baby Log — the phone's sync loop (SPEC.md §7.3, §7.6).

   Two phones and a PC share one OneDrive folder of immutable files, so "sync" is only ever two
   things: push the queue (flush) and list the day folders since the last pull (pull). The day
   folder is the UTC date of the upload, not of the event, which is what lets a phone catch every
   change by listing a handful of folders rather than the whole journal.

   Everything with a clock or a network in it lives behind small pure helpers — which folders to
   list, where an item goes, what a status means, how long to wait — kept on the Sync object so
   tests/test_sync.py can run them under Node without a browser. Node 14/16: no top-level await,
   every browser global behind a typeof check. */
"use strict";

const Sync = (() => {
  const C = typeof Core !== "undefined" ? Core : require("./core.js");
  // graph.js owns the failure rules (it is where they run); resolved lazily so script order and
  // the headless tests both work.
  const graph = () => (typeof Graph !== "undefined" ? Graph : require("./graph.js"));

  const DAY = 86400000;
  const CAP = 120;              // folders per pull before it is a catch-up instead
  const KEEP_DAYS = 120;        // how far back a catch-up looks — what the phone shows (§7.2)
  const FULL_EVERY_DAYS = 30;   // a catch-up this old is repeated
  const POLL_MS = 45000, JITTER_MS = 10000;
  const SEEN_BATCH = 25;        // names written back to bl.seen this often mid-folder
  const hasDoc = typeof document !== "undefined";
  const pad = (n) => String(n).padStart(2, "0");

  // -- pure helpers -------------------------------------------------------------------------------

  const utcDate = (d = new Date()) => d.toISOString().slice(0, 10);
  const dayMs = (ymd) => Date.parse(`${ymd}T00:00:00Z`);
  const isDay = (s) => /^\d{4}-\d{2}-\d{2}$/.test(String(s)) && !Number.isNaN(dayMs(s));
  const shift = (ymd, n) => new Date(dayMs(ymd) + n * DAY).toISOString().slice(0, 10);
  const daysBetween = (a, b) => Math.round((dayMs(b) - dayMs(a)) / DAY);

  /** The UTC day folders a normal pull lists: the day before the last pull through today. More
      than 120 of them (or no last pull at all) means a catch-up instead; the list is then the
      most recent 120. */
  function foldersToList(lastSyncIso, todayUtc = utcDate()) {
    const last = C.localDate(lastSyncIso);
    if (!isDay(last)) return { folders: [], catch_up: true };
    let start = shift(last, -1);
    if (start > todayUtc) start = todayUtc;     // a clock that ran ahead: never list the future
    const n = daysBetween(start, todayUtc) + 1;
    const folders = [];
    for (let i = Math.max(0, n - CAP); i < n; i++) folders.push(shift(start, i));
    return { folders, catch_up: n > CAP };
  }

  /** Where a queue item uploads. Assigned on the first attempt and kept for retries — unless the
      folder is older than UTC yesterday, when it is re-assigned to today with a fresh w so the
      other devices find it by listing recent folders (a stale duplicate is harmless: same bytes,
      same resolution). Children have no day folder. */
  function pathFor(item, todayUtc = utcDate()) {
    const body = item.body || {};
    if (item.kind === "child") return item.path || `children/${C.fileName(body.child_id, body.revision)}`;
    const fresh = () => `events/${todayUtc}/${C.fileName(body.event_id, body.revision)}`;
    if (!item.path) return fresh();
    const folder = item.path.split("/")[1];
    return folder === todayUtc || folder === shift(todayUtc, -1) ? item.path : fresh();
  }

  const classify = (status, body) => graph().classify(status, body);
  const backoffMs = (retryAfter, attempt) => graph().backoffMs(retryAfter, attempt);

  /** A revise or tombstone must pull first when the last pull is older than 24 h (§7.3). */
  function stalePull(meta, now = Date.now()) {
    const at = Date.parse((meta && meta.last_sync_at) || "");
    return Number.isNaN(at) || now - at > DAY;
  }

  const clock = (iso) => {
    const d = new Date(iso);
    return Number.isNaN(d.getTime()) ? "?" : `${pad(d.getHours())}:${pad(d.getMinutes())}`;
  };
  function ago(ms) {
    const m = Math.floor(Math.max(0, ms) / 60000);
    if (m < 1) return "just now";
    if (m < 60) return `${m} min ago`;
    const h = Math.floor(m / 60);
    if (h < 24) return `${h} h ago`;
    return `${Math.floor(h / 24)} d ago`;
  }
  const errorNewer = (s) => !!(s.last_error && s.last_error.at && (!s.last_sync_at || s.last_error.at > s.last_sync_at));

  /** The pill's words for a state (§7.3, §7.6). Signed out never reads as an error: logging
      works, entries queue, and the pill says so. */
  function statusText(s = state()) {
    if (s.syncing) return "Syncing…";
    if (!s.online) return s.waiting ? `Offline · ${s.waiting} waiting` : "Offline";
    if (!s.signed_in) {
      if (s.waiting) return `Signed out · ${s.waiting} waiting · tap to sign in`;
      return s.last_sync_at ? `Signed out · showing data from ${clock(s.last_sync_at)}` : "Signed out · tap to sign in";
    }
    if (s.failed) return `${s.failed} stuck · tap`;
    if (errorNewer(s)) return `Sync failed · ${clock(s.last_error.at)} · tap for details`;
    if (s.last_sync_at) return `Synced ${ago((s.now || Date.now()) - Date.parse(s.last_sync_at))}`;
    return "Not synced yet";
  }
  /** {text, tone}: tone is busy / amber (something queued over 24 h) / error / warn / ok. */
  function status(s = state()) {
    let tone = "ok";
    if (s.syncing) tone = "busy";
    else if (s.stale) tone = "amber";
    else if (s.failed || (s.signed_in && s.online && errorNewer(s))) tone = "error";
    else if (!s.signed_in || !s.online) tone = "warn";
    return { text: statusText(s), tone };
  }

  // -- the live state -----------------------------------------------------------------------------

  let inflight = null;
  let again = false;       // a trigger arrived mid-run: go once more when it finishes
  let timer = null;
  let started = false;
  let syncing = false;
  const listeners = [];

  const online = () => typeof navigator === "undefined" || navigator.onLine !== false;
  const visible = () => !hasDoc || document.visibilityState !== "hidden";
  const signedIn = () => typeof Graph !== "undefined" && Graph.isSignedIn();
  const inBackoff = () => typeof Graph !== "undefined" && Graph.backoffUntil() > 0;

  function state(now = Date.now()) {
    const m = Store.meta();
    const q = Store.queue();
    let oldest = null;
    for (const i of q) {
      const t = Date.parse(i.created_at || "");
      if (!Number.isNaN(t) && (oldest === null || t < oldest)) oldest = t;
    }
    return {
      syncing, online: online(), signed_in: signedIn(),
      waiting: q.length, failed: Store.failed().length,
      last_sync_at: m.last_sync_at, last_error: m.last_error,
      stale: oldest !== null && now - oldest > DAY,
      now,
    };
  }

  function onChange(fn) { listeners.push(fn); return () => { const i = listeners.indexOf(fn); if (i >= 0) listeners.splice(i, 1); }; }
  function emit(kind, detail) {
    for (const fn of listeners.slice()) {
      try { fn(kind, detail || {}); } catch (e) { console.error(e); }
    }
  }
  const errorInfo = (e) => ({
    at: C.nowIso(),
    status: e && e.status != null ? e.status : null,
    code: (e && e.code) || (e && e.name) || null,
    message: (e && e.message) || String(e),
  });
  const kindOf = (e) => (e && e.kind) || (e && e.name === "SignedOutError" ? "signed_out" : "retryable");

  // -- flush ----------------------------------------------------------------------------------------

  /** Upload the queue in created_at order. A retryable failure stops the walk and keeps the
      rest for later; a permanent one parks the item under bl.failed and carries on; 401/403
      stop it and mark signed out. */
  async function flush() {
    if (!signedIn()) return { skipped: "signed_out" };
    if (inBackoff()) return { skipped: "backoff" };
    const out = { sent: 0, failed: 0, stopped: null };
    for (const item of Store.queue()) {
      const path = pathFor(item, utcDate());
      if (path !== item.path) {
        // Written back before the PUT so a retry sends the same bytes to the same place. If even
        // that write fails the upload still goes; the worst case is a harmless duplicate later.
        try { await Store.setQueuePath(item.qid, path); } catch { /* see above */ }
      }
      try {
        await Graph.putJSON(path, item.body);
        await Store.drop(item.qid);
        // Our own file need not come back down: mark it seen in its folder.
        const parts = path.split("/");
        if (parts[0] === "events") Store.markSeen(parts[1], [parts[2]]);
        out.sent += 1;
      } catch (e) {
        const kind = kindOf(e);
        if (kind === "permanent") {
          await Store.fail(item, e);
          out.failed += 1;
          continue;
        }
        if (kind === "retryable") Store.setMeta({ last_error: errorInfo(e) });
        out.stopped = kind;
        out.error = errorInfo(e);
        break;
      }
    }
    return out;
  }

  // -- pull -----------------------------------------------------------------------------------------

  /** Is this listed file worth downloading? Not when the held record already is (or outranks)
      it — but an equal revision under a different w is a concurrent write and may win. */
  function wanted(parsed, name) {
    const held = parsed.id.startsWith("C-") ? Store.child(parsed.id) : Store.event(parsed.id);
    if (!held) return true;
    if (parsed.rev > held.revision) return true;
    return parsed.rev === held.revision && held._file !== name;
  }

  async function pullFolder(day, counts) {
    const files = await Graph.listFolder(`events/${day}`);
    const seen = new Set(Store.seen(day));
    let batch = [];
    const flushSeen = () => { if (batch.length) { Store.markSeen(day, batch); batch = []; } };
    for (const f of files) {
      if (f.isFolder || seen.has(f.name)) continue;
      const parsed = C.parseName(f.name);
      if (!parsed) continue;                    // OneDrive's temp files and the like
      if (f.size === 0) continue;               // still uploading; leave it for the next pull
      if (wanted(parsed, f.name)) {
        const text = await Graph.getText(f.downloadUrl, `events/${day}/${f.name}`);
        let rec = null;
        try { rec = text === null ? null : JSON.parse(text); } catch { rec = null; }
        counts.downloaded += 1;
        if (rec && await Store.applyRemote(rec, f.name)) {
          counts.applied += 1;
          counts.changed.push(parsed.id);
        } else if (!rec) {
          counts.bad += 1;
        }
      }
      batch.push(f.name);
      if (batch.length >= SEEN_BATCH) flushSeen();
    }
    flushSeen();
  }

  async function pullChildren(counts) {
    for (const f of await Graph.listFolder("children")) {
      if (f.isFolder) continue;
      const parsed = C.parseName(f.name);
      if (!parsed || f.size === 0 || !wanted(parsed, f.name)) continue;
      const text = await Graph.getText(f.downloadUrl, `children/${f.name}`);
      let rec = null;
      try { rec = text === null ? null : JSON.parse(text); } catch { rec = null; }
      counts.downloaded += 1;
      if (rec && await Store.applyRemote(rec, f.name)) {
        counts.applied += 1;
        counts.changed.push(parsed.id);
      } else if (!rec) {
        counts.bad += 1;
      }
    }
  }

  /** First sign-in, or a month since the last full pass: every day folder within 120 days that
      is not yet fully caught up. Days older than yesterday are marked done once listed clean,
      so an interrupted catch-up resumes where it stopped. */
  async function catchUp(today, counts) {
    const done = new Set(Store.done());
    const yesterday = shift(today, -1);
    const folders = (await Graph.listFolder("events"))
      .filter((f) => f.isFolder && isDay(f.name))
      .map((f) => f.name)
      .filter((d) => daysBetween(d, today) <= KEEP_DAYS && !done.has(d))
      .sort();
    for (const day of folders) {
      await pullFolder(day, counts);
      if (day < yesterday) Store.markDone(day);
    }
    counts.folders += folders.length;
  }

  /** List the folders since the last pull (or catch up), apply what is new, then children/.
      last_sync_at moves only after a pull that finished with no error. */
  async function pull() {
    if (!signedIn()) return { skipped: "signed_out" };
    if (inBackoff()) return { skipped: "backoff" };
    const counts = { folders: 0, downloaded: 0, applied: 0, bad: 0, changed: [], catch_up: false };
    const m = Store.meta();
    const today = utcDate();
    const plan = foldersToList(m.last_sync_at, today);
    const fullAt = Date.parse(m.full_sync_at || "");
    counts.catch_up = plan.catch_up || Number.isNaN(fullAt) || Date.now() - fullAt > FULL_EVERY_DAYS * DAY;
    try {
      if (counts.catch_up) {
        await catchUp(today, counts);
      } else {
        for (const day of plan.folders) await pullFolder(day, counts);
        counts.folders += plan.folders.length;
      }
      await pullChildren(counts);
    } catch (e) {
      const kind = kindOf(e);
      if (kind !== "signed_out") Store.setMeta({ last_error: errorInfo(e) });
      counts.stopped = kind;
      counts.error = errorInfo(e);
      if (counts.changed.length) emit("applied", { ids: counts.changed });
      return counts;
    }
    const patch = { last_sync_at: C.nowIso(), last_error: null };
    if (counts.catch_up) patch.full_sync_at = patch.last_sync_at;
    Store.setMeta(patch);
    if (counts.changed.length) emit("applied", { ids: counts.changed });
    return counts;
  }

  // -- the schedule -------------------------------------------------------------------------------

  /** Flush, then pull. Overlapping triggers coalesce into the run in flight plus one more. */
  function run() {
    if (inflight) { again = true; return inflight; }
    inflight = (async () => {
      let result = { flush: null, pull: null };
      do {
        again = false;
        if (!online() || !signedIn()) {
          result = { flush: { skipped: online() ? "signed_out" : "offline" }, pull: { skipped: online() ? "signed_out" : "offline" } };
          break;
        }
        syncing = true;
        emit("status");
        try {
          result.flush = await flush();
          result.pull = await pull();
        } catch (e) {
          // Only a bug reaches here: flush and pull report their own failures.
          console.error(e);
          Store.setMeta({ last_error: errorInfo(e) });
        } finally {
          syncing = false;
        }
      } while (again);
      return result;
    })().finally(() => { inflight = null; emit("status", {}); });
    return inflight;
  }

  function schedule() {
    if (timer) { clearTimeout(timer); timer = null; }
    if (!started || !visible()) return;
    timer = setTimeout(tick, POLL_MS - JITTER_MS + Math.random() * 2 * JITTER_MS);
  }
  async function tick() {
    timer = null;
    // Never while hidden, never during a backoff — but keep the clock ticking so it resumes.
    if (visible() && !inBackoff()) await run();
    schedule();
  }

  /** Wire the triggers and run once. Called after Graph.resume() has settled the redirect. */
  function start() {
    if (started) return;
    started = true;
    if (hasDoc) {
      document.addEventListener("visibilitychange", () => {
        if (visible()) { run(); schedule(); } else if (timer) { clearTimeout(timer); timer = null; }
      });
    }
    if (typeof window !== "undefined") window.addEventListener("online", () => { run(); emit("status"); });
    if (typeof window !== "undefined") window.addEventListener("offline", () => emit("status"));
    run();
    schedule();
  }
  function stop() {
    started = false;
    if (timer) { clearTimeout(timer); timer = null; }
  }

  return {
    foldersToList, pathFor, classify, backoffMs, stalePull, statusText, status,
    flush, pull, run, afterWrite: run, start, stop, state, onChange,
    isSyncing: () => syncing,
  };
})();

if (typeof module !== "undefined") module.exports = Sync;
