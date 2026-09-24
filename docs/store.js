/* Baby Log — phone-side storage and the upload queue (SPEC.md §7.2).

   Logging a feed with no connection has to work exactly as it does with one. So every record is
   written locally first and queued; uploading is a separate, retryable step. Nothing is ever held
   only in memory, because the app can be killed between the crib and the couch.

   Records live in IndexedDB with a memory mirror loaded once by open(): reads are synchronous
   from memory, writes go to memory and IndexedDB and are awaited before the UI says "Saved". A
   write that IndexedDB refuses is rolled back from memory and surfaces as StorageError, so the
   editor stays open with what was typed rather than pretending.

   Records are shaped exactly as store.py writes them (SPEC.md §3.2) and validated with the same
   Core.validate the PC uses, so the two writers cannot drift. */
"use strict";

/** IndexedDB refused a write: the memory copy has been reverted and nothing was saved. */
class StorageError extends Error {
  constructor(message) {
    super(message || "storage failed");
    this.name = "StorageError";
  }
}

const Store = (() => {
  const K = {
    settings: "bl.settings",
    meta: "bl.meta",
    seen: "bl.seen",
    done: "bl.done",
    draft: "bl.draft",
    failed: "bl.failed",
  };
  const DB_NAME = "baby-log";
  const DB_VERSION = 1;
  const KEEP_DAYS = 120;
  const DAY = 86400000;
  const SEEN_KEEP = 3;

  // §6.1's keys plus the phone's own device id; night_override is §7.4's moon button.
  const SETTINGS = {
    label: "", units: "ml", step_ml: null, quick_mode: "recent", quick_custom: [],
    night_from: "21:00", night_to: "07:00", child_id: null, night_override: null,
  };
  const META = {
    last_sync_at: null, full_sync_at: null, signed_out: false, last_error: null,
    signed_in_as: null, backoff_until: null,
  };
  const EVENT_FIELDS = ["child_id", "type", "time", "end", "data", "note", "logged_by"];
  const CHILD_FIELDS = ["name", "born", "born_time", "sex", "birth_weight_g", "targets"];
  const TARGETS = { feeds_per_day: null, wet_per_day: null, dirty_per_day: null };

  let db = null;
  const events = new Map();
  const children = new Map();
  let queue = [];
  let persistAsked = false;

  // -- localStorage, guarded --------------------------------------------------------------------
  // Private browsing and a full quota both throw, and losing a draft must never take the app
  // down with it. Every write reports whether it landed; callers that care check.
  function read(key, fallback) {
    try {
      const raw = localStorage.getItem(key);
      return raw ? JSON.parse(raw) : fallback;
    } catch { return fallback; }
  }
  function write(key, value) {
    try { localStorage.setItem(key, JSON.stringify(value)); return true; } catch { return false; }
  }
  function remove(key) {
    try { localStorage.removeItem(key); return true; } catch { return false; }
  }

  // -- IndexedDB --------------------------------------------------------------------------------
  function openDb() {
    return new Promise((resolve, reject) => {
      if (typeof indexedDB === "undefined") { reject(new StorageError("IndexedDB unavailable")); return; }
      let req;
      try { req = indexedDB.open(DB_NAME, DB_VERSION); } catch (e) { reject(e); return; }
      req.onupgradeneeded = () => {
        const d = req.result;
        if (!d.objectStoreNames.contains("events")) d.createObjectStore("events", { keyPath: "event_id" });
        if (!d.objectStoreNames.contains("children")) d.createObjectStore("children", { keyPath: "child_id" });
        if (!d.objectStoreNames.contains("queue")) d.createObjectStore("queue", { keyPath: "qid" });
      };
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error || new StorageError("could not open the database"));
      req.onblocked = () => reject(new StorageError("database blocked"));
    });
  }
  function readAll(name) {
    return new Promise((resolve, reject) => {
      const tx = db.transaction(name, "readonly");
      const req = tx.objectStore(name).getAll();
      req.onsuccess = () => resolve(req.result || []);
      req.onerror = () => reject(req.error);
    });
  }
  /** Every op in one transaction, so a record and its queue item land together or not at all. */
  function commit(ops) {
    return new Promise((resolve, reject) => {
      if (!db) { reject(new StorageError("storage unavailable")); return; }
      const names = Array.from(new Set(ops.map((o) => o.store)));
      let tx;
      try { tx = db.transaction(names, "readwrite"); } catch (e) { reject(new StorageError(String(e && e.message || e))); return; }
      const fail = () => reject(new StorageError((tx.error && tx.error.message) || "write failed"));
      tx.oncomplete = () => resolve(true);
      tx.onerror = fail;
      tx.onabort = fail;
      try {
        for (const o of ops) {
          const s = tx.objectStore(o.store);
          if (o.op === "delete") s.delete(o.key); else s.put(o.value);
        }
      } catch (e) { reject(new StorageError(String(e && e.message || e))); }
    });
  }
  /** Apply to memory, write, and on failure revert — the UI only hears "Saved" after this. */
  async function save(ops, apply, revert) {
    apply();
    try {
      await commit(ops);
    } catch (e) {
      revert();
      throw e instanceof StorageError ? e : new StorageError(String(e && e.message || e));
    }
    askPersist();
    return true;
  }
  // Once, after the first write: without it Safari may evict the database under storage pressure.
  function askPersist() {
    if (persistAsked) return;
    persistAsked = true;
    try {
      if (typeof navigator !== "undefined" && navigator.storage && navigator.storage.persist) {
        navigator.storage.persist().catch(() => {});
      }
    } catch { /* not offered here */ }
  }

  const byCreated = (a, b) => (a.created_at < b.created_at ? -1 : a.created_at > b.created_at ? 1 : 0);

  /** Load the mirror. Resolves true when IndexedDB opened; false means every write will throw. */
  async function open() {
    if (db) return true;
    try {
      db = await openDb();
      const [evs, chs, q] = await Promise.all([readAll("events"), readAll("children"), readAll("queue")]);
      events.clear(); children.clear();
      for (const r of evs) events.set(r.event_id, r);
      for (const r of chs) children.set(r.child_id, r);
      queue = q.sort(byCreated);
    } catch (e) {
      db = null;
      return false;
    }
    try { await prune(); } catch { /* best effort; the next open tries again */ }
    return true;
  }

  // -- small state -------------------------------------------------------------------------------
  function settings() {
    const s = { ...SETTINGS, ...read(K.settings, {}) };
    if (!s.device) {
      // Minted once and kept: it is what tells the two phones' revisions apart (§3.2).
      s.device = `d-${Core.rand4()}`;
      write(K.settings, s);
    }
    return s;
  }
  function setSettings(patch) {
    const cur = settings();
    for (const k of Object.keys(patch || {})) {
      if (k in SETTINGS) cur[k] = patch[k];
    }
    return write(K.settings, cur);
  }
  const meta = () => ({ ...META, ...read(K.meta, {}) });
  const setMeta = (patch) => write(K.meta, { ...meta(), ...patch });

  const seenAll = () => read(K.seen, {});
  const seen = (folder) => seenAll()[folder] || [];
  /** Remember downloaded names per day folder, keeping only the three most recent folders so
      localStorage never grows with the journal. */
  function markSeen(folder, names) {
    const all = seenAll();
    const cur = new Set(all[folder] || []);
    for (const n of names || []) cur.add(n);
    all[folder] = Array.from(cur);
    for (const k of Object.keys(all).sort().slice(0, -SEEN_KEEP)) delete all[k];
    return write(K.seen, all);
  }
  const done = () => read(K.done, []);
  function markDone(folder) {
    const d = done();
    if (!d.includes(folder)) d.push(folder);
    return write(K.done, d.sort());
  }
  const draft = () => read(K.draft, null);
  const setDraft = (d) => write(K.draft, d);
  const clearDraft = () => remove(K.draft);
  const failed = () => read(K.failed, []);

  // -- the queue --------------------------------------------------------------------------------
  const queueList = () => queue.slice().sort(byCreated);
  const queueItem = (body, kind) => ({ qid: Core.newId("Q"), kind, path: null, body, created_at: Core.nowIso() });

  /** The path is assigned by Sync.flush on the first attempt and kept for retries (§7.2). */
  async function setQueuePath(qid, path) {
    const item = queue.find((i) => i.qid === qid);
    if (!item) return false;
    const before = item.path;
    return save([{ store: "queue", op: "put", value: { ...item, path } }],
      () => { item.path = path; }, () => { item.path = before; });
  }
  async function drop(qid) {
    const idx = queue.findIndex((i) => i.qid === qid);
    if (idx < 0) return false;
    const [item] = queue.splice(idx, 1);
    try {
      await commit([{ store: "queue", op: "delete", key: qid }]);
    } catch (e) {
      queue.splice(idx, 0, item);
      throw e instanceof StorageError ? e : new StorageError(String(e && e.message || e));
    }
    return true;
  }
  /** Graph refused the item for good: park it under bl.failed for Settings' Retry / Discard. */
  async function fail(item, err) {
    const list = failed().filter((f) => f.qid !== item.qid);
    list.push({
      ...item,
      status: err && err.status != null ? err.status : null,
      code: (err && err.code) || null,
      message: (err && err.message) || String(err),
      failed_at: Core.nowIso(),
    });
    write(K.failed, list);
    await drop(item.qid);
  }
  async function retryFailed(qid) {
    const list = failed();
    const f = list.find((x) => x.qid === qid);
    if (!f) return false;
    // A fresh path: whatever OneDrive disliked about the old one is not repeated.
    const item = { qid: f.qid, kind: f.kind, path: null, body: f.body, created_at: Core.nowIso() };
    await save([{ store: "queue", op: "put", value: item }],
      () => queue.push(item), () => { queue = queue.filter((i) => i !== item); });
    write(K.failed, list.filter((x) => x.qid !== qid));
    return true;
  }
  const discardFailed = (qid) => write(K.failed, failed().filter((x) => x.qid !== qid));

  // -- records, shaped exactly as store.py writes them ------------------------------------------
  function checkTimes(time, end) {
    const t = Core.parseIso(time);
    if (!t) throw new Error("time must be YYYY-MM-DDTHH:MM:SS±HH:MM");
    if (end !== null && end !== undefined) {
      const e = Core.parseIso(end);
      if (!e) throw new Error("end must be YYYY-MM-DDTHH:MM:SS±HH:MM or null");
      if (e.getTime() < t.getTime()) throw new Error("end is before time");
    }
  }
  /** The §3.2 record, key order and all; extra top-level keys a reader carried are kept last. */
  function eventRecord(base, fields, held) {
    const s = settings();
    const type = fields.type !== undefined ? fields.type : held && held.type;
    if (!Core.TYPES.includes(type)) throw new Error(`unknown type: ${type}`);
    const time = fields.time !== undefined ? fields.time : held ? held.time : Core.isoLocal();
    const end = fields.end !== undefined ? fields.end : held ? held.end : null;
    checkTimes(time, end);
    // A changed type starts from that type's defaults: the old data would not validate.
    const data = fields.data !== undefined ? fields.data : held && held.type === type ? held.data : {};
    const child_id = fields.child_id || (held && held.child_id) || s.child_id || (child() || {}).child_id;
    if (!child_id) throw new Error("no child");
    const rec = {
      event_id: base.event_id,
      revision: base.revision,
      deleted: !!base.deleted,
      reason: base.reason === undefined ? null : base.reason,
      child_id,
      type,
      time,
      end: end === undefined ? null : end,
      data: Core.validate(type, data),
      note: fields.note !== undefined ? String(fields.note || "") : (held && held.note) || "",
      logged_by: fields.logged_by || (held && held.logged_by) || s.label,
      edited_by: base.revision > 1 ? s.label : null,
      device: s.device,
      entered_from: "phone",
      created_at: Core.nowIso(),
    };
    for (const k of Object.keys(held || {})) {
      if (!(k in rec) && !k.startsWith("_")) rec[k] = held[k];
    }
    return rec;
  }
  function checkFields(fields, allowed) {
    for (const k of Object.keys(fields || {})) {
      if (!allowed.includes(k)) throw new Error(`unknown field: ${k}`);
    }
  }

  /** Save the record and queue its upload, in one transaction, then tell the caller it is safe. */
  async function saveEvent(rec) {
    const item = queueItem(rec, "event");
    const before = events.get(rec.event_id);
    await save([
      { store: "events", op: "put", value: rec },
      { store: "queue", op: "put", value: item },
    ], () => { events.set(rec.event_id, rec); queue.push(item); },
       () => { if (before) events.set(rec.event_id, before); else events.delete(rec.event_id); queue = queue.filter((i) => i !== item); });
    return rec;
  }

  async function newEvent(fields) {
    checkFields(fields, EVENT_FIELDS);
    return saveEvent(eventRecord({ event_id: Core.newId("E"), revision: 1 }, fields || {}, null));
  }
  /** A correction: the same event, one revision later, logged_by carried unless changed. */
  async function revise(held, fields) {
    checkFields(fields, EVENT_FIELDS);
    const cur = events.get(held.event_id) || held;
    return saveEvent(eventRecord({ event_id: cur.event_id, revision: cur.revision + 1 }, fields || {}, cur));
  }
  /** A tombstone is a full copy of the latest record with deleted: true (§3.1). */
  async function tombstone(held, reason) {
    const cur = events.get(held.event_id) || held;
    if (cur.deleted) throw new Error("already deleted");
    return saveEvent(eventRecord({ event_id: cur.event_id, revision: cur.revision + 1, deleted: true,
                                   reason: reason == null ? null : String(reason) }, {}, cur));
  }
  /** The phone holds only the resolved record, so a restore is built from the tombstone's body. */
  async function restore(held) {
    const cur = events.get(held.event_id) || held;
    if (!cur.deleted) throw new Error("not deleted");
    return saveEvent(eventRecord({ event_id: cur.event_id, revision: cur.revision + 1, deleted: false, reason: null }, {}, cur));
  }

  const isDate = (s) => typeof s === "string" && /^\d{4}-\d{2}-\d{2}$/.test(s) && !Number.isNaN(Date.parse(`${s}T00:00:00Z`));
  const numOrNull = (v, name) => {
    if (v === null || v === undefined) return null;
    if (typeof v !== "number" || !Number.isFinite(v) || v < 0) throw new Error(`${name} must be a number >= 0`);
    return v;
  };
  /** The phone never creates a child (§3.3); it can revise one. */
  async function reviseChild(held, fields) {
    checkFields(fields, CHILD_FIELDS);
    const cur = children.get(held.child_id) || held;
    const f = fields || {};
    const name = f.name !== undefined ? f.name : cur.name;
    if (typeof name !== "string" || !name.trim()) throw new Error("name is required");
    const born = f.born !== undefined ? f.born : cur.born;
    if (!isDate(born)) throw new Error("born must be YYYY-MM-DD");
    const born_time = f.born_time !== undefined ? f.born_time : cur.born_time;
    if (born_time !== null && born_time !== undefined && !/^\d{2}:\d{2}$/.test(String(born_time))) throw new Error("born_time must be HH:MM");
    const sex = f.sex !== undefined ? f.sex : cur.sex;
    if (sex !== null && sex !== undefined && typeof sex !== "string") throw new Error("sex must be text");
    const targets = { ...TARGETS, ...(cur.targets || {}) };
    for (const k of Object.keys(f.targets || {})) {
      if (!(k in TARGETS)) throw new Error(`unknown field: targets.${k}`);
      targets[k] = numOrNull(f.targets[k], `targets.${k}`);
    }
    const rec = {
      child_id: cur.child_id,
      revision: cur.revision + 1,
      deleted: false,
      reason: null,
      name: name.trim(),
      born,
      born_time: born_time === undefined ? null : born_time,
      sex: sex === undefined ? null : sex,
      birth_weight_g: numOrNull(f.birth_weight_g !== undefined ? f.birth_weight_g : cur.birth_weight_g, "birth_weight_g"),
      targets,
      device: settings().device,
      created_at: Core.nowIso(),
    };
    for (const k of Object.keys(cur)) if (!(k in rec) && !k.startsWith("_")) rec[k] = cur[k];
    const item = queueItem(rec, "child");
    const before = children.get(rec.child_id);
    await save([
      { store: "children", op: "put", value: rec },
      { store: "queue", op: "put", value: item },
    ], () => { children.set(rec.child_id, rec); queue.push(item); },
       () => { if (before) children.set(rec.child_id, before); else children.delete(rec.child_id); queue = queue.filter((i) => i !== item); });
    return rec;
  }

  /** A downloaded record replaces the held one iff it wins the §3.4 resolution. The queue is
      left alone: a superseded queued revision still uploads, and resolution ignores it. */
  async function applyRemote(record, fileName) {
    if (!record || typeof record !== "object") return false;
    const key = record.event_id != null ? "event_id" : record.child_id != null ? "child_id" : null;
    if (!key || typeof record.revision !== "number") return false;
    const map = key === "event_id" ? events : children;
    const store = key === "event_id" ? "events" : "children";
    const id = record[key];
    const rec = { ...record, _file: String(fileName || "") };
    const held = map.get(id);
    if (held && Core.resolve([held, rec], key).get(id) !== rec) return false;
    await save([{ store, op: "put", value: rec }],
      () => map.set(id, rec), () => { if (held) map.set(id, held); else map.delete(id); });
    return true;
  }

  // -- reads, all from memory --------------------------------------------------------------------
  const eventsLive = () => Core.live(Array.from(events.values()), "event_id");
  const event = (id) => events.get(id) || null;
  const childrenLive = () => Core.live(Array.from(children.values()), "child_id")
    .sort((a, b) => (a.child_id < b.child_id ? -1 : a.child_id > b.child_id ? 1 : 0));
  /** child(id) → the held record, tombstone included; child() → the current child (§3.3). */
  function child(id) {
    if (id !== undefined) return children.get(id) || null;
    const live = childrenLive();
    const chosen = settings().child_id;
    return live.find((c) => c.child_id === chosen) || live[0] || null;
  }
  const deleted = () => Array.from(events.values()).filter((e) => e.deleted)
    .sort((a, b) => -byCreated(a, b));
  // The paper import joins a row's own note and its question as "note — Check: …" (§10).
  const needsCheck = () => eventsLive().filter((e) => /^Check: | — Check: /.test(String(e.note || "")));

  async function usage() {
    const out = { events: events.size, children: children.size, queue: queue.length,
                  failed: failed().length, usage: null, quota: null };
    try {
      if (typeof navigator !== "undefined" && navigator.storage && navigator.storage.estimate) {
        const est = await navigator.storage.estimate();
        out.usage = est.usage == null ? null : est.usage;
        out.quota = est.quota == null ? null : est.quota;
      }
    } catch { /* not offered here */ }
    return out;
  }

  /** Drop events older than 120 days; anything a queue item still refers to stays. */
  async function prune(now = Date.now()) {
    const cutoff = now - KEEP_DAYS * DAY;
    const pinned = new Set(queue.map((i) => i.body && i.body.event_id).filter(Boolean));
    const gone = [];
    for (const ev of events.values()) {
      if (pinned.has(ev.event_id)) continue;
      const t = Core.parseIso(ev.time);
      if (t && t.getTime() < cutoff) gone.push(ev);
    }
    if (!gone.length) return 0;
    await save(gone.map((ev) => ({ store: "events", op: "delete", key: ev.event_id })),
      () => gone.forEach((ev) => events.delete(ev.event_id)),
      () => gone.forEach((ev) => events.set(ev.event_id, ev)));
    return gone.length;
  }

  return {
    StorageError,
    open,
    settings, setSettings, meta, setMeta,
    seen, markSeen, done, markDone, draft, setDraft, clearDraft,
    failed, fail, retryFailed, discardFailed,
    queue: queueList, setQueuePath, drop,
    newEvent, revise, tombstone, restore, reviseChild, applyRemote,
    events: eventsLive, event, children: childrenLive, child, deleted, needsCheck,
    usage, prune,
    ready: () => !!db,
  };
})();
