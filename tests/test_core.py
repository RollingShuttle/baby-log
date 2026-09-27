"""
test_core.py — docs/core.js, the logic both front ends share, run under Node.

    python tests/test_core.py

One Node script loads core.js, runs every case in tests/fixtures/data_cases.json (the fixture
store.py is tested against too, so the two validators cannot drift) plus the arithmetic the
screens depend on, and prints a JSON list of {name, ok, detail}. Python asserts every ok.

The script pins process.env.TZ to America/Chicago before any Date is made, so the DST case is
the same on every machine. It skips with a message when no Node exists; a few static checks on
the source run without one.
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

CORE = ROOT / "docs" / "core.js"
FIXTURE = HERE / "fixtures" / "data_cases.json"


def source():
    return CORE.read_text(encoding="utf-8")


def code():
    """core.js with its comments stripped: the rules below are about what the code does."""
    src = re.sub(r"/\*.*?\*/", " ", source(), flags=re.DOTALL)
    return re.sub(r"^\s*//.*$", " ", src, flags=re.MULTILINE)


class TestSource(unittest.TestCase):
    """What can be checked without running it."""

    def test_it_exports_for_node_and_only_for_node(self):
        src = source().rstrip()
        self.assertTrue(src.endswith('if (typeof module !== "undefined") module.exports = Core;'))
        self.assertIn("const Core = (() => {", src)

    def test_nothing_node_14_cannot_run(self):
        """The Adobe copies are v14 and v16; Safari is the other target."""
        src = code()
        for bad in ("??=", ".at(", "structuredClone", "await "):
            self.assertNotIn(bad, src, f"{bad} is not available in every target runtime")

    def test_crypto_falls_back_to_the_node_module(self):
        src = code()
        self.assertIn("globalThis.crypto", src)
        self.assertIn('require("crypto")', src)
        self.assertIn(".webcrypto", src)

    def test_every_spec_function_is_exported(self):
        names = ["stamp", "rand4", "newId", "fileName", "parseName", "nowIso", "isoLocal",
                 "parseIso", "localDate", "defaults", "validate", "resolve", "live", "onDay",
                 "isRunning", "staleTimer", "lastOf", "sinceText", "usualGapMs", "nextFeedAt",
                 "totals", "bottleMl", "breastSeconds", "describe", "fmtAmount", "toUnit",
                 "fromUnit", "stepMl", "chipStepMl", "quickAmounts", "quickRange",
                 "formulaChoices", "formulaOf", "unusual", "ageText", "isNight", "fmtTime",
                 "fmtDay", "fmtDateTime", "dayNumber"]
        src = code()
        block = src[src.rindex("return {"):]
        for name in names:
            self.assertRegex(block, r"\b%s\b" % name, f"Core.{name} is not exported")


SCRIPT = r"""
process.env.TZ = "America/Chicago";
const Core = require(%(core)s);
const F = %(fixture)s;
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
const same = (a, b) => canon(a) === canon(b);
function t(name, fn) {
  try {
    const r = fn();
    if (r === true) out.push({ name, ok: true, detail: "" });
    else if (r && r.skipped) out.push({ name, ok: true, skipped: true, detail: r.skipped });
    else out.push({ name, ok: false, detail: String(r) });
  } catch (e) { out.push({ name, ok: false, detail: "threw " + (e && e.stack || e) }); }
}
const eq = (got, want) => same(got, want) ? true : "got " + canon(got) + " want " + canon(want);
const throws = (fn) => { try { fn(); return "did not throw"; } catch (e) { return e instanceof Error ? true : "threw a non-Error"; } };

// -- the shared fixture ------------------------------------------------------------------
t("defaults equal the fixture", () => {
  for (const type of Object.keys(F.defaults)) {
    const r = eq(Core.defaults(type), F.defaults[type]);
    if (r !== true) return type + ": " + r;
  }
  return true;
});
t("defaults are fresh copies", () => {
  const a = Core.defaults("feed"); a.breast.left_s = 5; a.bottles.push(1);
  return eq(Core.defaults("feed"), F.defaults.feed);
});
for (const c of F.accept) {
  t("accept: " + c.name, () => {
    const before = canon(c.data);
    const r = eq(Core.validate(c.type, c.data), c.expect);
    if (r !== true) return r;
    return canon(c.data) === before ? true : "input was mutated";
  });
}
for (const c of F.reject) {
  t("reject: " + c.name, () => {
    const data = JSON.parse(JSON.stringify(c.data));
    if (data && data.minutes === "Infinity") data.minutes = Infinity;   // the fixture's note
    return throws(() => Core.validate(c.type, data));
  });
}
t("validate rejects a non-object", () => throws(() => Core.validate("note", "x")));
for (const iso of F.times.accept) {
  t("parseIso accepts " + iso, () => Core.parseIso(iso) instanceof Date && !isNaN(Core.parseIso(iso).getTime()) ? true : "returned " + Core.parseIso(iso));
}
for (const iso of F.times.reject) {
  t("parseIso rejects " + JSON.stringify(iso), () => Core.parseIso(iso) === null ? true : "returned " + Core.parseIso(iso));
}
t("parseIso rejects an impossible date", () => Core.parseIso("2026-02-30T00:00:00-05:00") === null && Core.parseIso("2026-09-23T24:00:00-05:00") === null ? true : "accepted");
t("parseIso gives the right instant", () => eq(Core.parseIso("2026-09-23T17:50:00-05:00").getTime(), Date.UTC(2026, 8, 23, 22, 50)));
const CREATED = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}\+00:00$/;
for (const s of F.created_at.accept) t("created_at shape accepts " + s, () => CREATED.test(s) && Core.CREATED_RE.test(s) ? true : "rejected");
for (const s of F.created_at.reject) t("created_at shape rejects " + s, () => !CREATED.test(s) && !Core.CREATED_RE.test(s) ? true : "accepted");
t("nowIso has the created_at shape", () => CREATED.test(Core.nowIso()) ? true : Core.nowIso());
for (const c of F.names.accept) t("parseName " + c.name, () => eq(Core.parseName(c.name), { id: c.id, rev: c.rev, w: c.w }));
for (const n of F.names.reject) t("parseName rejects " + n, () => Core.parseName(n) === null ? true : "parsed " + canon(Core.parseName(n)));
for (const c of F.resolve.cases) {
  t("resolve: " + c.name, () => {
    const m = Core.resolve(c.records);
    if (!(m instanceof Map)) return "not a Map";
    const w = m.get("X");
    if (!w || w._file !== c.winner) return "picked " + (w && w._file);
    if (c.live_count !== undefined && Core.live(c.records).length !== c.live_count) return "live gave " + Core.live(c.records).length;
    return true;
  });
  t("resolve order-independent: " + c.name, () => {
    const w = Core.resolve(c.records.slice().reverse()).get("X");
    return w && w._file === c.winner ? true : "picked " + (w && w._file);
  });
}

// -- core_examples ---------------------------------------------------------------------------
const X = F.core_examples;
for (const c of X.describe) t("describe " + c.text, () => eq(Core.describe(c.ev, c.unit), c.text));
for (const c of X.stepMl) t("stepMl " + canon(c.recent).slice(0, 20), () => eq(Core.stepMl(c.recent, c.unit), c.ml));
for (const c of X.chipStepMl) t("chipStepMl " + canon(c.recent).slice(0, 20), () => eq(Core.chipStepMl(c.recent, c.unit), c.ml));
for (const c of X.quickAmounts) t("quickAmounts " + canon(c.values), () => eq(Core.quickAmounts(c.recent, c.unit, c.custom), c.values));
for (const c of X.quickRange) t("quickRange " + c.from + "-" + c.to + "/" + c.step, () => eq(Core.quickRange(c.from, c.to, c.step), c.values));
for (const c of X.formulaChoices) t("formulaChoices " + canon(c.values), () => eq(Core.formulaChoices(c.recentFormulas), c.values));
for (const c of X.unusual) t("unusual " + c.ml, () => eq(Core.unusual(c.ml, c.recent), c.result));
for (const c of X.ageText) t("ageText " + c.text, () => eq(Core.ageText(c.born, c.now), c.text));
for (const c of X.sinceText) t("sinceText " + c.text, () => eq(Core.sinceText(c.ms), c.text));
for (const c of X.isNight) t("isNight " + c.now + " " + c.from + "-" + c.to, () => eq(Core.isNight(c.now, { night_from: c.from, night_to: c.to }), c.result));
for (const c of X.fmt) {
  t("fmtTime", () => eq(Core.fmtTime(c.iso), c.fmtTime));
  t("fmtDay", () => eq(Core.fmtDay(c.iso), c.fmtDay));
  t("fmtDateTime", () => eq(Core.fmtDateTime(c.iso), c.fmtDateTime));
  t("localDate", () => eq(Core.localDate(c.iso), c.localDate));
}
for (const c of X.fmtAmount) t("fmtAmount " + c.text, () => eq(Core.fmtAmount(c.ml, c.unit), c.text));
for (const c of X.fromUnit) t("fromUnit " + c.v + " " + c.unit, () => eq(Core.fromUnit(c.v, c.unit), c.ml));

// -- ids and names -----------------------------------------------------------------------------
t("stamp is UTC", () => eq(Core.stamp(new Date(Date.UTC(2026, 8, 23, 22, 50, 12))), "20260923-225012"));
t("rand4 is four lowercase hex and varies", () => {
  const seen = new Set();
  for (let i = 0; i < 20; i++) { const r = Core.rand4(); if (!/^[0-9a-f]{4}$/.test(r)) return r; seen.add(r); }
  return seen.size > 1 ? true : "20 calls gave one value";
});
t("newId shape", () => /^E-\d{8}-\d{6}-[0-9a-f]{4}$/.test(Core.newId("E")) ? true : Core.newId("E"));
t("newId takes a date", () => Core.newId("C", new Date(Date.UTC(2026, 8, 23, 22, 0, 0))).startsWith("C-20260923-220000-") ? true : "wrong stamp");
t("fileName round-trips through parseName", () => {
  const id = Core.newId("E"), name = Core.fileName(id, 3), p = Core.parseName(name);
  return p && p.id === id && p.rev === 3 && /^[0-9a-f]{4}$/.test(p.w) ? true : name;
});
t("two fileNames for one revision differ", () => Core.fileName("E-x", 1) !== Core.fileName("E-x", 1) ? true : "same name twice");

// -- isoLocal, including the DST crossing ----------------------------------------------------
const chicago = new Date(2026, 0, 15).getTimezoneOffset() === 360 && new Date(2026, 6, 15).getTimezoneOffset() === 300;
t("isoLocal shape and offset", () => {
  const s = Core.isoLocal(new Date(2026, 8, 23, 17, 50, 0));
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}$/.test(s)) return s;
  return s.startsWith("2026-09-23T17:50:00") && Core.parseIso(s) ? true : s;
});
t("isoLocal DST: September vs November in America/Chicago", () => {
  // Node 14 on Windows ignores a TZ set after start, so there the zone is the machine's own.
  if (!chicago) return { skipped: "TZ override not honoured by this Node (" + process.version + "); DST not checked" };
  const sep = Core.isoLocal(new Date(2026, 8, 23, 17, 50, 0));
  const nov130 = Core.isoLocal(new Date(2026, 10, 1, 1, 30, 0));    // clocks go back at 02:00, so still CDT
  const nov300 = Core.isoLocal(new Date(2026, 10, 1, 3, 0, 0));     // after the change: CST
  const nov15 = Core.isoLocal(new Date(2026, 10, 15, 17, 50, 0));
  if (sep !== "2026-09-23T17:50:00-05:00") return "sep " + sep;
  if (nov130 !== "2026-11-01T01:30:00-05:00") return "nov 01:30 " + nov130;
  if (nov300 !== "2026-11-01T03:00:00-06:00") return "nov 03:00 " + nov300;
  if (nov15 !== "2026-11-15T17:50:00-06:00") return "nov 15 " + nov15;
  return sep.slice(-6) !== nov300.slice(-6) ? true : "offsets did not differ";
});
t("isoLocal defaults to now and parses back", () => Core.parseIso(Core.isoLocal()) ? true : Core.isoLocal());

// -- events for the arithmetic below ---------------------------------------------------------
const ev = (o) => Object.assign({ event_id: "E-" + Math.random().toString(16).slice(2, 10), revision: 1, deleted: false, end: null, note: "", data: {} }, o);
const feed = (id, time, end, breast, bottles, timer) => ev({ event_id: id, type: "feed", time, end,
  data: Core.validate("feed", { breast: breast || {}, bottles: bottles || [], timer: timer || null }) });
const NOW = "2026-09-23T18:00:00-05:00";
const T = { side: "left", side_started: "2026-09-23T17:55:00-05:00" };
const day = [
  feed("E-f1", "2026-09-23T08:00:00-05:00", "2026-09-23T08:10:00-05:00", { total_s: 600 }, [{ kind: "formula", ml: 30 }]),
  feed("E-f2", "2026-09-23T11:00:00-05:00", "2026-09-23T11:12:00-05:00", { left_s: 300, right_s: 420, total_s: 720 }),
  feed("E-f3", "2026-09-23T14:00:00-05:00", "2026-09-23T14:05:00-05:00", {}, [{ kind: "breast_milk", ml: 40 }, { kind: "formula", ml: 20 }]),
  feed("E-f4", "2026-09-23T17:50:00-05:00", null, { left_s: 300, right_s: null, total_s: 300, last_side: "left" }, [],
       { side: "right", side_started: "2026-09-23T17:55:00-05:00" }),
  ev({ event_id: "E-d1", type: "diaper", time: "2026-09-23T09:00:00-05:00", data: Core.validate("diaper", { wet: true }) }),
  ev({ event_id: "E-d2", type: "diaper", time: "2026-09-23T12:00:00-05:00", data: Core.validate("diaper", { wet: true, dirty: true, color: "yellow" }) }),
  ev({ event_id: "E-d3", type: "diaper", time: "2026-09-22T23:30:00-05:00", data: Core.validate("diaper", { dirty: true }) }),
  ev({ event_id: "E-s1", type: "sleep", time: "2026-09-23T13:00:00-05:00", end: "2026-09-23T14:20:00-05:00", data: Core.validate("sleep", {}) }),
  ev({ event_id: "E-s2", type: "sleep", time: "2026-09-23T17:00:00-05:00", end: null, data: Core.validate("sleep", { timer: { running: true } }) }),
  ev({ event_id: "E-s3", type: "sleep", time: "2026-09-22T22:00:00-05:00", end: "2026-09-23T01:00:00-05:00", data: Core.validate("sleep", {}) }),
  ev({ event_id: "E-p1", type: "pump", time: "2026-09-23T10:00:00-05:00", data: Core.validate("pump", { left_ml: 40, right_ml: 35, minutes: 20 }) }),
];

t("totals folds the running feed and sleep at now", () => eq(Core.totals(day, "2026-09-23", NOW), {
  feeds: 4, bottle_ml: 90, breast_s: 600 + 720 + 0 + (300 + 300), wet: 2, dirty: 1,
  sleeps: 2, sleep_s: 4800 + 3600, pumps: 1, pump_ml: 75 }));
t("totals counts a sleep on its start day only", () => eq(Core.totals(day, "2026-09-22", NOW), {
  feeds: 0, bottle_ml: 0, breast_s: 0, wet: 0, dirty: 1, sleeps: 1, sleep_s: 10800, pumps: 0, pump_ml: 0 }));
t("totals of an empty day are zeros", () => eq(Core.totals(day, "2026-09-21", NOW), {
  feeds: 0, bottle_ml: 0, breast_s: 0, wet: 0, dirty: 0, sleeps: 0, sleep_s: 0, pumps: 0, pump_ml: 0 }));
t("onDay slices the writer's date", () => eq(Core.onDay(day, "2026-09-22").map((e) => e.event_id).sort(), ["E-d3", "E-s3"]));
t("bottleMl sums the portions", () => eq([Core.bottleMl(day[2]), Core.bottleMl(day[1])], [60, 0]));
t("breastSeconds folds the running side", () => eq(Core.breastSeconds(day[3], NOW), 600));
t("breastSeconds uses the sides when total is null", () => eq(Core.breastSeconds(feed("E-x", NOW, NOW, { left_s: 100, right_s: 50 })), 150));
t("breastSeconds is 0 with no data", () => eq(Core.breastSeconds(feed("E-x", NOW, NOW)), 0));
t("isRunning", () => eq([Core.isRunning(day[3]), Core.isRunning(day[0]), Core.isRunning(day[8]), Core.isRunning(day[4])], [true, false, true, false]));
t("staleTimer boundaries", () => eq([
  Core.staleTimer(feed("E-x", "2026-09-23T16:59:00-05:00", null, {}, [], T), NOW),
  Core.staleTimer(feed("E-x", "2026-09-23T17:01:00-05:00", null, {}, [], T), NOW),
  Core.staleTimer(ev({ type: "sleep", time: "2026-09-23T11:59:00-05:00", end: null, data: Core.validate("sleep", { timer: { running: true } }) }), NOW),
  Core.staleTimer(ev({ type: "sleep", time: "2026-09-23T12:01:00-05:00", end: null, data: Core.validate("sleep", { timer: { running: true } }) }), NOW),
  Core.staleTimer(ev({ type: "diaper", time: "2026-09-23T01:00:00-05:00", end: null }), NOW),
  Core.staleTimer(feed("E-x", "2026-09-23T10:00:00-05:00", "2026-09-23T10:10:00-05:00"), NOW),
  Core.staleTimer(feed("E-x", "2026-09-23T08:00:00-05:00", null), NOW),   // no timer: a paper feed is not running
], [true, false, true, false, false, false, false]));
t("isRunning needs a timer, not just a missing end", () => eq(
  [Core.isRunning(feed("E-x", "2026-09-23T08:00:00-05:00", null)), Core.isRunning(feed("E-x", "2026-09-23T08:00:00-05:00", null, {}, [], T))],
  [false, true]));
t("lastOf picks the running feed", () => { const l = Core.lastOf(day, "feed", NOW); return l && l.event_id === "E-f4" ? true : canon(l); });
t("lastOf honours before", () => { const l = Core.lastOf(day, "feed", "2026-09-23T12:00:00-05:00"); return l && l.event_id === "E-f2" ? true : canon(l); });
t("lastOf is null with none", () => eq(Core.lastOf(day, "growth", NOW), null));
t("lastOf defaults to now", () => { const l = Core.lastOf(day, "diaper"); return l && l.event_id === "E-d2" ? true : canon(l); });

t("usualGapMs is null under three", () => eq(Core.usualGapMs(day.slice(0, 2), "feed"), null));
const sixFeeds = [0, 3, 5, 8, 11, 13].map((h, i) => feed("E-g" + i, Core.isoLocal(new Date(2026, 8, 23, h, 0, 0)), null));
t("usualGapMs median of six", () => eq(Core.usualGapMs(sixFeeds, "feed"), 3 * 3600000));
t("usualGapMs uses only the last n", () => eq(Core.usualGapMs(sixFeeds, "feed", 3), 2.5 * 3600000));   // 8, 11, 13 -> gaps 3 h, 2 h
t("usualGapMs ignores order", () => eq(Core.usualGapMs(sixFeeds.slice().reverse(), "feed"), 3 * 3600000));
t("usualGapMs with exactly three", () => eq(Core.usualGapMs(sixFeeds.slice(0, 3), "feed"), 2.5 * 3600000));
t("nextFeedAt is last feed plus the usual gap", () => {
  const s = Core.nextFeedAt(sixFeeds);
  if (!Core.parseIso(s)) return "not a §3.2 string: " + s;
  return eq(Core.parseIso(s).getTime(), new Date(2026, 8, 23, 16, 0, 0).getTime());
});
t("nextFeedAt is null without a gap", () => eq(Core.nextFeedAt(sixFeeds.slice(0, 2)), null));
t("nextFeedAt is null with no feeds", () => eq(Core.nextFeedAt([]), null));

// -- live ordering -------------------------------------------------------------------------------
t("live sorts by instant then id", () => {
  const recs = [
    ev({ event_id: "E-b", type: "note", time: "2026-09-23T10:00:00-05:00", created_at: "2026-09-23T15:00:00.000000+00:00", device: "pc" }),
    ev({ event_id: "E-a", type: "note", time: "2026-09-23T10:00:00-05:00", created_at: "2026-09-23T15:00:00.000000+00:00", device: "pc" }),
    ev({ event_id: "E-c", type: "note", time: "2026-09-23T15:00:00+01:00", created_at: "2026-09-23T15:00:00.000000+00:00", device: "pc" }),   // 14:00Z, an hour before the others
    ev({ event_id: "E-d", type: "note", time: "2026-09-23T11:00:00-05:00", deleted: true, created_at: "2026-09-23T15:00:00.000000+00:00", device: "pc" }),
  ];
  return eq(Core.live(recs).map((r) => r.event_id), ["E-c", "E-a", "E-b"]);
});
t("resolve with another key", () => {
  const m = Core.resolve([{ child_id: "C-1", revision: 1 }, { child_id: "C-1", revision: 2 }], "child_id");
  return m.get("C-1").revision === 2 ? true : canon(Array.from(m));
});

// -- text and amounts ------------------------------------------------------------------------------
t("sinceText floors and drops a zero tail", () => eq(
  [3659999, 3660000, 59999, 60000, 90000000, 172800000, -5000].map(Core.sinceText),
  ["1 h", "1 h 1 m", "0 m", "1 m", "1 d 1 h", "2 d", "0 m"]));
t("fmtAmount oz drops trailing zeros", () => eq([15, 30, 37, 7, 44].map((ml) => Core.fmtAmount(ml, "oz")), ["0.5 oz", "1 oz", "1.25 oz", "0.25 oz", "1.5 oz"]));
t("fmtAmount ml rounds", () => eq(Core.fmtAmount(22.4, "ml"), "22 ml"));
t("toUnit", () => eq([Core.toUnit(22, "oz"), Core.toUnit(22, "ml")], [0.74, 22]));
t("fromUnit round-trips oz steps", () => eq([0.25, 0.5, 1, 1.5].map((v) => Core.fromUnit(v, "oz")), [7, 15, 30, 44]));
t("stepMl oz tiers", () => eq([Core.stepMl([], "oz"), Core.stepMl([30, 30, 30], "oz"), Core.stepMl([60, 60, 60], "oz")], [7, 7, 15]));
t("chipStepMl empty", () => eq([Core.chipStepMl([], "ml"), Core.chipStepMl([], "oz")], [5, 7]));
t("quickAmounts all > 0 with tiny medians", () => {
  for (const recent of [[], [1], [3, 4, 5], [2, 2, 2, 2]]) {
    const q = Core.quickAmounts(recent, "ml", []);
    if (q.length !== 4) return "length " + q.length + " for " + canon(recent);
    if (!q.every((v) => v > 0)) return canon(q);
    if (!q.every((v, i) => i === 0 || v > q[i - 1])) return "not ascending " + canon(q);
  }
  const oz = Core.quickAmounts([], "oz", null);
  return oz.length === 4 && oz.every((v) => v > 0) ? true : canon(oz);
});
t("quickAmounts custom wins only when non-empty", () => eq([Core.quickAmounts([30, 21], "ml", []), Core.quickAmounts([30, 21], "ml", [50])], [[20, 25, 30, 35], [50]]));
t("unusual with two recent is false", () => eq(Core.unusual(1000, [1, 2]), false));

// -- the range chips and the formula memory (§8.1) ----------------------------------------------
t("quickRange is [] for a missing bound or step", () => eq([
  Core.quickRange(null, 100, 10), Core.quickRange(50, undefined, 10), Core.quickRange(50, 100),
  Core.quickRange(50, 100, null), Core.quickRange(NaN, 100, 10), Core.quickRange(50, "x", 10),
  Core.quickRange(50, 100, Infinity), Core.quickRange("", 100, 10), Core.quickRange(50, 100, ""),
], [[], [], [], [], [], [], [], [], []]));
t("quickRange with one value and a negative step", () => eq([Core.quickRange(70, 70, 10), Core.quickRange(50, 70, -10)], [[70], [50, 60, 70]]));
t("quickRange stops at 12 even with a reversed range", () => {
  const q = Core.quickRange(400, 60, 5);
  return q.length === 12 && q[0] === 60 && q[11] === 115 ? true : canon(q);
});
t("quickRange takes numeric strings from a settings form", () => eq(Core.quickRange("50", "80", "10"), [50, 60, 70, 80]));
t("quickRange does not include a value past `to`", () => eq(Core.quickRange(50, 75, 10), [50, 60, 70]));
t("formulaChoices skips null and empty names", () => eq(Core.formulaChoices([null, "", "Enfamil NeuroPro", undefined, "Enfamil NeuroPro"]), ["Enfamil NeuroPro"]));
t("formulaChoices starters when only nulls were recorded", () => eq([Core.formulaChoices([null, null]), Core.formulaChoices(null), Core.formulaChoices(undefined)],
  [["Similac", "Enfamil"], ["Similac", "Enfamil"], ["Similac", "Enfamil"]]));
t("formulaChoices does not mutate its input", () => { const r = ["B", "A", "B"]; Core.formulaChoices(r); return eq(r, ["B", "A", "B"]); });
t("formulaOf is the first portion's name", () => eq([
  Core.formulaOf(feed("E-x", NOW, NOW, {}, [{ kind: "formula", ml: 70, formula: "Similac Pro-Advance" }, { kind: "formula", ml: 10, formula: "Enfamil NeuroPro" }])),
  Core.formulaOf(feed("E-x", NOW, NOW, {}, [{ kind: "breast_milk", ml: 40 }, { kind: "formula", ml: 10, formula: "Enfamil NeuroPro" }])),
  Core.formulaOf(feed("E-x", NOW, NOW, {}, [{ kind: "formula", ml: 22 }])),
  Core.formulaOf(feed("E-x", NOW, NOW)),
  Core.formulaOf(ev({ type: "diaper", data: Core.validate("diaper", { wet: true }) })),
  Core.formulaOf(null),
  Core.formulaOf({ type: "feed", data: { bottles: [{ kind: "formula", ml: 5, formula: "" }] } }),   // an unvalidated record from an older file
], ["Similac Pro-Advance", null, null, null, null, null, null]));
t("validate keeps a formula name and fills null", () => eq(
  Core.validate("feed", { bottles: [{ kind: "formula", ml: 70, formula: "Enfamil NeuroPro" }, { kind: "breast_milk", ml: 30 }, { kind: "formula", ml: 10, formula: null }] }).bottles,
  [{ kind: "formula", ml: 70, formula: "Enfamil NeuroPro" }, { kind: "breast_milk", ml: 30, formula: null }, { kind: "formula", ml: 10, formula: null }]));
t("validate refuses a non-text formula", () => {
  for (const bad of [5, true, [], {}, ""]) {
    const r = throws(() => Core.validate("feed", { bottles: [{ kind: "formula", ml: 70, formula: bad }] }));
    if (r !== true) return canon(bad) + ": " + r;
  }
  return true;
});
t("describe does not name the formula", () => eq(
  Core.describe(feed("E-x", NOW, NOW, {}, [{ kind: "formula", ml: 70, formula: "Similac Pro-Advance" }]), "ml"), "70 ml formula"));

t("isNight boundaries", () => {
  const h = { night_from: "21:00", night_to: "07:00" };
  return eq([
    Core.isNight("2026-09-23T21:00:00-05:00", h), Core.isNight("2026-09-23T20:59:00-05:00", h),
    Core.isNight("2026-09-24T06:59:00-05:00", h), Core.isNight("2026-09-24T07:00:00-05:00", h),
    Core.isNight(new Date(2026, 8, 23, 23, 0, 0), h), Core.isNight(new Date(2026, 8, 23, 12, 0, 0), h),
    Core.isNight("2026-09-24T13:00:00-05:00", { night_from: "11:00", night_to: "13:00" }),
  ], [true, false, true, false, true, false, false]);
});
t("ageText singulars", () => eq([Core.ageText("2026-09-21", "2026-09-22T12:00:00-05:00"), Core.ageText("2026-09-21", "2026-09-21T12:00:00-05:00"),
  Core.ageText("2026-09-21", "2026-10-13T12:00:00-05:00")], ["1 day old", "0 days old", "3 weeks 1 day"]));
t("ageText from a Date", () => eq(Core.ageText("2026-09-21", new Date(2026, 8, 23, 19, 5)), "2 days old"));
t("ageText months just before the anniversary", () => eq(Core.ageText("2026-09-21", "2026-11-20T12:00:00-06:00"), "1 month 4 weeks"));
t("ageText born on the 31st", () => eq([
  Core.ageText("2026-01-31", "2026-05-01T12:00:00-05:00"),     // the Apr 31 anniversary rolls to May 1
  Core.ageText("2026-01-31", "2026-03-30T12:00:00-06:00"),     // Feb 31 rolls to Mar 3: 1 month + 27 days
], ["3 months", "1 month 3 weeks"]));
t("dayNumber", () => eq([Core.dayNumber("2026-09-21", "2026-09-21T10:00:00-05:00"), Core.dayNumber("2026-09-21", "2026-09-23T10:00:00-05:00")], [1, 3]));
t("fmtDay across a year boundary", () => eq([Core.fmtDay("2027-01-01T00:10:00-06:00"), Core.fmtDay("2026-12-31T23:50:00-06:00")], ["Fri 1 Jan", "Thu 31 Dec"]));

t("describe pump growth health note", () => eq([
  Core.describe(day[10], "ml"),
  Core.describe(ev({ type: "growth", data: Core.validate("growth", { weight_g: 3420 }) }), "ml"),
  Core.describe(ev({ type: "growth", data: Core.validate("growth", { weight_g: 3400, length_cm: 51 }) }), "ml"),
  Core.describe(ev({ type: "health", data: Core.validate("health", { medicine: "Vitamin D", dose: "1 drop" }) }), "ml"),
  Core.describe(ev({ type: "health", data: Core.validate("health", { temp_c: 37.2 }) }), "ml"),
  Core.describe(ev({ type: "note", data: Core.validate("note", {}) }), "ml"),
], ["Pumped 75 ml", "Weight 3.42 kg", "Weight 3.4 kg · Length 51 cm", "Vitamin D 1 drop", "37.2 °C", "Note"]));
t("describe feed in oz and bare", () => eq([
  Core.describe(X.describe[0].ev, "oz"),
  Core.describe(day[2], "ml"),
  Core.describe(feed("E-x", "2026-09-23T10:00:00-05:00", "2026-09-23T10:00:00-05:00"), "ml"),
], ["5 min + 0.75 oz formula", "40 ml breast milk + 20 ml formula", "Feed"]));
t("describe diaper variants", () => eq([
  Core.describe(ev({ type: "diaper", data: Core.validate("diaper", { wet: true }) }), "ml"),
  Core.describe(ev({ type: "diaper", data: Core.validate("diaper", { dirty: true, color: "dark_green", texture: "seedy" }) }), "ml"),
], ["Wet", "Dirty · dark green, seedy"]));

console.log(JSON.stringify(out));
"""


class TestUnderNode(unittest.TestCase):
    """Everything the screens compute, run for real."""

    def test_core_js_passes_every_case(self):
        if not _node.NODE:
            self.skipTest("no Node binary found (set BABY_LOG_NODE or install node); "
                          "core.js was not executed")
        fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
        script = SCRIPT % {"core": json.dumps(str(CORE)), "fixture": json.dumps(fixture)}
        rc, out, err = _node.run_js(script)
        self.assertEqual(rc, 0, f"node exited {rc}\n{err}\n{out}")
        lines = [ln for ln in out.splitlines() if ln.strip()]
        results = json.loads(lines[-1])
        self.assertGreater(len(results), 120, "the script ran too few cases")
        failed = [r for r in results if not r["ok"]]
        report = "\n".join(f"  {r['name']}: {r['detail']}" for r in failed)
        self.assertEqual(failed, [], f"{len(failed)} of {len(results)} cases failed:\n{report}")
        skipped = [r for r in results if r.get("skipped")]
        self.assertLess(len(skipped), 2, "only the DST case may be skipped, and only on Node 14")
        print(f"\n  {len(results) - len(skipped)} JS cases passed under {_node.NODE}", file=sys.stderr)
        for r in skipped:
            print(f"  skipped {r['name']}: {r['detail']}", file=sys.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
