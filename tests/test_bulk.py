"""
test_bulk.py — static/bulk.js, the Catch up screen's shorthand parser, run under Node.

    python tests/test_bulk.py

One Node script loads bulk.js (and docs/core.js only for Core.isoLocal, the way the page passes
it in), runs every shorthand form the contract names with a fixed `now`, and prints a JSON list
of {name, ok, detail}. Python asserts every ok. process.env.TZ is pinned to America/Chicago
before any Date is made, so the iso offsets are the same on every machine. Without Node the
runtime tests skip with a message; the static checks on the source still run.
"""

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path[:0] = [str(HERE), str(ROOT)]

import json
import re
import unittest

import _node

BULK = ROOT / "static" / "bulk.js"
CORE = ROOT / "docs" / "core.js"


def source():
    return BULK.read_text(encoding="utf-8")


def code():
    """bulk.js with its comments stripped: the rules below are about what the code does."""
    src = re.sub(r"/\*.*?\*/", " ", source(), flags=re.DOTALL)
    return re.sub(r"^\s*//.*$", " ", src, flags=re.MULTILINE)


class TestSource(unittest.TestCase):
    """What can be checked without running it."""

    def test_it_exports_for_node_and_only_for_node(self):
        src = source().rstrip()
        self.assertTrue(src.endswith('if (typeof module !== "undefined") module.exports = Bulk;'))
        self.assertIn("const Bulk = (() => {", src)

    def test_nothing_node_14_cannot_run(self):
        src = code()
        for bad in ("??=", ".at(", "structuredClone", "await ", "?."):
            self.assertNotIn(bad, src, f"{bad} is not available in every target runtime")

    def test_it_does_not_reach_for_core(self):
        """The page passes Core.isoLocal in; the file itself must stand alone under Node."""
        self.assertNotIn("Core.", code())
        self.assertNotIn("require(", code())

    def test_utf8_lf_no_bom(self):
        raw = BULK.read_bytes()
        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"), "BOM")
        self.assertNotIn(b"\r\n", raw, "CRLF line endings")

    def test_parses_under_node_check(self):
        if not _node.NODE:
            self.skipTest("no Node binary found (set BABY_LOG_NODE or install node)")
        proc = subprocess.run([_node.NODE, "--check", str(BULK)], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stderr)


SCRIPT = r"""
process.env.TZ = "America/Chicago";
const Bulk = require(%(bulk)s);
const Core = require(%(core)s);
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
    else out.push({ name, ok: false, detail: String(r) });
  } catch (e) { out.push({ name, ok: false, detail: "threw " + (e && e.stack || e) }); }
}
const eq = (got, want) => same(got, want) ? true : "got " + canon(got) + " want " + canon(want);

// 3 Nov 2026, 14:00 Chicago (CST: DST ended on the 1st). Yisen born 21 Sep 2026.
const NOW = new Date(2026, 10, 3, 14, 0, 0);
const BORN = "2026-09-21";
const OPTS = { now: NOW, born: BORN, lastFormula: "Similac", isoLocal: Core.isoLocal };
const P = (text, extra) => Bulk.parse(text, Object.assign({}, OPTS, extra || {}));
const row = (text, i, extra) => P(text, extra).rows[i == null ? 0 : i];
const one = (text, extra) => { const r = P(text, extra); return r.rows[r.rows.length - 1]; };
const pick = (r, keys) => { const o = {}; for (const k of keys) o[k] = r[k]; return o; };

// -- day headers --------------------------------------------------------------------------
for (const [text, want] of [
  ["11/02", "2026-11-02"], ["11-02", "2026-11-02"], ["11.2", "2026-11-02"],
  ["2026-11-02", "2026-11-02"], ["11月2日", "2026-11-02"], ["2026年11月2日", "2026-11-02"],
  ["11/2", "2026-11-02"], ["10/5", "2026-10-05"], ["11/03", "2026-11-03"],
]) {
  t("header " + text, () => eq(pick(row(text), ["kind", "date", "error", "hhmm", "type"]),
    { kind: "header", date: want, error: null, hhmm: null, type: null }));
}
t("header 2日 carries the previous header's month", () => {
  const r = P("10/30\n2日\n0100 w");
  return eq([r.rows[1].kind, r.rows[1].date, r.rows[2].date], ["header", "2026-10-02", "2026-10-02"]);
});
t("header 2日 with no header above uses the current month", () =>
  eq(pick(row("2日"), ["kind", "date"]), { kind: "header", date: "2026-11-02" }));
t("header 31日 after a 30-day month is not a date", () =>
  eq(pick(row("11/01\n31日", 1), ["kind", "error"]), { kind: "error", error: "not a real date: 31日" }));
t("year rule: a future month/day means last year", () =>
  eq(pick(row("12/02", 0, { born: null }), ["kind", "date"]), { kind: "header", date: "2025-12-02" }));
t("year rule: tomorrow means last year", () =>
  eq(row("11/04", 0, { born: null }).date, "2025-11-04"));
t("year rule: today is this year", () => eq(row("11/03").date, "2026-11-03"));
t("year rule: a typed year is kept even in the future", () =>
  eq(pick(row("2027-01-01", 0, { born: null }), ["kind", "date"]), { kind: "header", date: "2027-01-01" }));
t("year rule: 29 Feb last year (2025) is not a date, this year's typed is", () =>
  eq([row("2/29", 0, { born: null }).error, row("2028-02-29", 0, { born: null }).date],
    ["not a real date: 2/29", "2028-02-29"]));
t("header: an impossible month or day is an error row, not a throw", () =>
  eq([row("13/45").kind, row("13/45").error, row("11/31").error, row("0/3").error],
    ["error", "not a real date: 13/45", "not a real date: 11/31", "not a real date: 0/3"]));
t("header may carry a trailing # comment", () =>
  eq(pick(row("11/02 # Sunday"), ["kind", "date", "note"]), { kind: "header", date: "2026-11-02", note: "" }));
t("a date with anything else after it is not a header", () =>
  eq(pick(row("11/02 70"), ["kind", "error"]), { kind: "error", error: "unreadable time" }));
t("a later header replaces the date", () => {
  const r = P("11/01\n0100 w\n11/02\n0200 w");
  return eq([r.rows[1].date, r.rows[3].date], ["2026-11-01", "2026-11-02"]);
});

// -- times ---------------------------------------------------------------------------------
for (const [text, want] of [
  ["0130 w", "01:30"], ["130 w", "01:30"], ["1:30 w", "01:30"], ["01:30 w", "01:30"],
  ["1330 w", "13:30"], ["13:30 w", "13:30"], ["0000 w", "00:00"], ["2359 w", "23:59"],
  ["1:30pm w", "13:30"], ["1:30 pm w", "13:30"], ["130PM w", "13:30"], ["1:30am w", "01:30"],
  ["12:30am w", "00:30"], ["12:30 pm w", "12:30"], ["11:59 PM w", "23:59"],
  ["上午9:10 w", "09:10"], ["上午 9:10 w", "09:10"], ["下午1:30 w", "13:30"], ["下午 130 w", "13:30"],
  ["晚上9:10 w", "21:10"], ["晚上 910 w", "21:10"], ["凌晨2:00 w", "02:00"], ["凌晨 200 w", "02:00"],
  ["凌晨12:30 w", "00:30"], ["晚上12:30 w", "00:30"], ["下午12:30 w", "12:30"], ["早上7:00 w", "07:00"],
]) {
  t("time " + text, () => eq(pick(row("11/02\n" + text, 1), ["kind", "hhmm", "error"]),
    { kind: "entry", hhmm: want, error: null }));
}
for (const text of ["2530 w", "1260 w", "13:30am w", "9 w", "12345 w", "1:5 w", "abc w", "w 0130"]) {
  t("unreadable time " + text, () => eq(pick(row("11/02\n" + text, 1), ["kind", "error"]),
    { kind: "error", error: "unreadable time" }));
}
t("time becomes the §3.2 iso string through opts.isoLocal (CST in November)", () =>
  eq(row("11/02\n0130 w", 1).time, "2026-11-02T01:30:00-06:00"));
t("time keeps the offset of its own date (CDT in October)", () =>
  eq(row("10/02\n1330 w", 1).time, "2026-10-02T13:30:00-05:00"));
t("without opts.isoLocal the fallback writes the same shape", () =>
  eq(row("11/02\n0130 w", 1, { isoLocal: undefined }).time, "2026-11-02T01:30:00-06:00"));

// -- feeds ---------------------------------------------------------------------------------
const feedData = (ml, formula) => ({ bottles: [{ kind: "formula", ml, formula }] });
for (const [text, ml, formula] of [
  ["0200 70", 70, "Similac"], ["0200 70ml", 70, "Similac"], ["0200 70 ml", 70, "Similac"],
  ["0200 70ML", 70, "Similac"], ["0200 奶70", 70, "Similac"], ["0200 奶 70", 70, "Similac"],
  ["0200 70毫升", 70, "Similac"], ["0200 120", 120, "Similac"],
  ["0200 70 enfamil", 70, "Enfamil"], ["0200 70 Enfamil", 70, "Enfamil"],
  ["0200 70 similac pro-advance", 70, "Similac Pro-advance"],
  ["0200 70ml Enfamil NeuroPro", 70, "Enfamil NeuroPro"], ["0200 70 ml  Enfamil   NeuroPro", 70, "Enfamil NeuroPro"],
  ["0200 奶80 美赞臣", 80, "美赞臣"], ["0200 70.4", 70, "Similac"], ["0200 70.6", 71, "Similac"],
]) {
  t("feed " + text, () => eq(pick(row("11/02\n" + text, 1), ["kind", "type", "data", "error"]),
    { kind: "entry", type: "feed", data: feedData(ml, formula), error: null }));
}
t("feed with no formula known is null", () =>
  eq(row("11/02\n0200 70", 1, { lastFormula: null }).data, feedData(70, null)));
t("feed with no formula known but one typed keeps it", () =>
  eq(row("11/02\n0200 70 Enfamil", 1, { lastFormula: null }).data, feedData(70, "Enfamil")));
t("a typed formula carries to the lines below it", () => {
  const r = P("11/02\n0100 70\n0200 70 Enfamil\n0300 80\n0400 90 Similac\n0500 60");
  return eq(r.rows.slice(1).map((x) => x.data.bottles[0].formula),
    ["Similac", "Enfamil", "Enfamil", "Similac", "Similac"]);
});
t("feed of 0 ml is an error", () =>
  eq(pick(row("11/02\n0200 0", 1), ["kind", "error"]), { kind: "error", error: "amount must be more than 0 ml" }));
t("a bare time is an error", () =>
  eq(pick(row("11/02\n0200", 1), ["kind", "error"]), { kind: "error", error: "nothing after the time" }));

// -- diapers -------------------------------------------------------------------------------
const diaper = (wet, dirty) => ({ wet, dirty });
for (const [text, want] of [
  ["w", diaper(true, false)], ["wet", diaper(true, false)], ["尿", diaper(true, false)], ["W", diaper(true, false)],
  ["d", diaper(false, true)], ["dirty", diaper(false, true)], ["p", diaper(false, true)], ["poo", diaper(false, true)],
  ["屎", diaper(false, true)], ["便", diaper(false, true)], ["大便", diaper(false, true)], ["Dirty", diaper(false, true)],
  ["wd", diaper(true, true)], ["dw", diaper(true, true)], ["both", diaper(true, true)], ["尿屎", diaper(true, true)],
  ["屎尿", diaper(true, true)], ["都有", diaper(true, true)], ["WD", diaper(true, true)], ["Both", diaper(true, true)],
]) {
  t("diaper " + text, () => eq(pick(row("11/02\n0300 " + text, 1), ["kind", "type", "data", "error"]),
    { kind: "entry", type: "diaper", data: want, error: null }));
}
t("diaper with extra words is an unreadable entry", () =>
  eq(pick(row("11/02\n0300 w big", 1), ["kind", "error"]), { kind: "error", error: "unreadable entry: w big" }));
t("unreadable what", () =>
  eq(pick(row("11/02\n0300 xyz", 1), ["kind", "hhmm", "error"]), { kind: "error", hhmm: "03:00", error: "unreadable entry: xyz" }));

// -- notes, comments, blanks ---------------------------------------------------------------
t("note after # on a feed", () =>
  eq(pick(row("11/02\n0200 70 # slow feed", 1), ["note", "data"]), { note: "slow feed", data: feedData(70, "Similac") }));
t("note after # with a formula name before it", () =>
  eq(pick(row("11/02\n0200 70 enfamil #spit up", 1), ["note", "data"]), { note: "spit up", data: feedData(70, "Enfamil") }));
t("note after # on a diaper", () =>
  eq(pick(row("11/02\n0300 wd #big one", 1), ["note", "data"]), { note: "big one", data: diaper(true, true) }));
t("note keeps its own # characters and CJK", () =>
  eq(row("11/02\n0300 w # 第1次 #2", 1).note, "第1次 #2"));
t("no note is an empty string, never null", () =>
  eq([row("11/02\n0300 w", 1).note, row("11/02", 0).note, row("", 0).note], ["", "", ""]));
t("blank lines and # comments are ignored and not counted", () => {
  const r = P("# the slips from the kitchen\n\n11/02\n   \n0100 w\n# lunch\n\t\n");
  return eq([r.rows.map((x) => x.kind), r.counts.entries, r.counts.errors],
    [["ignore", "ignore", "header", "ignore", "entry", "ignore", "ignore", "ignore"], 1, 0]);
});
t("a comment line does not reset the date", () =>
  eq(row("11/02\n# x\n0100 w", 2).date, "2026-11-02"));

// -- the five error kinds ------------------------------------------------------------------
t("error: entry before any day header", () =>
  eq(pick(row("0130 w"), ["kind", "date", "hhmm", "error"]), { kind: "error", date: null, hhmm: "01:30", error: "no date above this line" }));
t("error: unreadable time", () => eq(row("11/02\nhalf past one w", 1).error, "unreadable time"));
t("error: unreadable what", () => eq(row("11/02\n0130 bath", 1).error, "unreadable entry: bath"));
t("error: later than now + 10 min on today's date", () => {
  const r = P("11/03\n1409 w\n1410 w\n1411 w");
  return eq(r.rows.slice(1).map((x) => [x.kind, x.error]),
    [["entry", null], ["entry", null], ["error", "later than now"]]);
});
t("error: the same clock time on an earlier day is fine", () => eq(row("11/02\n2359 w", 1).error, null));
t("error: a date before the child's birth, and the lines under it", () => {
  const r = P("09/01\n0100 w\n0200 70");
  return eq(r.rows.map((x) => [x.kind, x.error]), [
    ["error", "2026-09-01 is before the child's birth (2026-09-21)"],
    ["error", "no date above this line"], ["error", "no date above this line"]]);
});
t("the birth day itself is allowed", () => eq(pick(row("09/21"), ["kind", "date"]), { kind: "header", date: "2026-09-21" }));
t("no born means no birth check", () => eq(row("09/01", 0, { born: null }).date, "2026-09-01"));
t("a bad header unsets the date for the lines below", () =>
  eq(row("11/02\n13/45\n0100 w", 2).error, "no date above this line"));
t("error rows still carry what was read", () =>
  eq(pick(row("11/02\n0300 xyz # n", 1), ["line", "date", "hhmm", "note", "text", "type", "data", "time"]),
    { line: 2, date: "2026-11-02", hhmm: "03:00", note: "n", text: "0300 xyz # n", type: null, data: null, time: null }));
t("nothing throws: null, undefined, a number, no opts", () =>
  eq([Bulk.parse(null).rows.length, Bulk.parse(undefined).rows.length, Bulk.parse(123).rows[0].kind, Bulk.parse("11/02").rows[0].kind],
    [1, 1, "error", "header"]));

// -- counts, days, row shape ---------------------------------------------------------------
const DOC = [
  "# October slips", "10/30", "0130 70 Enfamil", "0300 w", "0345 d", "0500 wd", "", "2日",
  "0100 80", "0200 w # small", "9999 w", "0300 wd", "11/01", "0100 70", "0200 p", "0300 xyz",
].join("\n");
t("counts", () => eq(P(DOC).counts, { feeds: 3, wet: 2, dirty: 2, both: 2, errors: 2, entries: 9 }));
t("entries = feeds + wet + dirty + both", () => {
  const c = P(DOC).counts;
  return eq(c.entries, c.feeds + c.wet + c.dirty + c.both);
});
t("days are sorted and distinct, from the entries (2日 under 10/30 is October)", () =>
  eq(P(DOC).days, ["2026-10-02", "2026-10-30", "2026-11-01"]));
t("days omit a header with no entries under it", () => eq(P("11/01\n11/02\n0100 w").days, ["2026-11-02"]));
t("a trailing newline is one empty ignored row", () => eq(P("11/02\n0100 w\n").rows.map((x) => x.kind), ["header", "entry", "ignore"]));
t("one row per line, 1-based, original text kept, CRLF split", () => {
  const r = P("11/02\r\n0100 w\r\n\r\n0200 70");
  return eq(r.rows.map((x) => [x.line, x.text]), [[1, "11/02"], [2, "0100 w"], [3, ""], [4, "0200 70"]]);
});
t("row shape: exactly the contract's keys", () => {
  const keys = ["line", "kind", "date", "hhmm", "type", "data", "note", "time", "text", "error"].sort();
  const r = P(DOC);
  for (const x of r.rows) if (canon(Object.keys(x).sort()) !== canon(keys)) return "row " + x.line + " has " + Object.keys(x);
  return true;
});
t("an entry row in full", () => eq(row("11/02\n下午1:30 70 Enfamil # ok", 1), {
  line: 2, kind: "entry", date: "2026-11-02", hhmm: "13:30", type: "feed",
  data: feedData(70, "Enfamil"), note: "ok", time: "2026-11-02T13:30:00-06:00",
  text: "下午1:30 70 Enfamil # ok", error: null }));
t("a header row in full", () => eq(row("11月2日"), {
  line: 1, kind: "header", date: "2026-11-02", hhmm: null, type: null, data: null, note: "",
  time: null, text: "11月2日", error: null }));
t("feed data validates with Core", () => {
  const r = row("11/02\n0200 70 Enfamil", 1);
  const v = Core.validate("feed", r.data);
  return eq(v.bottles, r.data.bottles);
});
t("diaper data validates with Core", () => {
  const v = Core.validate("diaper", row("11/02\n0200 wd", 1).data);
  return eq([v.wet, v.dirty], [true, true]);
});
t("the time round-trips through Core.parseIso", () =>
  eq(Core.parseIso(row("11/02\n0200 w", 1).time).getTime(), new Date(2026, 10, 2, 2, 0, 0).getTime()));
t("about a month of slips parses quickly", () => {
  const lines = [];
  for (let d = 1; d <= 30; d++) {
    lines.push("10/" + d);
    for (let h = 0; h < 24; h++) lines.push(String(h).padStart(2, "0") + "00 " + (h %% 2 ? "70" : "w"));
  }
  const t0 = Date.now();
  const r = P(lines.join("\n"));
  const ms = Date.now() - t0;
  if (r.counts.entries !== 720 || r.counts.errors !== 0 || r.days.length !== 30) return canon(r.counts);
  return ms < 2000 ? true : "took " + ms + " ms";
});

// -- describe ------------------------------------------------------------------------------
t("describe feed with formula", () => eq(Bulk.describe(row("11/02\n0200 70 Enfamil", 1), "ml"), "70 ml formula · Enfamil"));
t("describe feed with the last formula", () => eq(Bulk.describe(row("11/02\n0200 70", 1), "ml"), "70 ml formula · Similac"));
t("a typed name takes the spelling already on file", () =>
  eq(row("11/02\n0200 70 enfamil", 1, { lastFormula: "Similac", formulas: ["Enfamil"] }).data, feedData(70, "Enfamil")));
t("a typed name matching the last formula keeps its spelling", () =>
  eq(row("11/02\n0200 70 SIMILAC", 1, { lastFormula: "Similac" }).data, feedData(70, "Similac")));
t("an unknown name gets its initials capitalised", () =>
  eq(row("11/02\n0200 70 kendamil organic", 1, { lastFormula: null }).data, feedData(70, "Kendamil Organic")));
t("the canonical spelling carries to the lines below", () =>
  eq(row("11/02\n0200 70 enfamil\n0300 80", 2, { lastFormula: null, formulas: ["Enfamil"] }).data, feedData(80, "Enfamil")));
t("describe feed with no formula", () => eq(Bulk.describe(row("11/02\n0200 70", 1, { lastFormula: null }), "ml"), "70 ml formula"));
t("describe feed in oz rounds to the quarter like Core", () =>
  eq(Bulk.describe(row("11/02\n0200 74 Enfamil", 1), "oz"), "2.5 oz formula · Enfamil"));
t("describe diapers", () => eq(
  ["w", "d", "wd"].map((x) => Bulk.describe(row("11/02\n0200 " + x, 1), "ml")),
  ["Wet", "Dirty", "Wet + dirty"]));
t("describe header, ignore, error and nothing", () => eq(
  [Bulk.describe(row("11/02"), "ml"), Bulk.describe(row(""), "ml"), Bulk.describe(row("0100 w"), "ml"), Bulk.describe(null, "ml")],
  ["2026-11-02", "", "", ""]));
t("describe agrees with Core.describe for the same data", () => {
  const r = row("11/02\n0200 70 Enfamil", 1);
  const core = Core.describe({ type: "feed", time: r.time, end: null, data: Core.validate("feed", r.data) }, "ml");
  return eq(Bulk.describe(r, "ml").slice(0, core.length), core);
});

console.log(JSON.stringify(out));
"""


class TestUnderNode(unittest.TestCase):
    """Every shorthand form, run for real."""

    def test_bulk_js_passes_every_case(self):
        if not _node.NODE:
            self.skipTest("no Node binary found (set BABY_LOG_NODE or install node); "
                          "bulk.js was not executed")
        script = SCRIPT % {"bulk": json.dumps(str(BULK)), "core": json.dumps(str(CORE))}
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
