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
  // A normal pull re-lists this many days before the last pull: the day folder is the UTC date
  // of the write, but the PC's OneDrive client uploads when it can (paused, metered, asleep), so
  // a file can land in a folder a day or two after the last pull walked past it.
  const LOOKBACK_DAYS = 3;
  const STALE_MS = 5 * 60000;   // a revise pulls first when the last pull is older than this
  const POLL_MS = 45000, JITTER_MS = 10000;
  const SEEN_BATCH = 25;        // names written back to bl.seen this often mid-folder
  const CONFLICTS_KEEP = 20;    // collisions remembered for Settings, newest first
  const hasDoc = typeof document !== "undefined";
  const pad = (n) => String(n).padStart(2, "0");

  // -- pure helpers -------------------------------------------------------------------------------

  const utcDate = (d = new Date()) => d.toISOString().slice(0, 10);
  const dayMs = (ymd) => Date.parse(`${ymd}T00:00:00Z`);
  const isDay = (s) => /^\d{4}-\d{2}-\d{2}$/.test(String(s)) && !Number.isNaN(dayMs(s));
  const shift = (ymd, n) => new Date(dayMs(ymd) + n * DAY).toISOString().slice(0, 10);
  const daysBetween = (a, b) => Math.round((dayMs(b) - dayMs(a)) / DAY);

  /** The UTC day folders a normal pull lists: three days before the last pull through today.
      More than 120 of them (or no last pull at all) means a catch-up instead; the list is then
      the most recent 120. */
  function foldersToList(lastSyncIso, todayUtc = utcDate()) {
    const last = C.localDate(lastSyncIso);
    if (!isDay(last)) return { folders: [], catch_up: true };
    let start = shift(last, -LOOKBACK_DAYS);
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

  /** A revise or tombstone must pull first when the last pull is older than a few poll
      intervals. §7.3 said 24 h; that let a phone build a revision on a base the PC had already
      deleted or stopped hours earlier, and §3.4 then settled the collision silently. */
  function stalePull(meta, now = Date.now()) {
    const at = Date.parse((meta && meta.last_sync_at) || "");
    return Number.isNaN(at) || now - at > STALE_MS;
  }

  /** A downloaded record at the same revision as the held one, from another device, for an
      entry this phone has queued or uploaded: both sides revised the same base, and §3.4 picks
      one on every device alike — so the collision is real and somebody should look at it. */
  function isConflict(held, rec, queued) {
    if (!held || !rec || rec.revision !== held.revision) return false;
    if (!rec.device || rec.device === held.device) return false;
    const id = rec.event_id != null ? rec.event_id : rec.child_id;
    return !!(queued && queued.has(id));
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
      works, entries queue, and the pill says so. While a run is on, the phase and its count
      (so a tap on the pill visibly does something); for six seconds after, what it did. */
  function statusText(s = state()) {
    if (s.syncing) {
      const p = s.progress;
      if (p && p.phase === "sending") return `Syncing… sending ${p.done} of ${p.total}`;
      if (p && p.phase === "listing") return `Syncing… checking ${p.total} ${p.total === 1 ? "day" : "days"}`;
      if (p && p.phase === "reading") return `Syncing… reading ${p.total} new`;
      return "Syncing…";
    }
    if (!s.online) return s.waiting ? `Offline · ${s.waiting} waiting` : "Offline";
    if (!s.signed_in) {
      if (s.waiting) return `Signed out · ${s.waiting} waiting · tap to sign in`;
      return s.last_sync_at ? `Signed out · showing data from ${clock(s.last_sync_at)}` : "Signed out · tap to sign in";
    }
    if (s.failed) return `${s.failed} stuck · tap`;
    if (errorNewer(s)) return `Sync failed · ${clock(s.last_error.at)} · tap for details`;
    if (s.last_result) {
      const parts = [];
      if (s.last_result.sent) parts.push(`${s.last_result.sent} sent`);
      if (s.last_result.received) parts.push(`${s.last_result.received} new`);
      return `Synced · ${parts.length ? parts.join(" · ") : "nothing new"}`;
    }
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
  // What the run in flight is doing ({phase, done, total, sent, received}), and what the last
  // clean run did ({sent, received, at}) — shown on the pill for RESULT_MS after it (§7.3).
  let progress = null;
  let lastResult = null;
  let runSent = 0;         // the flush's count, so the pull's progress events can carry it
  const RESULT_MS = 6000;
  const listeners = [];
  // Ids this phone uploaded this session. A queued item leaves the queue the moment its PUT
  // lands, so this is how a later pull still knows "we wrote revision n of that too" when the
  // other device's copy turns up — even a run or two later, as the PC's file may land late.
  const uploaded = new Set();

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
    const recent = lastResult && now - lastResult.at < RESULT_MS;
    return {
      syncing, online: online(), signed_in: signedIn(),
      waiting: q.length, failed: Store.failed().length,
      last_sync_at: m.last_sync_at, last_error: m.last_error,
      stale: oldest !== null && now - oldest > DAY,
      progress: syncing && progress ? { ...progress } : null,
      last_result: recent ? { sent: lastResult.sent, received: lastResult.received } : null,
      now,
    };
  }

  function onChange(fn) { listeners.push(fn); return () => { const i = listeners.indexOf(fn); if (i >= 0) listeners.splice(i, 1); }; }
  function emit(kind, detail) {
    for (const fn of listeners.slice()) {
      try { fn(kind, detail || {}); } catch (e) { console.error(e); }
    }
  }
  /** One step of the run in flight, for the pill: "sending 2 of 5", "checking 4 days",
      "reading 12 new", then "done" with the totals. */
  function report(phase, done, total, received) {
    progress = { phase, done, total, sent: runSent, received: received || 0 };
    emit("progress", { ...progress });
  }
  const errorInfo = (e) => ({
    at: C.nowIso(),
    status: e && e.status != null ? e.status : null,
    code: (e && e.code) || (e && e.name) || null,
    message: (e && e.message) || String(e),
  });
  const kindOf = (e) => (e && e.kind) || (e && e.name === "SignedOutError" ? "signed_out" : "retryable");
  const idOf = (item) => (item && item.body && (item.body.event_id || item.body.child_id)) || null;
  const heldOf = (id) => (String(id).startsWith("C-") ? Store.child(id) : Store.event(id));

  // -- flush ----------------------------------------------------------------------------------------

  /** Upload the queue in created_at order. A retryable failure stops the walk and keeps the
      rest for later; a permanent one parks the item under bl.failed and carries on; 401/403
      stop it and mark signed out. */
  async function flush() {
    if (!signedIn()) return { skipped: "signed_out" };
    if (inBackoff()) return { skipped: "backoff" };
    const out = { sent: 0, failed: 0, stopped: null };
    const items = Store.queue();
    for (let i = 0; i < items.length; i++) {
      const item = items[i];
      runSent = out.sent;
      report("sending", i + 1, items.length, 0);
      const path = pathFor(item, utcDate());
      if (path !== item.path) {
        // Written back before the PUT so a retry sends the same bytes to the same place. If even
        // that write fails the upload still goes; the worst case is a harmless duplicate later.
        try { await Store.setQueuePath(item.qid, path); } catch { /* see above */ }
      }
      try {
        await Graph.putJSON(path, item.body);
        await Store.drop(item.qid);
        // Our own file need not come back down: mark it seen in its folder, and stamp its name
        // on the held record so wanted() passes it over in folders bl.seen has forgotten.
        const parts = path.split("/");
        if (parts[0] === "events") Store.markSeen(parts[1], [parts[2]]);
        const id = idOf(item);
        if (id) {
          uploaded.add(id);
          const held = heldOf(id);
          if (held && held.revision === item.body.revision) await Store.setFile(id, parts[parts.length - 1]);
        }
        out.sent += 1;
        runSent = out.sent;
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
    const held = heldOf(parsed.id);
    if (!held) return true;
    if (parsed.rev > held.revision) return true;
    return parsed.rev === held.revision && held._file !== name;
  }

  /** Remember a collision for Settings (newest first, one entry per id) and for this pull's
      "applied" event. `other` is the downloaded side, whichever way §3.4 went: the toast says
      who else wrote it, not who won. */
  function noteConflict(id, rec, counts) {
    if (counts.conflicts.includes(id)) return;
    counts.conflicts.push(id);
    const other = { device: rec.device || null, edited_by: rec.edited_by || null, logged_by: rec.logged_by || null,
                    entered_from: rec.entered_from || null, deleted: !!rec.deleted };
    const rest = (Store.meta().conflicts || []).filter((c) => c.event_id !== id);
    Store.setMeta({ conflicts: [{ event_id: id, at: C.nowIso(), other }].concat(rest).slice(0, CONFLICTS_KEEP) });
  }

  /** Download one listed file and apply it. False when nothing usable came back — the folder
      must then not be retired, because the file may simply still be uploading. */
  async function fetchApply(f, dir, parsed, counts) {
    const text = await Graph.getText(f.downloadUrl, `${dir}/${f.name}`);
    let rec = null;
    try { rec = text === null ? null : JSON.parse(text); } catch { rec = null; }
    counts.downloaded += 1;
    if (!rec) { counts.bad += 1; return false; }
    if (isConflict(heldOf(parsed.id), rec, counts.queued)) noteConflict(parsed.id, rec, counts);
    if (await Store.applyRemote(rec, f.name)) {
      counts.applied += 1;
      counts.changed.push(parsed.id);
    }
    return true;
  }

  /** One day folder. Resolves true when the pass skipped nothing: a zero-size listing (still
      uploading) or an empty download means the folder has to be listed again. */
  async function pullFolder(day, counts, at, of) {
    report("listing", at || 1, of || 1, counts.applied);
    const files = await Graph.listFolder(`events/${day}`);
    const seen = new Set(Store.seen(day));
    let batch = [];
    let clean = true;
    const flushSeen = () => { if (batch.length) { Store.markSeen(day, batch); batch = []; } };
    // What this folder holds that the phone has not: counted first so the pill can say how many.
    const todo = [];
    for (const f of files) {
      if (f.isFolder || seen.has(f.name)) continue;
      const parsed = C.parseName(f.name);
      if (!parsed) continue;                    // OneDrive's temp files and the like
      if (f.size === 0) { clean = false; continue; }   // still uploading; leave it for the next pull
      todo.push({ f, parsed, fetch: wanted(parsed, f.name) });
    }
    counts.to_read += todo.filter((t) => t.fetch).length;
    for (const t of todo) {
      if (t.fetch) {
        report("reading", counts.downloaded + 1, counts.to_read, counts.applied);
        if (!(await fetchApply(t.f, `events/${day}`, t.parsed, counts))) clean = false;
      }
      batch.push(t.f.name);
      if (batch.length >= SEEN_BATCH) flushSeen();
    }
    flushSeen();
    return clean;
  }

  async function pullChildren(counts) {
    for (const f of await Graph.listFolder("children")) {
      if (f.isFolder) continue;
      const parsed = C.parseName(f.name);
      if (!parsed || f.size === 0 || !wanted(parsed, f.name)) continue;
      await fetchApply(f, "children", parsed, counts);
    }
  }

  /** First sign-in, or a month since the last full pass: every day folder within 120 days that
      is not yet fully caught up. Days older than yesterday are marked done once listed clean,
      so an interrupted catch-up resumes where it stopped — and only when clean, because bl.done
      is never revisited: a folder retired with a half-uploaded file in it would keep that file
      from every phone for good. */
  async function catchUp(today, counts) {
    const done = new Set(Store.done());
    const yesterday = shift(today, -1);
    const folders = (await Graph.listFolder("events"))
      .filter((f) => f.isFolder && isDay(f.name))
      .map((f) => f.name)
      .filter((d) => daysBetween(d, today) <= KEEP_DAYS && !done.has(d))
      .sort();
    for (let i = 0; i < folders.length; i++) {
      const day = folders[i];
      const clean = await pullFolder(day, counts, i + 1, folders.length);
      if (clean && day < yesterday) Store.markDone(day);
    }
    counts.folders += folders.length;
  }

  /** List the folders since the last pull (or catch up), apply what is new, then children/.
      last_sync_at moves only after a pull that finished with no error. The "applied" event
      carries the ids that changed and the ids that collided (§3.4 settled those; app.js says
      so), whether or not the pull got to the end. */
  async function pull() {
    if (!signedIn()) return { skipped: "signed_out" };
    if (inBackoff()) return { skipped: "backoff" };
    const counts = { folders: 0, downloaded: 0, to_read: 0, applied: 0, bad: 0, changed: [], conflicts: [], catch_up: false,
                     queued: new Set(Store.queue().map(idOf).filter(Boolean).concat(Array.from(uploaded))) };
    const m = Store.meta();
    const today = utcDate();
    const plan = foldersToList(m.last_sync_at, today);
    const fullAt = Date.parse(m.full_sync_at || "");
    counts.catch_up = plan.catch_up || Number.isNaN(fullAt) || Date.now() - fullAt > FULL_EVERY_DAYS * DAY;
    const report = () => { if (counts.changed.length || counts.conflicts.length) emit("applied", { ids: counts.changed, conflicts: counts.conflicts }); };
    try {
      if (counts.catch_up) {
        await catchUp(today, counts);
      } else {
        for (let i = 0; i < plan.folders.length; i++) await pullFolder(plan.folders[i], counts, i + 1, plan.folders.length);
        counts.folders += plan.folders.length;
      }
      await pullChildren(counts);
    } catch (e) {
      const kind = kindOf(e);
      if (kind !== "signed_out") Store.setMeta({ last_error: errorInfo(e) });
      counts.stopped = kind;
      counts.error = errorInfo(e);
      report();
      return counts;
    }
    const patch = { last_sync_at: C.nowIso(), last_error: null };
    if (counts.catch_up) patch.full_sync_at = patch.last_sync_at;
    Store.setMeta(patch);
    report();
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
        runSent = 0;
        progress = null;
        emit("status");
        try {
          result.flush = await flush();
          runSent = result.flush.sent || 0;
          result.pull = await pull();
          // The outcome, kept on the pill for six seconds — only after a run that finished
          // clean; a stopped one is what "Sync failed" is for.
          if (!result.flush.stopped && !result.flush.skipped && !result.pull.stopped && !result.pull.skipped) {
            lastResult = { sent: runSent, received: result.pull.applied || 0, at: Date.now() };
            report("done", 1, 1, lastResult.received);
            setTimeout(() => emit("status", {}), RESULT_MS + 200);   // the pill's usual words come back
          }
        } catch (e) {
          // Only a bug reaches here: flush and pull report their own failures.
          console.error(e);
          Store.setMeta({ last_error: errorInfo(e) });
        } finally {
          syncing = false;
          progress = null;
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

  /** Settings → Sync now: forget which folders were caught up and run a full catch-up. This is
      the way back for a file that landed in a folder after bl.done retired it. */
  function fullSync() {
    Store.clearDone();
    Store.setMeta({ full_sync_at: null });
    return run();
  }

  return {
    foldersToList, pathFor, classify, backoffMs, stalePull, isConflict, statusText, status,
    flush, pull, run, afterWrite: run, fullSync, start, stop, state, onChange,
    isSyncing: () => syncing,
  };
})();

if (typeof module !== "undefined") module.exports = Sync;
