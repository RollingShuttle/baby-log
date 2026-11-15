"""tools/growth_standard.py and static/growth.js — the weight-for-age standard (WS/T 423-2022) and
the arithmetic of the growth charts. The JSON is checked against rows copied by hand from the
official PDF; the shared fixture is checked against the Python reference and, under Node, against
static/growth.js. Standalone or under discovery."""
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "tools"))
import _node  # noqa: E402
import growth_standard as gs  # noqa: E402

STD = gs.load()
FIXTURE = json.loads(gs.FIXTURE.read_text(encoding="utf-8"))["cases"]
GROWTH_JS = ROOT / "static" / "growth.js"

# Rows read off the official PDF (tables A.1, A.2, B.1, B.2), typed in separately from the parser.
OFFICIAL = {
    ("boy", "p", 0): [2.8, 3.0, 3.2, 3.5, 3.7, 4.0, 4.2],
    ("boy", "p", 1): [3.7, 3.9, 4.2, 4.6, 4.9, 5.2, 5.6],
    ("boy", "p", 7): [7.2, 7.7, 8.2, 8.8, 9.5, 10.1, 10.8],
    ("boy", "p", 12): [8.3, 8.8, 9.4, 10.1, 10.8, 11.5, 12.3],
    ("boy", "p", 22): [10.0, 10.6, 11.3, 12.2, 13.0, 13.9, 14.8],
    ("boy", "p", 24): [10.4, 11.0, 11.7, 12.6, 13.5, 14.4, 15.4],
    ("boy", "p", 27): [10.8, 11.5, 12.2, 13.1, 14.1, 15.1, 16.1],
    ("boy", "p", 72): [17.1, 18.3, 19.8, 21.6, 23.6, 25.7, 27.9],
    ("boy", "p", 81): [18.2, 19.7, 21.3, 23.4, 25.7, 28.0, 30.6],
    ("boy", "sd", 0): [2.4, 2.7, 3.1, 3.5, 3.9, 4.3, 4.7],
    ("boy", "sd", 1): [3.2, 3.6, 4.1, 4.6, 5.1, 5.6, 6.2],
    ("boy", "sd", 2): [4.1, 4.6, 5.2, 5.8, 6.5, 7.2, 8.0],
    ("boy", "sd", 22): [9.0, 9.9, 11.0, 12.2, 13.5, 15.0, 16.8],
    ("boy", "sd", 63): [13.9, 15.6, 17.5, 19.7, 22.3, 25.5, 29.3],
    ("girl", "p", 0): [2.7, 2.9, 3.1, 3.3, 3.6, 3.8, 4.1],
    ("girl", "p", 1): [3.5, 3.7, 4.0, 4.3, 4.6, 4.9, 5.3],
    ("girl", "p", 10): [7.4, 7.8, 8.3, 9.0, 9.6, 10.3, 11.1],
    ("girl", "p", 12): [7.7, 8.2, 8.8, 9.4, 10.1, 10.9, 11.6],
    ("girl", "sd", 0): [2.3, 2.6, 3.0, 3.3, 3.7, 4.1, 4.6],
    ("girl", "sd", 2): [3.8, 4.3, 4.8, 5.4, 6.0, 6.7, 7.4],
}


class TestStandard(unittest.TestCase):
    def test_rows_match_the_official_pdf(self):
        for (sex, key, age), row in OFFICIAL.items():
            t = STD[sex]
            self.assertEqual(t[key][t["ages"].index(age)], row, (sex, key, age))

    def test_shape(self):
        gs.check(STD)       # raises on any break: ages 0..81, rising columns, medians agree
        self.assertEqual(STD["percentiles"], [3, 10, 25, 50, 75, 90, 97])
        self.assertEqual(STD["sds"], [-3, -2, -1, 0, 1, 2, 3])
        self.assertEqual(STD["boy"]["ages"][24:], [24, 27, 30, 33, 36, 39, 42, 45, 48, 51, 54, 57,
                                                   60, 63, 66, 69, 72, 75, 78, 81])

    def test_the_writer_round_trips(self):
        text = gs.JSON_PATH.read_text(encoding="utf-8")
        self.assertEqual(gs.dumps(STD), text)

    def test_iphone_copy_is_byte_identical(self):
        self.assertEqual(gs.IOS_PATH.read_bytes(), gs.JSON_PATH.read_bytes())

    def test_files_are_utf8_lf(self):
        for p in (gs.JSON_PATH, gs.FIXTURE, Path(gs.__file__)):
            raw = p.read_bytes()
            self.assertNotIn(b"\r\n", raw, p)
            self.assertFalse(raw.startswith(b"\xef\xbb\xbf"), p)


class TestArithmetic(unittest.TestCase):
    def test_fixture_is_current(self):
        self.assertEqual(gs.cases(STD), FIXTURE, "run: python tools/growth_standard.py --fixture")

    def test_on_a_row_the_sd_columns_are_exact(self):
        for i, kg in enumerate(STD["boy"]["sd"][12]):
            self.assertAlmostEqual(gs.z_score(STD, "boy", 12.0, kg), i - 3, places=9)

    def test_between_rows_is_linear(self):
        med = gs.row_at(STD["boy"]["sd"], STD["boy"]["ages"], 25.5)[3]
        self.assertAlmostEqual(med, (12.6 + 13.1) / 2, places=9)

    def test_outside_the_table(self):
        self.assertIsNone(gs.age_months("2026-09-21", "2026-09-20"))
        self.assertIsNone(gs.z_score(STD, "boy", 81.01, 20.0))
        self.assertIsNone(gs.z_score(STD, "", 3.0, 6.0))
        self.assertIsNone(gs.z_score(STD, None, 3.0, 6.0))

    def test_labels_and_bands(self):
        self.assertEqual([gs.pct_label(x) for x in (0.4, 1.0, 22.5, 98.9, 99.0, 99.2)],
                         ["<1", "1", "22", "98", "99", ">99"])
        self.assertEqual([gs.band(x) for x in (2.9, 3, 24.9, 25, 74.9, 75, 96.9, 97)],
                         ["lower", "below", "below", "average", "average", "above", "above", "upper"])

    def test_the_number_shown_is_in_the_band_shown(self):
        # A label rounded up onto a threshold read "percentile 3 · Lower" (review, Nov 2026).
        self.assertEqual([gs.pct_label(x) for x in (2.527, 24.999, 74.95, 96.61)], ["2", "24", "74", "96"])
        for i in range(100, 9901):
            pc = i / 100
            self.assertEqual(gs.band(float(gs.pct_label(pc))), gs.band(pc), pc)
        near = [c for c in FIXTURE if c["percentile"] is not None and c["percentile"] % 1 > 0.5
                and int(c["percentile"]) + 1 in (3, 25, 75, 97)]
        self.assertEqual(len(near), 4, "keep a fixture case just under each band threshold")
        for c in near:
            self.assertEqual(gs.band(float(c["label"])), c["band"], c)

    def test_yisen_so_far(self):
        # The four weights on file when this was built: birth P17, then about the median.
        got = [c["label"] for c in FIXTURE[:4]]
        self.assertEqual(got, ["17", "48", "46", "54"])


NODE_SCRIPT = r"""
const Growth = require(%(js)s);
const std = require(%(json)s);
const cases = require(%(fixture)s).cases;
const out = cases.map((c) => {
  const age = Growth.ageMonths(c.born, c.day);
  const z = Growth.zScore(std, c.sex, age, c.kg);
  const pc = Growth.percentile(z);
  const r = Growth.rowAt(std, c.sex, "p", age);
  return { age, z, pc, label: Growth.pctLabel(pc), band: Growth.band(pc), median: r ? r[3] : null };
});
// The number shown must fall in the band shown, all the way from P1 to P99.
const clash = [];
for (let i = 100; i <= 9900; i++) {
  const pc = i / 100;
  if (Growth.band(Number(Growth.pctLabel(pc))) !== Growth.band(pc)) clash.push(pc);
}
console.log(JSON.stringify(clash));
console.log(JSON.stringify(out));
"""


class TestGrowthJs(unittest.TestCase):
    def test_exists_and_is_loaded(self):
        self.assertTrue(GROWTH_JS.exists())
        html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
        self.assertLess(html.index("/static/growth.js"), html.index("/static/app.js"))

    def test_nothing_node_16_cannot_run(self):
        src = GROWTH_JS.read_text(encoding="utf-8")
        for bad in ("??=", ".at(", "||=", "&&="):
            self.assertNotIn(bad, src)

    def test_matches_the_fixture_under_node(self):
        if not _node.NODE:
            self.skipTest("no Node binary found (set BABY_LOG_NODE or install node)")
        rc, out, err = _node.run_js(NODE_SCRIPT % {
            "js": json.dumps(str(GROWTH_JS)), "json": json.dumps(str(gs.JSON_PATH)),
            "fixture": json.dumps(str(gs.FIXTURE))})
        self.assertEqual(rc, 0, err)
        lines = out.strip().splitlines()
        self.assertEqual(json.loads(lines[-2]), [], "a percentile label outside its own band")
        got = json.loads(lines[-1])
        self.assertEqual(len(got), len(FIXTURE))
        for want, have in zip(FIXTURE, got):
            ctx = (want["sex"], want["day"], want["kg"])
            for key, tol in (("age_months", 1e-9), ("z", 1e-9), ("percentile", 1e-3), ("median", 1e-9)):
                w, h = want[key], have["pc" if key == "percentile" else "age" if key == "age_months" else key]
                if w is None:
                    self.assertIsNone(h, (key, ctx))
                else:
                    self.assertAlmostEqual(h, w, delta=tol, msg=(key, ctx))
            self.assertEqual(have["label"], want["label"], ctx)
            self.assertEqual(have["band"], want["band"], ctx)

    def test_parses_under_node_check(self):
        if not _node.NODE:
            self.skipTest("no Node binary found")
        proc = subprocess.run([_node.NODE, "--check", str(GROWTH_JS)], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)


if __name__ == "__main__":
    unittest.main()
