/* Baby Log — the logic both front ends share (SPEC.md §5).

   Pure functions, no DOM, no storage. The PC serves this same file at /core.js, so the phone and
   the desktop cannot drift apart on how a feed is described, how a filename is parsed, or which
   of two concurrent revisions wins. tests/test_core.py runs it under Node against
   tests/fixtures/data_cases.json, the fixture store.py is tested against too.

   Units: ml and seconds/milliseconds everywhere unless the name says otherwise; a `unit`
   argument ("ml" | "oz") changes only formatting and step size. Must run in Safari, Edge and
   Node 14/16 — so no ??=, no .at(), no structuredClone, and crypto is looked up at call time. */
"use strict";

const Core = (() => {
  const pad = (n, w = 2) => String(n).padStart(w, "0");
  const OZ_ML = 29.5735;
  const MIN = 60000, HOUR = 3600000, DAY = 86400000;
  const TYPES = ["feed", "diaper", "sleep", "pump", "growth", "health", "note"];
  const ENUMS = {
    bottle_kind: ["formula", "breast_milk"],
    side: ["left", "right"],
    color: ["black", "dark_green", "green", "yellow", "brown", "other"],
    texture: ["sticky", "seedy", "soft", "solid", "watery"],
    size: ["small", "medium", "large"],
  };
  // The one filename rule (§3.1). The revision is written without padding, so "r01" is not a
  // journal file and must not be read as one — hence [1-9]\d* rather than \d+.
  const NAME_RE = /^([EC]-.+)-r([1-9]\d*)-([0-9a-f]{4})\.json$/;
  const ISO_RE = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})([+-])(\d{2}):(\d{2})$/;
  const CREATED_RE = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}\+00:00$/;
  const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

  const DEFAULTS = {
    feed: { breast: { left_s: null, right_s: null, total_s: null, last_side: null, approx: false },
            bottles: [], made_ml: null, leftover_ml: null, timer: null },
    diaper: { wet: false, dirty: false, color: null, texture: null, size: null, rash: false, blowout: false },
    sleep: { where: null, timer: null },
    pump: { left_ml: null, right_ml: null, minutes: null },
    growth: { weight_g: null, length_cm: null, head_cm: null },
    health: { temp_c: null, medicine: null, dose: null, symptom: null },
    note: { milestone: false },
  };
  // What each key may hold. "num" is null or a finite number >= 0; the three compound kinds
  // (breast, bottles, the timers) have their own checks below.
  const FIELDS = {
    feed: { breast: "breast", bottles: "bottles", made_ml: "num", leftover_ml: "num", timer: "feed_timer" },
    diaper: { wet: "bool", dirty: "bool", color: "enum:color", texture: "enum:texture", size: "enum:size",
              rash: "bool", blowout: "bool" },
    sleep: { where: "str", timer: "sleep_timer" },
    pump: { left_ml: "num", right_ml: "num", minutes: "num" },
    growth: { weight_g: "num", length_cm: "num", head_cm: "num" },
    health: { temp_c: "num", medicine: "str", dose: "str", symptom: "str" },
    note: { milestone: "bool" },
  };
  const BREAST = { left_s: "num", right_s: "num", total_s: "num", last_side: "enum:side", approx: "bool" };

  const isObj = (v) => v !== null && typeof v === "object" && !Array.isArray(v);
  const clone = (v) => JSON.parse(JSON.stringify(v));

  // Browsers have globalThis.crypto; Node 16 hides the same API under require("crypto").webcrypto
  // and Node 14 has only randomFillSync. Resolved per call so the file loads anywhere.
  function cryptoObj() {
    if (typeof globalThis !== "undefined" && globalThis.crypto && globalThis.crypto.getRandomValues) {
      return globalThis.crypto;
    }
    if (typeof require === "function") {
      const c = require("crypto");
      if (c.webcrypto) return c.webcrypto;
      return { getRandomValues: (buf) => c.randomFillSync(buf) };
    }
    throw new Error("no crypto source");
  }

  // -- ids, names, instants ----------------------------------------------------------------

  // UTC "YYYYMMDD-HHMMSS", matching store.py's stamp so both devices name files the same way.
  function stamp(d = new Date()) {
    return `${d.getUTCFullYear()}${pad(d.getUTCMonth() + 1)}${pad(d.getUTCDate())}`
      + `-${pad(d.getUTCHours())}${pad(d.getUTCMinutes())}${pad(d.getUTCSeconds())}`;
  }
  // Four hex characters: the suffix that keeps two devices in the same second apart (§1).
  function rand4() {
    const b = new Uint8Array(2);
    cryptoObj().getRandomValues(b);
    return Array.from(b).map((x) => x.toString(16).padStart(2, "0")).join("");
  }
  // `${prefix}-${stamp}-${rand4}` — an event or child id; never changes across revisions.
  const newId = (prefix, date = new Date()) => `${prefix}-${stamp(date)}-${rand4()}`;
  // `${id}-r${rev}-${w}.json` with a fresh w per write, so two writers of one revision coexist.
  const fileName = (id, rev) => `${id}-r${rev}-${rand4()}.json`;
  // {id, rev, w} for a journal filename, or null for anything that is not one (temp files etc.).
  function parseName(name) {
    const m = NAME_RE.exec(String(name));
    return m ? { id: m[1], rev: Number(m[2]), w: m[3] } : null;
  }
  // created_at: UTC with six fractional digits and "+00:00", fixed width so strings sort (§3.2).
  const nowIso = () => new Date().toISOString().replace("Z", "000+00:00");
  // Whole seconds with the zone's numeric offset on that instant — the `time`/`end` shape (§3.2).
  function isoLocal(d = new Date()) {
    const off = -d.getTimezoneOffset();
    const a = Math.abs(off);
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
      + `T${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
      + `${off < 0 ? "-" : "+"}${pad(Math.floor(a / 60))}:${pad(a % 60)}`;
  }
  // A Date for a string of exactly the §3.2 shape, else null. Date.parse alone would accept
  // "Z", fractions and Feb 30, so the components are range-checked here.
  function parseIso(iso) {
    if (typeof iso !== "string") return null;
    const m = ISO_RE.exec(iso);
    if (!m) return null;
    const [y, mo, d, h, mi, s, oh, om] = [m[1], m[2], m[3], m[4], m[5], m[6], m[8], m[9]].map(Number);
    if (mo < 1 || mo > 12 || d < 1 || d > new Date(Date.UTC(y, mo, 0)).getUTCDate()) return null;
    if (h > 23 || mi > 59 || s > 59 || oh > 23 || om > 59) return null;
    const t = Date.parse(iso);
    return Number.isNaN(t) ? null : new Date(t);
  }
  // The display day: the writer's local date, never re-zoned (§3.2).
  const localDate = (iso) => String(iso == null ? "" : iso).slice(0, 10);

  // Milliseconds for a Date, a number, an ISO string, or "now" when absent.
  function toMs(x) {
    if (x == null) return Date.now();
    if (x instanceof Date) return x.getTime();
    if (typeof x === "number") return x;
    const d = parseIso(x);
    return d ? d.getTime() : Date.parse(x);
  }

  // -- validation (§3.2) -------------------------------------------------------------------

  // A fresh copy of the full data object for a type, every key present.
  function defaults(type) {
    if (!DEFAULTS[type]) throw new Error(`unknown type: ${type}`);
    return clone(DEFAULTS[type]);
  }

  function check(kind, v, path) {
    if (kind === "bool") {
      if (typeof v !== "boolean") throw new Error(`${path} must be true or false`);
      return v;
    }
    if (kind === "num") {
      if (v === null) return null;
      if (typeof v !== "number" || !Number.isFinite(v) || v < 0) throw new Error(`${path} must be a number >= 0`);
      return v;
    }
    if (kind === "str") {
      if (v === null) return null;
      if (typeof v !== "string") throw new Error(`${path} must be text`);
      return v;
    }
    if (kind.startsWith("enum:")) {
      const set = ENUMS[kind.slice(5)];
      if (v === null) return null;
      if (!set.includes(v)) throw new Error(`${path} must be one of ${set.join(", ")}`);
      return v;
    }
    if (kind === "breast") return merge(BREAST, DEFAULTS.feed.breast, v, path);
    if (kind === "bottles") {
      if (!Array.isArray(v)) throw new Error(`${path} must be a list`);
      return v.map((b, i) => {
        const p = `${path}[${i}]`;
        if (!isObj(b)) throw new Error(`${p} must be an object`);
        for (const k of Object.keys(b)) if (k !== "kind" && k !== "ml" && k !== "formula") throw new Error(`unknown key ${p}.${k}`);
        if (!ENUMS.bottle_kind.includes(b.kind)) throw new Error(`${p}.kind must be formula or breast_milk`);
        if (typeof b.ml !== "number" || !Number.isFinite(b.ml) || b.ml <= 0) throw new Error(`${p}.ml must be a number > 0`);
        // The formula's name as the parents call it; null (the default, and always for breast
        // milk) rather than "" so an untyped name never becomes a chip of its own.
        const formula = b.formula === undefined ? null : b.formula;
        if (formula !== null && (typeof formula !== "string" || formula === "")) throw new Error(`${p}.formula must be text or null`);
        return { kind: b.kind, ml: b.ml, formula };
      });
    }
    if (kind === "feed_timer") {
      if (v === null) return null;
      if (!isObj(v)) throw new Error(`${path} must be null or an object`);
      for (const k of Object.keys(v)) if (k !== "side" && k !== "side_started") throw new Error(`unknown key ${path}.${k}`);
      if (!ENUMS.side.includes(v.side)) throw new Error(`${path}.side must be left or right`);
      if (!parseIso(v.side_started)) throw new Error(`${path}.side_started must be YYYY-MM-DDTHH:MM:SS±HH:MM`);
      return { side: v.side, side_started: v.side_started };
    }
    if (kind === "sleep_timer") {
      if (v === null) return null;
      if (!isObj(v) || Object.keys(v).length !== 1 || v.running !== true) throw new Error(`${path} must be null or {running: true}`);
      return { running: true };
    }
    throw new Error(`no check for ${kind}`);
  }

  // Deep-merge `given` over `base` under a field map, refusing any key the map does not list.
  function merge(fields, base, given, path) {
    if (!isObj(given)) throw new Error(`${path} must be an object`);
    const out = clone(base);
    for (const k of Object.keys(given)) {
      if (!(k in fields)) throw new Error(`unknown key ${path}.${k}`);
      out[k] = check(fields[k], given[k], `${path}.${k}`);
    }
    return out;
  }

  // The caller's data merged over the defaults, or an Error — the same rules as store.py.
  function validate(type, data) {
    if (!FIELDS[type]) throw new Error(`unknown type: ${type}`);
    return merge(FIELDS[type], DEFAULTS[type], data == null ? {} : data, "data");
  }

  // -- resolution (§3.4) -------------------------------------------------------------------

  const END_TYPES = ["feed", "sleep", "pump"];
  // The ordering key for one record: revision, then (feed/sleep/pump) stopped beats running,
  // then created_at, device, and the filename's w. Compared element by element.
  function rank(rec) {
    // Only the write suffix matters here, whatever the id looks like.
    const w = /-r\d+-([0-9a-f]{4})\.json$/.exec(String(rec._file || ""));
    return [
      Number(rec.revision) || 0,
      END_TYPES.includes(rec.type) && rec.end != null ? 1 : 0,
      String(rec.created_at || ""),
      String(rec.device || ""),
      w ? w[1] : "",
    ];
  }
  function beats(a, b) {
    const ra = rank(a), rb = rank(b);
    for (let i = 0; i < ra.length; i++) {
      if (ra[i] > rb[i]) return true;
      if (ra[i] < rb[i]) return false;
    }
    return false;
  }
  // Map id -> the winning record, tombstones included.
  function resolve(records, key = "event_id") {
    const out = new Map();
    for (const rec of records || []) {
      if (!rec || rec[key] == null) continue;
      const held = out.get(rec[key]);
      if (!held || beats(rec, held)) out.set(rec[key], rec);
    }
    return out;
  }
  // The resolved records that are not deleted, by time as an instant, ties by id.
  function live(records, key = "event_id") {
    const out = [];
    for (const rec of resolve(records, key).values()) if (!rec.deleted) out.push(rec);
    return out.sort((a, b) => {
      const d = (toMs(a.time) || 0) - (toMs(b.time) || 0);
      if (d) return d;
      return String(a[key]) < String(b[key]) ? -1 : String(a[key]) > String(b[key]) ? 1 : 0;
    });
  }

  // -- timers and since-last -----------------------------------------------------------------

  // Every event whose local date is `day`.
  const onDay = (events, day) => (events || []).filter((ev) => localDate(ev.time) === day);
  // A feed or sleep with no end yet; `timer` is only informational (§3.2).
  // Running means a timer is going, not merely "no end": a feed typed in from the paper sheet
  // has no end time either, and it must not sit on the Now panel as a 60-hour feed.
  const isRunning = (ev) => !!ev && ev.end === null && (ev.type === "feed" || ev.type === "sleep")
    && !!(ev.data && ev.data.timer);
  // Running longer than anyone feeds (60 min) or a newborn sleeps (6 h): warn, never auto-stop.
  function staleTimer(ev, now) {
    if (!isRunning(ev)) return false;
    const limit = ev.type === "feed" ? 60 * MIN : 6 * HOUR;
    return toMs(now) - toMs(ev.time) > limit;
  }
  // The latest event of a type that started at or before `before`; a running one counts.
  function lastOf(events, type, before) {
    const cut = toMs(before);
    let best = null, bestMs = -Infinity;
    for (const ev of events || []) {
      if (ev.type !== type) continue;
      const ms = toMs(ev.time);
      if (Number.isNaN(ms) || ms > cut) continue;
      if (ms > bestMs || (ms === bestMs && String(ev.event_id) > String(best.event_id))) {
        best = ev; bestMs = ms;
      }
    }
    return best;
  }
  // "1 h 15 m", "45 m", "2 d 3 h": whole units, the trailing zero unit dropped.
  function sinceText(ms) {
    const t = Math.max(0, Math.floor((Number(ms) || 0) / MIN));
    const d = Math.floor(t / 1440), h = Math.floor((t % 1440) / 60), m = t % 60;
    if (d > 0) return h ? `${d} d ${h} h` : `${d} d`;
    if (h > 0) return m ? `${h} h ${m} m` : `${h} h`;
    return `${m} m`;
  }
  function median(nums) {
    const s = nums.slice().sort((a, b) => a - b);
    if (!s.length) return 0;
    const mid = Math.floor(s.length / 2);
    return s.length % 2 ? s[mid] : (s[mid - 1] + s[mid]) / 2;
  }
  // The median gap between the last n starts of a type; null until there are three events.
  function usualGapMs(events, type, n = 6) {
    const starts = (events || []).filter((ev) => ev.type === type).map((ev) => toMs(ev.time))
      .filter((ms) => !Number.isNaN(ms)).sort((a, b) => a - b).slice(-n);
    if (starts.length < 3) return null;
    const gaps = [];
    for (let i = 1; i < starts.length; i++) gaps.push(starts[i] - starts[i - 1]);
    return median(gaps);
  }
  // last feed + usual gap, as a §3.2 string in this device's zone; a hint, never an alarm.
  function nextFeedAt(events) {
    const last = lastOf(events, "feed");
    const gap = usualGapMs(events, "feed");
    if (!last || gap === null) return null;
    return isoLocal(new Date(toMs(last.time) + gap));
  }

  // -- amounts and totals --------------------------------------------------------------------

  // Bottle ml is derived, never stored: the sum of the portions.
  const bottleMl = (ev) => ((ev && ev.data && ev.data.bottles) || [])
    .reduce((a, b) => a + (Number(b.ml) || 0), 0);
  // Breast seconds so far: the folded total (or the sides) plus the running side's elapsed time.
  function breastSeconds(ev, now) {
    const br = (ev && ev.data && ev.data.breast) || {};
    let s = br.total_s != null ? br.total_s : (br.left_s || 0) + (br.right_s || 0);
    const timer = ev && ev.data && ev.data.timer;
    if (isRunning(ev) && timer && timer.side_started) {
      s += Math.max(0, (toMs(now) - toMs(timer.side_started)) / 1000);
    }
    return Math.floor(s);
  }
  // The day's counts for the Now panel and the day sheet; running feeds and sleeps fold `now`.
  function totals(events, day, now) {
    const t = { feeds: 0, bottle_ml: 0, breast_s: 0, wet: 0, dirty: 0, sleeps: 0, sleep_s: 0, pumps: 0, pump_ml: 0 };
    for (const ev of onDay(events, day)) {
      const data = ev.data || {};
      if (ev.type === "feed") {
        t.feeds += 1;
        t.bottle_ml += bottleMl(ev);
        t.breast_s += breastSeconds(ev, now);
      } else if (ev.type === "diaper") {
        if (data.wet) t.wet += 1;
        if (data.dirty) t.dirty += 1;
      } else if (ev.type === "sleep") {
        t.sleeps += 1;
        const end = ev.end === null ? toMs(now) : toMs(ev.end);
        t.sleep_s += Math.max(0, Math.floor((end - toMs(ev.time)) / 1000));
      } else if (ev.type === "pump") {
        t.pumps += 1;
        t.pump_ml += (data.left_ml || 0) + (data.right_ml || 0);
      }
    }
    return t;
  }

  // ml -> the unit's number (oz to 2 places), for an editor field.
  const toUnit = (ml, unit) => unit === "oz" ? Math.round((ml / OZ_ML) * 100) / 100 : ml;
  // The unit's number -> whole ml, the only thing ever stored (§8.1).
  const fromUnit = (v, unit) => Math.round(unit === "oz" ? Number(v) * OZ_ML : Number(v));
  // "22 ml" / "0.75 oz": oz shown to the nearest quarter so 7 ml reads 0.25 and 240 reads 8.
  // A 1–3 ml portion is not nothing: when the quarter would print 0, fall back to the editor's
  // two places (toUnit), so 3 ml reads 0.1 oz and the label agrees with the field.
  function fmtAmount(ml, unit) {
    if (unit === "oz") {
      const q = Math.round((ml / OZ_ML) * 4) / 4;
      return `${q === 0 && ml > 0 ? toUnit(ml, "oz") : q} oz`;
    }
    return `${Math.round(ml)} ml`;
  }
  // The −/+ step that grows with him: fine while feeds are small, coarser later (§5).
  function stepMl(recentMls, unit) {
    const med = median(recentMls || []);
    if (unit === "oz") return med < 1.5 * OZ_ML ? 7 : 15;
    return med < 40 ? 1 : med < 100 ? 5 : 10;
  }
  // The spacing between quick-amount chips, one tier coarser than the −/+ step.
  function chipStepMl(recentMls, unit) {
    const med = median(recentMls || []);
    if (unit === "oz") return med < 1.5 * OZ_ML ? 7 : med < 4 * OZ_ML ? 15 : 30;
    return med < 40 ? 5 : med < 100 ? 10 : med < 200 ? 20 : 30;
  }
  // Four chips around the median (−1, 0, +1, +2 chip steps), shifted up until all are > 0;
  // a non-empty `custom` list is returned as given.
  function quickAmounts(recentMls, unit, custom) {
    if (Array.isArray(custom) && custom.length) return custom;
    const step = chipStepMl(recentMls, unit);
    let base = Math.round(median(recentMls || []) / step) * step;
    while (base - step <= 0) base += step;
    return [base - step, base, base + step, base + 2 * step];
  }
  // More than twice his biggest recent feed — worth one "Save anyway?"; never with < 3 recent.
  function unusual(ml, recentMls) {
    const r = recentMls || [];
    return r.length >= 3 && ml > 2 * Math.max.apply(null, r);
  }
  // The range chips (§8.1): every step from `from` to `to` inclusive, the bounds swapped when
  // typed backwards. Capped at 12 so a stray "to 400" cannot fill the screen with chips, and []
  // rather than an endless loop when the step is 0 or a bound is missing.
  function quickRange(fromMl, toMl, stepMl) {
    // A blank settings field is "" and Number("") is 0 — treat it as missing, not as zero ml.
    const missing = (x) => x == null || x === "" || !Number.isFinite(Number(x));
    if (missing(fromMl) || missing(toMl) || missing(stepMl)) return [];
    const a = Number(fromMl), b = Number(toMl), step = Math.abs(Number(stepMl));
    if (step <= 0) return [];
    const lo = Math.min(a, b), hi = Math.max(a, b);
    const out = [];
    for (let v = lo; v <= hi && out.length < 12; v += step) out.push(v);
    return out;
  }
  // The formula chips: the distinct names of the most recent portions, newest first, at most
  // four; the two starters when nothing has been recorded yet (§8.1). Nothing is stored for
  // this, so every device agrees without configuration.
  function formulaChoices(recentFormulas) {
    const out = [];
    for (const name of recentFormulas || []) {
      if (typeof name !== "string" || name === "" || out.includes(name)) continue;
      out.push(name);
      if (out.length === 4) break;
    }
    return out.length ? out : ["Similac", "Enfamil"];
  }
  // The first portion's formula name, or null: what "Same as last" preselects.
  function formulaOf(ev) {
    const bottles = (ev && ev.data && ev.data.bottles) || [];
    const first = bottles[0];
    return first && typeof first.formula === "string" && first.formula !== "" ? first.formula : null;
  }

  // -- ages and dates ------------------------------------------------------------------------

  // Whole days between two "YYYY-MM-DD" strings, zone-free.
  function daysBetween(a, b) {
    const ms = (s) => Date.UTC(Number(s.slice(0, 4)), Number(s.slice(5, 7)) - 1, Number(s.slice(8, 10)));
    return Math.round((ms(b) - ms(a)) / DAY);
  }
  // The local date of `now`: a Date's own components, or a string's first ten characters.
  function dateOf(now) {
    if (now instanceof Date) return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
    if (typeof now === "number") return dateOf(new Date(now));
    return localDate(now == null ? isoLocal() : now);
  }
  const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;
  // "2 days old" under two weeks, "3 weeks 2 days" under eight, then "2 months 2 weeks".
  function ageText(born, now) {
    const today = dateOf(now);
    const days = Math.max(0, daysBetween(born, today));
    if (days < 14) return `${plural(days, "day")} old`;
    if (days < 56) {
      const w = Math.floor(days / 7), d = days % 7;
      return d ? `${plural(w, "week")} ${plural(d, "day")}` : plural(w, "week");
    }
    const by = Number(born.slice(0, 4)), bm = Number(born.slice(5, 7)) - 1, bd = Number(born.slice(8, 10));
    let months = (Number(today.slice(0, 4)) - by) * 12 + (Number(today.slice(5, 7)) - 1 - bm);
    const anniversary = (m) => {
      const d = new Date(Date.UTC(by, bm + m, bd));
      return `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())}`;
    };
    // A month anniversary that has not arrived yet (or rolled past a short month) is not a month.
    while (months > 0 && daysBetween(anniversary(months), today) < 0) months -= 1;
    const w = Math.floor(daysBetween(anniversary(months), today) / 7);
    return w ? `${plural(months, "month")} ${plural(w, "week")}` : plural(months, "month");
  }
  // Night is a local clock window; one that crosses midnight is t >= from || t < to.
  function isNight(now, hours) {
    const from = (hours && hours.night_from) || "21:00", to = (hours && hours.night_to) || "07:00";
    const t = now instanceof Date || typeof now === "number" ? isoLocal(new Date(toMs(now))).slice(11, 16)
      : String(now).slice(11, 16);
    return from <= to ? t >= from && t < to : t >= from || t < to;
  }
  // "17:50" — the wall clock the writer saw, straight from the string.
  const fmtTime = (iso) => String(iso).slice(11, 16);
  // "Wed 23 Sep" from the string's own date, so the day never shifts with the viewer's zone.
  function fmtDay(iso) {
    const s = String(iso);
    const y = Number(s.slice(0, 4)), m = Number(s.slice(5, 7)) - 1, d = Number(s.slice(8, 10));
    const dt = new Date(Date.UTC(y, m, d));
    if (Number.isNaN(dt.getTime())) return s.slice(0, 10);
    return `${DAYS[dt.getUTCDay()]} ${d} ${MONTHS[m]}`;
  }
  // "Wed 23 Sep 17:50".
  const fmtDateTime = (iso) => `${fmtDay(iso)} ${fmtTime(iso)}`;
  // 1-based day of life for the day-sheet heading.
  const dayNumber = (born, iso) => daysBetween(born, localDate(iso)) + 1;

  // -- one-line descriptions -----------------------------------------------------------------

  const label = (s) => String(s).replace(/_/g, " ");
  const kg = (g) => `${Math.round(g / 10) / 100} kg`;
  // The one-line summary every list shows: "5 min + 22 ml formula", "Wet + dirty · yellow" ...
  function describe(ev, unit) {
    const data = (ev && ev.data) || {};
    const now = new Date();
    switch (ev && ev.type) {
      case "feed": {
        const parts = [];
        const s = breastSeconds(ev, now);
        if (s > 0) parts.push(`${Math.round(s / 60)} min`);
        // One figure per kind, in the order the portions were given.
        const byKind = new Map();
        for (const b of data.bottles || []) byKind.set(b.kind, (byKind.get(b.kind) || 0) + (Number(b.ml) || 0));
        for (const [k, ml] of byKind) if (ml) parts.push(`${fmtAmount(ml, unit)} ${label(k)}`);
        if (parts.length) return parts.join(" + ");
        return isRunning(ev) ? "Feeding" : "Feed";
      }
      case "diaper": {
        let text = data.wet && data.dirty ? "Wet + dirty" : data.wet ? "Wet" : data.dirty ? "Dirty" : "Diaper";
        const extra = [data.color, data.texture].filter(Boolean).map(label);
        if (data.blowout) extra.push("blowout");
        if (extra.length) text += ` · ${extra.join(", ")}`;
        return text;
      }
      case "sleep":
        if (isRunning(ev)) return `Sleeping ${sinceText(toMs(now) - toMs(ev.time))}`;
        return `Sleep ${sinceText(toMs(ev.end) - toMs(ev.time))}`;
      case "pump": {
        const ml = (data.left_ml || 0) + (data.right_ml || 0);
        return ml || data.left_ml != null || data.right_ml != null ? `Pumped ${fmtAmount(ml, unit)}` : "Pump";
      }
      case "growth": {
        const parts = [];
        if (data.weight_g != null) parts.push(`Weight ${kg(data.weight_g)}`);
        if (data.length_cm != null) parts.push(`Length ${data.length_cm} cm`);
        if (data.head_cm != null) parts.push(`Head ${data.head_cm} cm`);
        return parts.join(" · ") || "Growth";
      }
      case "health": {
        const parts = [];
        if (data.medicine) parts.push([data.medicine, data.dose].filter(Boolean).join(" "));
        if (data.temp_c != null) parts.push(`${data.temp_c} °C`);
        if (data.symptom) parts.push(data.symptom);
        return parts.join(" · ") || "Health";
      }
      case "note":
        return data.milestone ? "Milestone" : "Note";
      default:
        return String((ev && ev.type) || "Entry");
    }
  }

  return {
    TYPES, ENUMS, NAME_RE, CREATED_RE, OZ_ML,
    stamp, rand4, newId, fileName, parseName, nowIso, isoLocal, parseIso, localDate,
    defaults, validate, resolve, live, onDay, isRunning, staleTimer, lastOf, sinceText,
    usualGapMs, nextFeedAt, totals, bottleMl, breastSeconds, describe, fmtAmount, toUnit,
    fromUnit, stepMl, chipStepMl, quickAmounts, quickRange, formulaChoices, formulaOf, unusual,
    ageText, isNight, fmtTime, fmtDay, fmtDateTime, dayNumber,
  };
})();

if (typeof module !== "undefined") module.exports = Core;
