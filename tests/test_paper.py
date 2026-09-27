"""
test_paper.py — the paper-sheet import against a temp journal. Reads the real
tools/paper_sheet.json (it is data, not a personal folder) and writes only under a temp dir.

    python tests/test_paper.py
"""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path[:0] = [str(HERE), str(ROOT)]

import contextlib
import io
import json
import shutil
import tempfile
import unittest
from datetime import datetime

import paper
import store

SHEET = ROOT / "tools" / "paper_sheet.json"


def quiet(fn, *a, **kw):
    """Run the import without its summary cluttering the test output."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        result = fn(*a, **kw)
    return result, buf.getvalue()


class PaperCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="baby-paper-test-"))
        self.j = store.Journal(self.tmp / "journal").ensure()
        self.sheet = paper.load(SHEET)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def event_files(self):
        return sorted(p for p in (self.j.root / "events").rglob("*.json"))

    def child_files(self):
        return sorted(p for p in (self.j.root / "children").rglob("*.json"))

    def planned(self, event_id):
        for ev in paper.plan(self.sheet, "C-test"):
            if ev["event_id"] == event_id:
                return ev
        self.fail(f"{event_id} not in the plan")

    def write_sheet(self, sheet):
        p = self.tmp / "sheet.json"
        p.write_text(json.dumps(sheet), encoding="utf-8")
        return p


class SheetTests(PaperCase):
    def test_sheet_shape(self):
        self.assertEqual(len(self.sheet["feeds"]), 18)
        self.assertEqual(len(self.sheet["diapers"]), 19)
        self.assertEqual(self.sheet["child"], {"name": "Yisen", "born": "2026-09-21"})

    def test_plan_has_every_row_once_in_time_order(self):
        events = paper.plan(self.sheet, "C-test")
        self.assertEqual(len(events), 37)
        ids = [e["event_id"] for e in events]
        self.assertEqual(len(set(ids)), 37)
        times = [e["time"] for e in events]
        self.assertEqual(times, sorted(times))
        for ev in events:
            self.assertRegex(ev["event_id"], r"^E-paper-\d{8}-\d{4}-(feed|diaper)$")
            self.assertRegex(ev["time"], store.TIME_RE)
            self.assertIsNone(ev["end"])
            self.assertEqual((ev["logged_by"], ev["device"], ev["entered_from"]),
                             ("paper", "paper", "paper"))
            self.assertEqual(ev["child_id"], "C-test")

    def test_feed_with_check(self):
        ev = self.planned("E-paper-20260921-2044-feed")
        self.assertEqual(ev["type"], "feed")
        self.assertEqual(ev["time"][:16], "2026-09-21T20:44")
        self.assertEqual(ev["data"], {
            "breast": {"left_s": None, "right_s": None, "total_s": 60, "last_side": None,
                       "approx": False},
            "bottles": [], "made_ml": None, "leftover_ml": None, "timer": None})
        self.assertEqual(ev["note"], 'Check: bottle amount unclear, written "4ml 1min + 1ml"')
        # The transcriber's reading of the handwriting is not stored.
        self.assertNotIn("written", ev)

    def test_two_portion_feed(self):
        ev = self.planned("E-paper-20260922-0725-feed")
        self.assertEqual(ev["data"]["breast"]["total_s"], 900)
        self.assertTrue(ev["data"]["breast"]["approx"])
        self.assertEqual(ev["data"]["bottles"],
                         [{"kind": "formula", "ml": 5, "formula": None}, {"kind": "formula", "ml": 15, "formula": None}])
        self.assertIsNone(ev["data"]["made_ml"])
        self.assertIsNone(ev["data"]["leftover_ml"])
        self.assertEqual(ev["note"], "")

    def test_sticky_black_diaper(self):
        ev = self.planned("E-paper-20260922-0130-diaper")
        self.assertEqual(ev["type"], "diaper")
        self.assertEqual(ev["data"], {"wet": True, "dirty": True, "color": "black",
                                      "texture": "sticky", "size": None, "rash": False,
                                      "blowout": False})
        self.assertEqual(ev["note"], "sticky")

    def test_green_solid_diaper_with_check(self):
        ev = self.planned("E-paper-20260923-1130-diaper")
        self.assertEqual(ev["data"], {"wet": False, "dirty": True, "color": "green",
                                      "texture": "solid", "size": None, "rash": False,
                                      "blowout": False})
        self.assertEqual(ev["note"],
                         'green + solid — Check: the note after "green + solid" is unclear')

    def test_time_carries_the_zones_offset_on_that_date(self):
        ev = self.planned("E-paper-20260921-1400-feed")
        expected = datetime(2026, 9, 21, 14, 0).astimezone()
        self.assertEqual(ev["time"], expected.isoformat(timespec="seconds"))
        self.assertEqual(datetime.fromisoformat(ev["time"]).utcoffset(), expected.utcoffset())
        # The wall-clock part is exactly what the sheet says, on every row.
        for e in paper.plan(self.sheet, "C-test"):
            local = datetime.fromisoformat(e["time"])
            self.assertEqual(local.utcoffset(), local.replace(tzinfo=None).astimezone().utcoffset())
            self.assertEqual(e["event_id"].split("-")[2:4],
                             [local.strftime("%Y%m%d"), local.strftime("%H%M")])

    def test_note_composition(self):
        self.assertEqual(paper.compose_note({}), "")
        self.assertEqual(paper.compose_note({"note": "first"}), "first")
        self.assertEqual(paper.compose_note({"check": "hm?"}), "Check: hm?")
        self.assertEqual(paper.compose_note({"note": "first", "check": "hm?"}),
                         "first — Check: hm?")

    def test_duplicate_row_raises_before_anything_is_written(self):
        sheet = json.loads(SHEET.read_text(encoding="utf-8"))
        sheet["feeds"].append(dict(sheet["feeds"][0]))
        with self.assertRaises(ValueError):
            paper.plan(sheet, "C-test")
        with self.assertRaises(ValueError):
            quiet(paper.run, self.j, self.write_sheet(sheet))
        self.assertEqual(self.event_files(), [])
        # The child is created before the plan is built; refusing the sheet must not leave one
        # behind either, or the next run would find "a child" that the sheet never wrote.
        self.assertEqual(self.child_files(), [])

    def test_load_rejects_a_sheet_of_the_wrong_shape(self):
        with self.assertRaises(ValueError):
            paper.load(self.write_sheet({"feeds": [], "diapers": []}))
        with self.assertRaises(ValueError):
            paper.load(self.write_sheet({"child": {"name": "X"}, "feeds": [], "diapers": []}))

    def test_bad_row_value_is_refused(self):
        sheet = json.loads(SHEET.read_text(encoding="utf-8"))
        sheet["diapers"][0]["color"] = "purple"
        with self.assertRaises(ValueError):
            paper.plan(sheet, "C-test")


class RunTests(PaperCase):
    def test_first_run_writes_everything_and_the_child(self):
        result, out = quiet(paper.run, self.j, SHEET)
        self.assertEqual(result["written"], 37)
        self.assertEqual(result["skipped"], 0)
        self.assertEqual(len(self.event_files()), 37)
        self.assertEqual(len(self.child_files()), 1)
        kids = self.j.children()
        self.assertEqual(len(kids), 1)
        self.assertEqual(result["child_id"], kids[0]["child_id"])
        self.assertEqual((kids[0]["name"], kids[0]["born"]), ("Yisen", "2026-09-21"))
        self.assertIn("37 written, 0 skipped", out)
        for rec in self.j.events():
            self.assertEqual(rec["revision"], 1)
            self.assertEqual(rec["child_id"], result["child_id"])
            self.assertEqual(rec["entered_from"], "paper")
        self.assertEqual(len(self.j.events()), 37)
        # Every file name is the §3.1 shape for the paper id.
        for p in self.event_files():
            self.assertRegex(p.name, r"^E-paper-\d{8}-\d{4}-(feed|diaper)-r1-[0-9a-f]{4}\.json$")

    def test_second_run_writes_nothing(self):
        quiet(paper.run, self.j, SHEET)
        before = self.event_files()
        result, out = quiet(paper.run, store.Journal(self.j.root), SHEET)
        self.assertEqual(result, {"written": 0, "skipped": 37,
                                  "child_id": self.j.children()[0]["child_id"]})
        self.assertEqual(self.event_files(), before)
        self.assertEqual(len(self.child_files()), 1)
        self.assertIn("0 written, 37 skipped", out)

    def test_existing_child_is_reused_not_duplicated(self):
        kid = self.j.write_child(name="Yisen", born="2026-09-21", born_time="09:30")
        result, _ = quiet(paper.run, self.j, SHEET)
        self.assertEqual(result["child_id"], kid["child_id"])
        self.assertEqual(len(self.child_files()), 1)
        self.assertEqual(len(self.j.children()), 1)
        self.assertEqual(self.j.child(kid["child_id"])["born_time"], "09:30")
        for rec in self.j.events():
            self.assertEqual(rec["child_id"], kid["child_id"])

    def test_child_is_reused_even_when_the_journal_was_written_by_another_process(self):
        # The row may have been created by the app a moment ago: a fresh read must see it.
        store.Journal(self.j.root).ensure().write_child(name="Yisen", born="2026-09-21")
        self.j.load()
        result, _ = quiet(paper.run, self.j, SHEET)
        self.assertEqual(len(self.child_files()), 1)
        self.assertEqual(len(self.j.children()), 1)
        self.assertEqual(result["child_id"], self.j.children()[0]["child_id"])

    def test_tombstoned_row_is_skipped_not_reimported(self):
        quiet(paper.run, self.j, SHEET)
        self.j.delete_event("E-paper-20260921-1400-feed", "undo", device="pc", edited_by="Dad")
        result, _ = quiet(paper.run, self.j, SHEET)
        self.assertEqual((result["written"], result["skipped"]), (0, 37))
        self.assertTrue(self.j.event("E-paper-20260921-1400-feed")["deleted"])

    def test_dry_run_writes_nothing(self):
        result, out = quiet(paper.run, self.j, SHEET, dry_run=True)
        self.assertEqual(result["written"], 0)
        self.assertEqual(result["skipped"], 0)
        self.assertEqual(result["planned"], 37)
        self.assertIsNone(result["child_id"])
        self.assertEqual(self.event_files(), [])
        self.assertEqual(self.child_files(), [])
        self.assertFalse(list(self.j.root.rglob("*.tmp")))
        self.assertIn("Dry run", out)
        self.assertIn("would", out)
        self.assertIn("would be created", out)

    def test_store_guard_is_the_second_line_of_defence(self):
        quiet(paper.run, self.j, SHEET)
        ev = self.planned("E-paper-20260921-1400-feed")
        ev["child_id"] = self.j.children()[0]["child_id"]
        with self.assertRaises(FileExistsError):
            self.j.write_event(revision=1, **ev)

    def test_main_with_root_and_dry_run(self):
        rc, out = quiet(paper.main, ["--root", str(self.j.root), "--sheet", str(SHEET), "--dry-run"])
        self.assertEqual(rc, 0)
        self.assertIn("37", out)
        self.assertEqual(self.event_files(), [])
        rc, out = quiet(paper.main, ["--root", str(self.j.root), "--sheet", str(SHEET)])
        self.assertEqual(rc, 0)
        self.assertEqual(len(self.event_files()), 37)

    def test_main_reports_a_bad_sheet(self):
        sheet = json.loads(SHEET.read_text(encoding="utf-8"))
        sheet["diapers"].append(dict(sheet["diapers"][0]))
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            rc, _ = quiet(paper.main, ["--root", str(self.j.root), "--sheet", str(self.write_sheet(sheet))])
        self.assertEqual(rc, 1)
        self.assertIn("same id", err.getvalue())
        self.assertEqual(self.event_files(), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
