"""
test_store.py — the journal, in isolation. Runs entirely in a temp directory; touches no
OneDrive folder.

    python tests/test_store.py
"""

# Run straight from the shell, only tests/ is on the path; discovered from the repo root, only
# the root is. Put both where imports can find them so both ways of running behave alike.
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path[:0] = [str(HERE), str(ROOT)]

import json
import os
import re
import shutil
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from unittest import mock
from zoneinfo import ZoneInfo

import store

CASES = json.loads((HERE / "fixtures" / "data_cases.json").read_text(encoding="utf-8"))
CHILD = "C-20260923-220000-0a1b"
T1 = "2026-09-23T17:50:00-05:00"
T2 = "2026-09-23T18:10:00-05:00"


def _py(value):
    """The fixture is JSON, which cannot spell infinity; its note says Python passes float('inf')."""
    if isinstance(value, dict):
        return {k: _py(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_py(v) for v in value]
    if value == "Infinity":
        return float("inf")
    return value


class JournalCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="baby-journal-test-"))
        self.j = store.Journal(self.tmp).ensure()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def feed(self, **kw):
        args = dict(child_id=CHILD, type="feed", time=T1, logged_by="Dad")
        args.update(kw)
        return self.j.write_event(**args)

    def event_files(self):
        return sorted(p for p in (self.tmp / "events").rglob("*.json"))

    def plant(self, day, name, payload):
        """Drop a file into the tree as another device (via OneDrive) would."""
        folder = self.tmp / "events" / day
        folder.mkdir(parents=True, exist_ok=True)
        (folder / name).write_text(json.dumps(payload), encoding="utf-8")
        return folder / name


# -- the shared fixture -------------------------------------------------------------------

class TestFixtureDefaults(unittest.TestCase):
    def test_defaults_equal_the_fixture(self):
        self.assertEqual(store.DEFAULTS, CASES["defaults"])

    def test_enums_equal_the_fixture(self):
        self.assertEqual({k: list(v) for k, v in store.ENUMS.items()}, CASES["enums"])

    def test_every_type_has_defaults(self):
        self.assertEqual(set(store.DEFAULTS), set(store.TYPES))


class TestFixtureAccept(unittest.TestCase):
    pass


class TestFixtureReject(unittest.TestCase):
    pass


def _make_accept(case):
    def test(self):
        got = store.validate_data(case["type"], _py(case["data"]))
        self.assertEqual(got, case["expect"], case["name"])
    return test


def _make_reject(case):
    def test(self):
        with self.assertRaises(ValueError, msg=case["name"]):
            store.validate_data(case["type"], _py(case["data"]))
    return test


def _slug(s):
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


for _case in CASES["accept"]:
    setattr(TestFixtureAccept, f"test_accept_{_slug(_case['name'])}", _make_accept(_case))
for _case in CASES["reject"]:
    setattr(TestFixtureReject, f"test_reject_{_slug(_case['name'])}", _make_reject(_case))


class TestFixtureTimes(unittest.TestCase):
    def test_accepted_times(self):
        for s in CASES["times"]["accept"]:
            dt = store.validate_time(s)
            self.assertIsNotNone(dt.utcoffset(), s)

    def test_rejected_times(self):
        for s in CASES["times"]["reject"]:
            with self.assertRaises(ValueError, msg=repr(s)):
                store.validate_time(s)

    def test_created_at_shapes(self):
        for s in CASES["created_at"]["accept"]:
            self.assertRegex(s, store.CREATED_RE)
        for s in CASES["created_at"]["reject"]:
            self.assertNotRegex(s, store.CREATED_RE)


class TestFixtureNames(unittest.TestCase):
    def test_accepted_names_parse(self):
        for c in CASES["names"]["accept"]:
            got = store.parse_name(c["name"])
            self.assertEqual(got, {"id": c["id"], "rev": c["rev"], "w": c["w"]}, c["name"])
            self.assertIsNotNone(store.NAME_RE.match(c["name"]))

    def test_rejected_names_are_none(self):
        for name in CASES["names"]["reject"]:
            self.assertIsNone(store.parse_name(name), name)
            self.assertIsNone(store.NAME_RE.match(name), name)


class TestFixtureResolve(unittest.TestCase):
    def test_every_resolve_case(self):
        for c in CASES["resolve"]["cases"]:
            winner = store.resolve(c["records"])["X"]
            self.assertEqual(winner["_file"], c["winner"], c["name"])
            if "live_count" in c:
                self.assertEqual(len(store.live(c["records"])), c["live_count"], c["name"])

    def test_order_of_input_does_not_change_the_winner(self):
        for c in CASES["resolve"]["cases"]:
            winner = store.resolve(list(reversed(c["records"])))["X"]
            self.assertEqual(winner["_file"], c["winner"], c["name"])


# -- module-level helpers -----------------------------------------------------------------

class TestHelpers(unittest.TestCase):
    def test_now_iso_is_fixed_width_utc_with_microseconds(self):
        s = store.now_iso()
        self.assertRegex(s, store.CREATED_RE)
        self.assertEqual(len(s), len("2026-09-23T22:50:12.123456+00:00"))

    def test_stamp_is_utc(self):
        dt = datetime(2026, 9, 23, 22, 50, 12, tzinfo=timezone.utc)
        self.assertEqual(store.stamp(dt), "20260923-225012")
        self.assertRegex(store.stamp(), r"^\d{8}-\d{6}$")

    def test_iso_local_keeps_the_offset_of_that_date(self):
        """Chicago is -05:00 in summer and -06:00 in winter; the offset must follow the date, not
        the day the code runs."""
        chicago = ZoneInfo("America/Chicago")
        self.assertEqual(store.iso_local(datetime(2026, 7, 1, 12, 0, tzinfo=chicago)),
                         "2026-07-01T12:00:00-05:00")
        self.assertEqual(store.iso_local(datetime(2026, 1, 5, 9, 0, tzinfo=chicago)),
                         "2026-01-05T09:00:00-06:00")
        # Either side of the November change-over (first Sunday, 2026-11-01).
        self.assertEqual(store.iso_local(datetime(2026, 10, 31, 23, 30, tzinfo=chicago)),
                         "2026-10-31T23:30:00-05:00")
        self.assertEqual(store.iso_local(datetime(2026, 11, 1, 3, 0, tzinfo=chicago)),
                         "2026-11-01T03:00:00-06:00")

    def test_iso_local_drops_microseconds_and_accepts_naive(self):
        s = store.iso_local(datetime(2026, 9, 23, 17, 50, 0, 123456))
        self.assertRegex(s, store.TIME_RE)
        self.assertTrue(s.startswith("2026-09-23T17:50:00"))
        store.validate_time(s)

    def test_validate_time_returns_an_aware_datetime(self):
        dt = store.validate_time(T1)
        self.assertEqual(dt.utcoffset().total_seconds(), -5 * 3600)

    def test_validate_time_rejects_an_impossible_date(self):
        with self.assertRaises(ValueError):
            store.validate_time("2026-02-30T10:00:00-05:00")

    def test_live_sorts_by_instant_not_by_string(self):
        early = {"event_id": "E-b", "revision": 1, "type": "note", "end": None,
                 "time": "2026-09-23T10:00:00+08:00", "created_at": "x", "device": "pc"}
        late = {"event_id": "E-a", "revision": 1, "type": "note", "end": None,
                "time": "2026-09-23T01:00:00-05:00", "created_at": "x", "device": "pc"}
        self.assertEqual([r["event_id"] for r in store.live([late, early])], ["E-b", "E-a"])

    def test_live_breaks_equal_instants_by_id(self):
        a = {"event_id": "E-2", "revision": 1, "type": "note", "end": None, "time": T1,
             "created_at": "x", "device": "pc"}
        b = {"event_id": "E-1", "revision": 1, "type": "note", "end": None, "time": T1,
             "created_at": "x", "device": "pc"}
        self.assertEqual([r["event_id"] for r in store.live([a, b])], ["E-1", "E-2"])

    def test_resolve_works_for_children_by_key(self):
        a = {"child_id": "C-1", "revision": 1, "created_at": "a", "device": "pc"}
        b = {"child_id": "C-1", "revision": 2, "created_at": "a", "device": "pc"}
        self.assertIs(store.resolve([a, b], "child_id")["C-1"], b)


class TestValidateData(unittest.TestCase):
    def test_none_means_defaults(self):
        self.assertEqual(store.validate_data("diaper", None), store.DEFAULTS["diaper"])

    def test_returns_a_fresh_object_and_does_not_touch_the_input(self):
        given = {"bottles": [{"kind": "formula", "ml": 22}]}
        got = store.validate_data("feed", given)
        self.assertEqual(given, {"bottles": [{"kind": "formula", "ml": 22}]})
        got["bottles"].append({"kind": "formula", "ml": 1})
        self.assertEqual(len(given["bottles"]), 1)
        self.assertEqual(store.DEFAULTS["feed"]["bottles"], [], "defaults must stay pristine")

    def test_arrays_are_replaced_not_merged(self):
        got = store.validate_data("feed", {"bottles": [{"kind": "breast_milk", "ml": 5}]})
        self.assertEqual(got["bottles"], [{"kind": "breast_milk", "ml": 5}])

    def test_bools_are_not_numbers(self):
        with self.assertRaises(ValueError):
            store.validate_data("feed", {"breast": {"left_s": True}})
        with self.assertRaises(ValueError):
            store.validate_data("pump", {"minutes": False})

    def test_float_seconds_and_nan_rules(self):
        self.assertEqual(store.validate_data("health", {"temp_c": 36.6})["temp_c"], 36.6)
        with self.assertRaises(ValueError):
            store.validate_data("health", {"temp_c": float("nan")})

    def test_timer_shapes_are_exact(self):
        with self.assertRaises(ValueError):
            store.validate_data("feed", {"timer": {"side": "left", "side_started": T1, "x": 1}})
        with self.assertRaises(ValueError):
            store.validate_data("sleep", {"timer": {"running": False}})
        with self.assertRaises(ValueError):
            store.validate_data("sleep", {"timer": {"running": True, "since": T1}})
        with self.assertRaises(ValueError):
            store.validate_data("sleep", {"timer": {}})
        self.assertEqual(store.validate_data("sleep", {"timer": None})["timer"], None)

    def test_bottle_with_extra_key_is_refused(self):
        with self.assertRaises(ValueError):
            store.validate_data("feed", {"bottles": [{"kind": "formula", "ml": 5, "temp": "warm"}]})

    def test_strings_where_strings_belong(self):
        with self.assertRaises(ValueError):
            store.validate_data("sleep", {"where": 3})
        with self.assertRaises(ValueError):
            store.validate_data("health", {"medicine": ["Vitamin D"]})
        self.assertEqual(store.validate_data("sleep", {"where": "婴儿床"})["where"], "婴儿床")

    def test_breast_must_be_an_object(self):
        with self.assertRaises(ValueError):
            store.validate_data("feed", {"breast": None})
        with self.assertRaises(ValueError):
            store.validate_data("feed", {"breast": [1]})

    def test_error_names_the_key(self):
        with self.assertRaisesRegex(ValueError, "middle_s"):
            store.validate_data("feed", {"breast": {"middle_s": 3}})
        with self.assertRaisesRegex(ValueError, "color"):
            store.validate_data("diaper", {"color": "purple"})


# -- writing and naming ---------------------------------------------------------------------

class TestWriting(JournalCase):
    def test_ensure_creates_every_subdir_and_is_idempotent(self):
        for d in store.SUBDIRS:
            self.assertTrue((self.tmp / d).is_dir(), d)
        self.j.ensure()
        self.assertTrue((self.tmp / "meta").is_dir())

    def test_a_new_event_has_the_spec_record_shape(self):
        rec = self.feed(data={"bottles": [{"kind": "formula", "ml": 22}]}, note="hungry")
        keys = ["event_id", "revision", "deleted", "reason", "child_id", "type", "time", "end",
                "data", "note", "logged_by", "edited_by", "device", "entered_from", "created_at"]
        self.assertEqual([k for k in rec if k != "_file"], keys)
        self.assertRegex(rec["event_id"], r"^E-\d{8}-\d{6}-[0-9a-f]{4}$")
        self.assertEqual(rec["revision"], 1)
        self.assertFalse(rec["deleted"])
        self.assertIsNone(rec["reason"])
        self.assertIsNone(rec["end"])
        self.assertIsNone(rec["edited_by"])
        self.assertEqual(rec["device"], "pc")
        self.assertEqual(rec["entered_from"], "pc")
        self.assertRegex(rec["created_at"], store.CREATED_RE)
        self.assertEqual(rec["data"]["breast"], store.DEFAULTS["feed"]["breast"])

    def test_the_file_is_named_per_the_rule_and_lands_in_the_utc_day_folder(self):
        rec = self.feed()
        files = self.event_files()
        self.assertEqual(len(files), 1)
        p = files[0]
        self.assertEqual(p.parent.name, datetime.now(timezone.utc).strftime("%Y-%m-%d"))
        parsed = store.parse_name(p.name)
        self.assertEqual(parsed, {"id": rec["event_id"], "rev": 1, "w": parsed["w"]})
        self.assertEqual(rec["_file"], p.name)

    def test_the_day_folder_is_the_write_date_not_the_event_date(self):
        self.feed(time="2026-01-05T09:00:00+08:00")
        self.assertEqual(self.event_files()[0].parent.name,
                         datetime.now(timezone.utc).strftime("%Y-%m-%d"))

    def test_file_on_disk_never_carries_file_key_and_is_utf8(self):
        rec = self.feed(note="喂奶 — 晚上")
        on_disk = json.loads(self.event_files()[0].read_text(encoding="utf-8"))
        self.assertNotIn("_file", on_disk)
        self.assertEqual(on_disk["note"], "喂奶 — 晚上")
        self.assertEqual(on_disk, {k: v for k, v in rec.items() if k != "_file"})

    def test_no_temp_debris_is_left_behind(self):
        self.feed()
        self.assertEqual(list(self.tmp.rglob("*.tmp")), [])
        self.assertEqual(list(self.tmp.rglob(".tmp-*")), [])

    def test_two_writes_in_the_same_second_do_not_collide(self):
        a = self.feed()
        b = self.feed()
        self.assertNotEqual(a["event_id"], b["event_id"])
        self.assertEqual(len(self.event_files()), 2)
        self.assertEqual(len(self.j.events()), 2)

    def test_twenty_rapid_writes_all_survive(self):
        ids = {self.feed()["event_id"] for _ in range(20)}
        self.assertEqual(len(ids), 20)
        self.assertEqual(len(self.j.events()), 20)
        self.assertEqual(len(self.event_files()), 20)

    def test_data_none_means_defaults_and_end_is_kept(self):
        rec = self.j.write_event(child_id=CHILD, type="sleep", time=T1, end=T2, logged_by="Mom",
                                 data={"where": "crib"})
        self.assertEqual(rec["data"], {"where": "crib", "timer": None})
        self.assertEqual(rec["end"], T2)
        rec2 = self.j.write_event(child_id=CHILD, type="note", time=T1, logged_by="Mom")
        self.assertEqual(rec2["data"], {"milestone": False})

    def test_created_at_is_fixed_width_and_orders_by_string(self):
        a = self.feed()
        b = self.feed()
        self.assertEqual(len(a["created_at"]), len(b["created_at"]))
        self.assertLess(a["created_at"], b["created_at"])

    def test_phone_style_fields_are_stored_as_given(self):
        rec = self.feed(device="d-3f9a", entered_from="phone", logged_by="Mom")
        self.assertEqual((rec["device"], rec["entered_from"], rec["logged_by"]),
                         ("d-3f9a", "phone", "Mom"))


class TestWriteValidation(JournalCase):
    def test_unknown_type(self):
        with self.assertRaises(ValueError):
            self.feed(type="bath")
        self.assertEqual(self.event_files(), [], "nothing is written on a refusal")

    def test_time_shape(self):
        for bad in CASES["times"]["reject"]:
            with self.assertRaises(ValueError, msg=repr(bad)):
                self.feed(time=bad)

    def test_end_shape_and_order(self):
        with self.assertRaises(ValueError):
            self.feed(end="2026-09-23T18:10:00Z")
        with self.assertRaises(ValueError):
            self.feed(time=T2, end=T1)
        self.feed(time=T1, end=T1)                         # equal is allowed (a zero-length feed)

    def test_end_is_compared_as_an_instant(self):
        # 18:00-05:00 is 23:00Z; 23:30+00:00 is later, even though the string sorts earlier.
        self.feed(time="2026-09-23T18:00:00-05:00", end="2026-09-23T23:30:00+00:00")
        with self.assertRaises(ValueError):
            self.feed(time="2026-09-23T18:00:00-05:00", end="2026-09-23T22:30:00+00:00")

    def test_data_is_validated(self):
        with self.assertRaises(ValueError):
            self.feed(data={"left_ml": 8})
        with self.assertRaises(ValueError):
            self.feed(data=[])

    def test_note_and_labels_must_be_strings(self):
        with self.assertRaises(ValueError):
            self.feed(note=None)
        with self.assertRaises(ValueError):
            self.feed(note=3)
        with self.assertRaises(ValueError):
            self.feed(logged_by=7)
        with self.assertRaises(ValueError):
            self.feed(logged_by=None)                      # a new event needs a label
        with self.assertRaises(ValueError):
            self.feed(edited_by=1)

    def test_entered_from_and_device(self):
        with self.assertRaises(ValueError):
            self.feed(entered_from="tablet")
        with self.assertRaises(ValueError):
            self.feed(device="")
        with self.assertRaises(ValueError):
            self.feed(child_id=None)

    def test_revision_of_unknown_id_is_a_key_error(self):
        with self.assertRaises(KeyError):
            self.feed(event_id="E-20260101-000000-dead")


class TestRevisions(JournalCase):
    def test_a_correction_is_a_new_file_not_an_edit(self):
        first = self.feed(note="first")
        original = self.event_files()[0].read_text(encoding="utf-8")
        second = self.feed(event_id=first["event_id"], note="second")
        self.assertEqual(second["revision"], 2)
        files = self.event_files()
        self.assertEqual(len(files), 2)
        r1 = next(p for p in files if store.parse_name(p.name)["rev"] == 1)
        self.assertEqual(r1.read_text(encoding="utf-8"), original, "revision 1 must never change")
        self.assertEqual(len(self.j.events()), 1)
        self.assertEqual(self.j.events()[0]["note"], "second")

    def test_filename_regex_round_trips_including_a_paper_id(self):
        pid = "E-paper-20260921-1400-feed"
        r1 = self.j.write_event(child_id=CHILD, type="feed", time="2026-09-21T14:00:00-05:00",
                                logged_by="paper", device="paper", entered_from="paper",
                                event_id=pid, revision=1)
        self.assertEqual((r1["event_id"], r1["revision"]), (pid, 1))
        r2 = self.j.write_event(child_id=CHILD, type="feed", time="2026-09-21T14:00:00-05:00",
                                logged_by="Dad", edited_by="Dad", event_id=pid)
        self.assertEqual(r2["revision"], 2)
        seen = sorted((store.parse_name(p.name)["id"], store.parse_name(p.name)["rev"])
                      for p in self.event_files())
        self.assertEqual(seen, [(pid, 1), (pid, 2)])
        self.assertEqual(self.j.event(pid)["revision"], 2)

    def test_explicit_revision_one_on_a_known_id_is_refused(self):
        first = self.feed()
        with self.assertRaises(FileExistsError):
            self.feed(event_id=first["event_id"], revision=1)
        self.feed(event_id=first["event_id"])            # r2
        with self.assertRaises(FileExistsError):
            self.feed(event_id=first["event_id"], revision=2)
        self.assertEqual(len(self.event_files()), 2)

    def test_logged_by_is_carried_unless_given(self):
        first = self.feed(logged_by="Mom")
        r2 = self.feed(event_id=first["event_id"], logged_by=None, edited_by="Dad")
        self.assertEqual(r2["logged_by"], "Mom")
        self.assertEqual(r2["edited_by"], "Dad")
        r3 = self.feed(event_id=first["event_id"], logged_by="Grandma")
        self.assertEqual(r3["logged_by"], "Grandma")
        r4 = self.feed(event_id=first["event_id"], logged_by=None)
        self.assertEqual(r4["logged_by"], "Grandma", "carried from the latest revision")

    def test_a_revision_may_change_type_and_child(self):
        first = self.feed()
        r2 = self.j.write_event(child_id="C-other", type="pump", time=T1, event_id=first["event_id"],
                                data={"left_ml": 40})
        self.assertEqual(r2["type"], "pump")
        self.assertEqual(r2["child_id"], "C-other")
        self.assertEqual(r2["data"], {"left_ml": 40, "right_ml": None, "minutes": None})
        with self.assertRaises(ValueError):
            self.j.write_event(child_id=CHILD, type="pump", time=T1, event_id=first["event_id"],
                               data={"wet": True})

    def test_revision_stamps_a_fresh_created_at_and_device(self):
        first = self.feed()
        r2 = self.feed(event_id=first["event_id"], device="d-1111", entered_from="phone",
                       edited_by="Mom")
        self.assertGreater(r2["created_at"], first["created_at"])
        self.assertEqual((r2["device"], r2["entered_from"]), ("d-1111", "phone"))

    def test_history_is_ascending_and_complete(self):
        first = self.feed()
        self.feed(event_id=first["event_id"])
        self.j.delete_event(first["event_id"], device="pc", edited_by="Dad")
        h = self.j.history(first["event_id"])
        self.assertEqual([r["revision"] for r in h], [1, 2, 3])
        self.assertTrue(h[-1]["deleted"])
        self.assertEqual(self.j.history("E-nothing"), [])

    def test_a_stop_and_a_switch_at_the_same_revision_resolve_to_the_stop(self):
        first = self.feed()
        base = {k: v for k, v in first.items() if k != "_file"}
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        stop = dict(base, revision=2, end=T2, created_at="2026-09-23T23:10:00.000000+00:00",
                    device="d-0001")
        switch = dict(base, revision=2, end=None, created_at="2026-09-23T23:10:01.000000+00:00",
                      device="d-0002",
                      data=dict(base["data"], timer={"side": "left", "side_started": T1}))
        self.plant(day, f"{first['event_id']}-r2-aaaa.json", stop)
        self.plant(day, f"{first['event_id']}-r2-bbbb.json", switch)
        self.j.load(force=True)
        self.assertEqual(self.j.event(first["event_id"])["end"], T2)
        self.assertEqual(len(self.j.history(first["event_id"])), 3)
        self.assertEqual(self.j._highest_revision(first["event_id"]), 2)
        r3 = self.feed(event_id=first["event_id"])
        self.assertEqual(r3["revision"], 3)


class TestTombstones(JournalCase):
    def test_delete_writes_a_tombstone_that_carries_every_field(self):
        first = self.feed(note="keep me", data={"bottles": [{"kind": "formula", "ml": 30}]})
        tomb = self.j.delete_event(first["event_id"], "wrong child", device="d-9999",
                                   edited_by="Mom")
        self.assertTrue(tomb["deleted"])
        self.assertEqual(tomb["reason"], "wrong child")
        self.assertEqual(tomb["revision"], 2)
        self.assertEqual(tomb["note"], "keep me")
        self.assertEqual(tomb["data"], first["data"])
        self.assertEqual(tomb["logged_by"], "Dad")
        self.assertEqual((tomb["device"], tomb["entered_from"], tomb["edited_by"]),
                         ("d-9999", "phone", "Mom"))
        self.assertGreater(tomb["created_at"], first["created_at"])
        self.assertEqual(self.j.events(), [])
        self.assertEqual(len(self.event_files()), 2)
        on_disk = json.loads(self.event_files()[-1].read_text(encoding="utf-8"))
        self.assertNotIn("_file", on_disk)

    def test_event_returns_the_tombstone_and_deleted_lists_it(self):
        first = self.feed()
        second = self.feed(time=T2)
        self.j.delete_event(first["event_id"], device="pc", edited_by="Dad")
        self.j.delete_event(second["event_id"], reason="undo", device="pc", edited_by="Dad")
        self.assertTrue(self.j.event(first["event_id"])["deleted"])
        gone = self.j.deleted()
        self.assertEqual([r["event_id"] for r in gone], [second["event_id"], first["event_id"]],
                         "newest tombstone first")
        self.assertEqual(gone[0]["reason"], "undo")
        self.assertIsNone(self.j.event("E-missing"))

    def test_deleting_twice_is_a_value_error(self):
        first = self.feed()
        self.j.delete_event(first["event_id"], device="pc", edited_by="Dad")
        with self.assertRaises(ValueError):
            self.j.delete_event(first["event_id"], device="pc", edited_by="Dad")
        self.assertEqual(len(self.event_files()), 2)

    def test_deleting_or_restoring_an_unknown_id_is_a_key_error(self):
        with self.assertRaises(KeyError):
            self.j.delete_event("E-20260101-000000-dead", device="pc", edited_by="Dad")
        with self.assertRaises(KeyError):
            self.j.restore_event("E-20260101-000000-dead", device="pc", edited_by="Dad")

    def test_restoring_a_live_event_is_a_value_error(self):
        first = self.feed()
        with self.assertRaises(ValueError):
            self.j.restore_event(first["event_id"], device="pc", edited_by="Dad")

    def test_restore_copies_the_latest_non_deleted_revision(self):
        first = self.feed(note="v1")
        self.feed(event_id=first["event_id"], note="v2", logged_by="Mom")
        self.j.delete_event(first["event_id"], reason="oops", device="pc", edited_by="Dad")
        back = self.j.restore_event(first["event_id"], device="d-0001", edited_by="Mom")
        self.assertEqual(back["revision"], 4)
        self.assertFalse(back["deleted"])
        self.assertIsNone(back["reason"])
        self.assertEqual(back["note"], "v2")
        self.assertEqual(back["logged_by"], "Mom")
        self.assertEqual((back["device"], back["entered_from"], back["edited_by"]),
                         ("d-0001", "phone", "Mom"))
        self.assertEqual(len(self.j.events()), 1)
        self.assertEqual(self.j.deleted(), [])
        self.assertEqual([r["revision"] for r in self.j.history(first["event_id"])], [1, 2, 3, 4])

    def test_restore_falls_back_to_the_tombstone_body(self):
        """A tombstone that arrived from a phone whose r1 has not synced yet: restore from what
        we have rather than fail."""
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        tomb = {"event_id": "E-20260923-225012-a1b2", "revision": 2, "deleted": True,
                "reason": "undo", "child_id": CHILD, "type": "diaper", "time": T1, "end": None,
                "data": store.validate_data("diaper", {"wet": True}), "note": "", "logged_by": "Mom",
                "edited_by": "Mom", "device": "d-0001", "entered_from": "phone",
                "created_at": "2026-09-23T23:00:00.000000+00:00"}
        self.plant(day, "E-20260923-225012-a1b2-r2-abcd.json", tomb)
        back = self.j.restore_event("E-20260923-225012-a1b2", device="pc", edited_by="Dad")
        self.assertEqual(back["revision"], 3)
        self.assertTrue(back["data"]["wet"])
        self.assertFalse(back["deleted"])

    def test_delete_then_restore_then_delete_again(self):
        first = self.feed()
        self.j.delete_event(first["event_id"], device="pc", edited_by="Dad")
        self.j.restore_event(first["event_id"], device="pc", edited_by="Dad")
        tomb = self.j.delete_event(first["event_id"], device="pc", edited_by="Dad")
        self.assertEqual(tomb["revision"], 4)
        self.assertEqual(self.j.events(), [])

    def test_delete_reason_must_be_a_string_or_none(self):
        first = self.feed()
        with self.assertRaises(ValueError):
            self.j.delete_event(first["event_id"], 5, device="pc", edited_by="Dad")


# -- reading ------------------------------------------------------------------------------

class TestQueries(JournalCase):
    def test_events_are_sorted_by_instant(self):
        a = self.feed(time="2026-09-23T18:00:00-05:00")
        b = self.feed(time="2026-09-23T10:00:00+08:00")     # 02:00Z, the earlier instant
        c = self.feed(time="2026-09-22T23:59:00-05:00")
        self.assertEqual([e["event_id"] for e in self.j.events()],
                         [b["event_id"], c["event_id"], a["event_id"]])

    def test_events_on_slices_the_string_date(self):
        late = self.feed(time="2026-09-23T23:30:00-05:00")   # 04:30Z on the 24th
        early = self.feed(time="2026-09-24T00:10:00-05:00")
        self.assertEqual([e["event_id"] for e in self.j.events_on("2026-09-23")], [late["event_id"]])
        self.assertEqual([e["event_id"] for e in self.j.events_on("2026-09-24")], [early["event_id"]])
        self.assertEqual(self.j.events_on("2026-09-25"), [])

    def test_events_between_is_inclusive(self):
        self.feed(time="2026-09-20T10:00:00-05:00")
        self.feed(time="2026-09-21T10:00:00-05:00")
        self.feed(time="2026-09-23T10:00:00-05:00")
        self.feed(time="2026-09-24T10:00:00-05:00")
        got = self.j.events_between("2026-09-21", "2026-09-23")
        self.assertEqual([e["time"][:10] for e in got], ["2026-09-21", "2026-09-23"])

    def test_tombstones_are_excluded_from_day_queries(self):
        first = self.feed()
        self.j.delete_event(first["event_id"], device="pc", edited_by="Dad")
        self.assertEqual(self.j.events_on(T1[:10]), [])
        self.assertEqual(self.j.events_between("2026-01-01", "2026-12-31"), [])

    def test_a_fresh_journal_object_sees_the_same_data(self):
        """What the PC reads must be exactly what a phone wrote — no in-memory state."""
        a = self.feed(note="persisted")
        self.j.delete_event(self.feed()["event_id"], device="pc", edited_by="Dad")
        again = store.Journal(self.tmp)
        self.assertEqual([e["event_id"] for e in again.events()], [a["event_id"]])
        self.assertEqual(again.events()[0]["note"], "persisted")
        self.assertEqual(again.events()[0]["_file"], a["_file"])
        self.assertEqual(again.stats()["deleted"], 1)

    def test_stats_shape(self):
        self.feed()
        gone = self.feed(time=T2)
        self.j.delete_event(gone["event_id"], device="pc", edited_by="Dad")
        self.j.write_child(name="Yisen", born="2026-09-21")
        s = self.j.stats()
        self.assertEqual(set(s), {"events", "deleted", "children", "files", "newest_at", "unreadable"})
        self.assertEqual((s["events"], s["deleted"], s["children"], s["files"]), (1, 1, 1, 4))
        self.assertRegex(s["newest_at"], store.CREATED_RE)
        self.assertEqual(s["unreadable"], [])

    def test_empty_journal_stats(self):
        s = self.j.stats()
        self.assertEqual(s, {"events": 0, "deleted": 0, "children": 0, "files": 0,
                             "newest_at": None, "unreadable": []})

    def test_non_journal_names_are_ignored(self):
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self.plant(day, "notes.txt", {"event_id": "E-x"})
        self.plant(day, "E-20260923-225012-a1b2-r1.json", {"event_id": "E-20260923-225012-a1b2"})
        (self.tmp / "events" / day / ".tmp-abc.tmp").write_text("{", encoding="utf-8")
        self.j.load(force=True)
        self.assertEqual(self.j.events(), [])
        self.assertEqual(self.j.stats()["unreadable"], [])

    def test_unknown_top_level_keys_in_a_file_are_preserved(self):
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        rec = {k: v for k, v in self.feed().items() if k != "_file"}
        rec.update(revision=2, future_key="kept", created_at="2026-09-23T23:59:00.000000+00:00")
        self.plant(day, f"{rec['event_id']}-r2-ffff.json", rec)
        self.j.load(force=True)
        self.assertEqual(self.j.event(rec["event_id"])["future_key"], "kept")


class TestDefensiveReading(JournalCase):
    def test_unreadable_files_are_skipped_reported_and_picked_up_once_fixed(self):
        good = self.feed()
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        broken = self.tmp / "events" / day / "E-20260923-225012-dead-r1-aaaa.json"
        broken.write_text("{not json", encoding="utf-8")
        empty = self.tmp / "events" / day / "E-20260923-225012-beef-r1-bbbb.json"
        empty.write_bytes(b"")
        listy = self.tmp / "events" / day / "E-20260923-225012-cafe-r1-cccc.json"
        listy.write_text("[1, 2]", encoding="utf-8")

        self.j.load(force=True)
        self.assertEqual([e["event_id"] for e in self.j.events()], [good["event_id"]])
        self.assertEqual(sorted(self.j.stats()["unreadable"]),
                         sorted([broken.name, empty.name, listy.name]))
        self.assertEqual(self.j.stats()["files"], 4)

        fixed = dict({k: v for k, v in good.items() if k != "_file"},
                     event_id="E-20260923-225012-dead", time=T2)
        broken.write_text(json.dumps(fixed), encoding="utf-8")
        self.j.load(force=True)
        self.assertEqual(len(self.j.events()), 2)
        self.assertEqual(sorted(self.j.stats()["unreadable"]), sorted([empty.name, listy.name]))

    def test_unreadable_is_retried_on_every_scan_not_cached_as_absent(self):
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        p = self.tmp / "events" / day / "E-20260923-225012-dead-r1-aaaa.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("{", encoding="utf-8")
        self.j.load(force=True)
        self.j.load(force=True)
        with mock.patch("json.loads", wraps=json.loads) as loads:
            self.j.load(force=True)
            self.assertEqual(loads.call_count, 1)

    def test_index_does_not_reparse_unchanged_files(self):
        for _ in range(3):
            self.feed()
        again = store.Journal(self.tmp)
        with mock.patch("json.loads", wraps=json.loads) as loads:
            again.load(force=True)
            self.assertEqual(loads.call_count, 3)
            again.load(force=True)
            self.assertEqual(loads.call_count, 3, "unchanged files are parsed once")
            again.events(); again.stats(); again.deleted()
            self.assertEqual(loads.call_count, 3)

        # A file whose bytes change (size or mtime) is read again; the others are not.
        p = self.event_files()[0]
        rec = json.loads(p.read_text(encoding="utf-8"))
        rec["note"] = "changed on another device (would never happen to r1, but the index must notice)"
        p.write_text(json.dumps(rec), encoding="utf-8")
        with mock.patch("json.loads", wraps=json.loads) as loads:
            again.load(force=True)
            self.assertEqual(loads.call_count, 1)
        self.assertIn("changed", next(e for e in again.events() if e["_file"] == p.name)["note"])

    def test_a_vanished_file_leaves_the_index(self):
        a = self.feed()
        b = self.feed(time=T2)
        self.event_files()[0].unlink()
        self.j.load(force=True)
        self.assertEqual(len(self.j.events()), 1)
        self.assertEqual(self.j.stats()["files"], 1)
        self.assertEqual({e["event_id"] for e in self.j.events()} <= {a["event_id"], b["event_id"]}, True)

    def test_scan_is_skipped_while_fresh_and_forced_on_demand(self):
        self.j.load(force=True)
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        rec = dict(self.feed().items())
        foreign = {k: v for k, v in rec.items() if k != "_file"}
        foreign.update(event_id="E-20260923-225012-f00d")
        self.plant(day, "E-20260923-225012-f00d-r1-aaaa.json", foreign)
        self.assertEqual(len(self.j.events()), 1, "a foreign file waits for the next scan")
        self.j.load(force=True)
        self.assertEqual(len(self.j.events()), 2)

    def test_own_writes_are_visible_immediately_without_a_rescan(self):
        self.j.load(force=True)
        a = self.feed()
        self.assertEqual([e["event_id"] for e in self.j.events()], [a["event_id"]])
        self.assertEqual(self.j.stats()["files"], 1)

    def test_missing_folders_do_not_crash_the_reader(self):
        bare = store.Journal(self.tmp / "nowhere")
        self.assertEqual(bare.events(), [])
        self.assertEqual(bare.children(), [])
        self.assertEqual(bare.stats()["files"], 0)

    def test_fingerprint_moves_on_any_new_file_whatever_its_created_at(self):
        self.j.load(force=True)
        before = self.j.fingerprint()
        self.assertEqual(before, (0, 0, 0))
        self.assertEqual(self.j.fingerprint(), before, "nothing changed, nothing moves")
        pc = self.feed()
        after_pc = self.j.fingerprint()
        self.assertNotEqual(after_pc, before)
        # A phone's queued upload keeps its original created_at, so it lands *older* than the
        # last PC write; stats()["newest_at"] does not move, the fingerprint must.
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        old = {k: v for k, v in pc.items() if k != "_file"}
        old.update(event_id="E-20260923-030000-ph01", created_at="2026-09-23T08:00:05.000000+00:00")
        self.plant(day, "E-20260923-030000-ph01-r1-abcd.json", old)
        self.j.load(force=True)
        self.assertEqual(self.j.stats()["newest_at"], pc["created_at"])
        self.assertNotEqual(self.j.fingerprint(), after_pc)


# -- threads --------------------------------------------------------------------------------

class TestThreads(JournalCase):
    """One Journal serves Flask's request threads, the 60 s scan and the post-write timer."""

    def test_readers_and_a_writer_share_the_journal_without_errors(self):
        # Before the lock, a _remember landing while a request iterated the index raised
        # "dictionary changed size during iteration" and that request answered 500; a write
        # landing mid-rescan was dropped from the index until the next scan.
        written, errors = [], []

        def write():
            try:
                for i in range(40):
                    eid = self.feed(note=str(i))["event_id"]
                    written.append(eid)
                    if self.j.event(eid) is None:
                        errors.append(AssertionError(f"{eid} invisible right after its write"))
            except Exception as e:                    # noqa: BLE001 — reported below
                errors.append(e)

        def read():
            try:
                for i in range(200):
                    self.j.events()
                    self.j.stats()
                    if i % 10 == 0:
                        self.j.load(force=True)      # the scan thread's rescans interleave too
            except Exception as e:                    # noqa: BLE001
                errors.append(e)

        threads = [threading.Thread(target=write)] + [threading.Thread(target=read) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(60)
        self.assertEqual(errors, [])
        self.assertEqual(len(written), 40)
        self.assertEqual({e["event_id"] for e in self.j.events()}, set(written))
        self.assertEqual(self.j.stats()["files"], 40)

    def test_a_write_during_a_rescan_waits_and_is_not_dropped(self):
        # Shape two of the bug: load() built a fresh dict, a write on another thread landed in
        # the old one, and load()'s final assignment threw the write away for SCAN_TTL_S.
        self.feed()
        listed, proceed = threading.Event(), threading.Event()
        real = self.j._candidate_files

        def slow_listing():
            yield from real()
            listed.set()
            proceed.wait(5)          # the tree is walked; hold the scan just before it assigns

        done = []
        with mock.patch.object(self.j, "_candidate_files", slow_listing):
            scan = threading.Thread(target=lambda: self.j.load(force=True))
            scan.start()
            self.assertTrue(listed.wait(5))
            writer = threading.Thread(target=lambda: done.append(self.feed(time=T2)))
            writer.start()
            writer.join(0.3)
            self.assertTrue(writer.is_alive(), "the write waits for the scan to finish")
            proceed.set()
            scan.join(5)
            writer.join(5)
        self.assertEqual(len(done), 1)
        self.assertIsNotNone(self.j.event(done[0]["event_id"]))
        self.assertEqual(len(self.j.events()), 2)
        self.assertEqual(self.j.stats()["files"], 2)


# -- children -------------------------------------------------------------------------------

class TestChildren(JournalCase):
    def test_a_child_record_has_the_spec_shape(self):
        rec = self.j.write_child(name="Yisen", born="2026-09-21")
        keys = ["child_id", "revision", "deleted", "reason", "name", "born", "born_time", "sex",
                "birth_weight_g", "targets", "device", "created_at"]
        self.assertEqual([k for k in rec if k != "_file"], keys)
        self.assertRegex(rec["child_id"], r"^C-\d{8}-\d{6}-[0-9a-f]{4}$")
        self.assertEqual(rec["targets"], {"feeds_per_day": None, "wet_per_day": None,
                                          "dirty_per_day": None})
        self.assertEqual(rec["revision"], 1)
        files = list((self.tmp / "children").glob("*.json"))
        self.assertEqual(len(files), 1)
        self.assertEqual(store.parse_name(files[0].name)["id"], rec["child_id"])
        self.assertNotIn("_file", json.loads(files[0].read_text(encoding="utf-8")))

    def test_children_come_oldest_id_first_and_child_resolves(self):
        a = self.j.write_child(name="One", born="2026-09-21")
        b = self.j.write_child(name="Two", born="2026-09-22")
        ids = [c["child_id"] for c in self.j.children()]
        self.assertEqual(ids, sorted([a["child_id"], b["child_id"]]))
        self.assertEqual(self.j.child(a["child_id"])["name"], "One")
        self.assertIsNone(self.j.child("C-nothing"))

    def test_revising_a_child_merges_targets_over_null_defaults(self):
        a = self.j.write_child(name="Yisen", born="2026-09-21")
        r2 = self.j.write_child(name="Yisen", born="2026-09-21", born_time="03:15",
                                birth_weight_g=3420, targets={"feeds_per_day": 8},
                                child_id=a["child_id"], device="d-0001")
        self.assertEqual(r2["revision"], 2)
        self.assertEqual(r2["targets"], {"feeds_per_day": 8, "wet_per_day": None,
                                         "dirty_per_day": None})
        self.assertEqual(len(self.j.children()), 1)
        self.assertEqual(self.j.child(a["child_id"])["born_time"], "03:15")
        self.assertEqual(len(list((self.tmp / "children").glob("*.json"))), 2)

    def test_child_validation(self):
        with self.assertRaises(ValueError):
            self.j.write_child(name="", born="2026-09-21")
        with self.assertRaises(ValueError):
            self.j.write_child(name="Y", born="21/09/2026")
        with self.assertRaises(ValueError):
            self.j.write_child(name="Y", born="2026-09-21", born_time="3:15")
        with self.assertRaises(ValueError):
            self.j.write_child(name="Y", born="2026-09-21", birth_weight_g="3.4 kg")
        with self.assertRaises(ValueError):
            self.j.write_child(name="Y", born="2026-09-21", targets={"naps_per_day": 3})
        with self.assertRaises(KeyError):
            self.j.write_child(name="Y", born="2026-09-21", child_id="C-20260101-000000-dead")
        self.assertEqual(list((self.tmp / "children").glob("*.json")), [])

    def test_children_and_events_do_not_mix(self):
        self.j.write_child(name="Yisen", born="2026-09-21")
        self.feed()
        self.assertEqual(len(self.j.children()), 1)
        self.assertEqual(len(self.j.events()), 1)
        s = self.j.stats()
        self.assertEqual((s["children"], s["events"], s["files"]), (1, 1, 2))


# -- opening ---------------------------------------------------------------------------------

class TestOpening(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="baby-journal-open-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_resolve_root_precedence(self):
        cfg = {"paths": {"app_folder": str(self.tmp / "cfg")}}
        with mock.patch.dict(os.environ, {"BABY_LOG_APP_FOLDER": ""}):
            self.assertEqual(store.resolve_root(cfg), self.tmp / "cfg")
            self.assertEqual(store.resolve_root(cfg, str(self.tmp / "arg")), self.tmp / "arg")
        with mock.patch.dict(os.environ, {"BABY_LOG_APP_FOLDER": str(self.tmp / "env")}):
            self.assertEqual(store.resolve_root(cfg), self.tmp / "env")
            self.assertEqual(store.resolve_root(cfg, str(self.tmp / "arg")), self.tmp / "arg")
        with mock.patch.dict(os.environ, {"BABY_LOG_APP_FOLDER": ""}):
            with self.assertRaises(RuntimeError):
                store.resolve_root({"paths": {"app_folder": None}})

    def test_open_journal_reads_config_and_ensures_the_tree(self):
        root = self.tmp / "journal"
        cfg = self.tmp / "config.yaml"
        cfg.write_text(f"paths:\n  app_folder: {json.dumps(str(root))}\n", encoding="utf-8")
        with mock.patch.dict(os.environ, {"BABY_LOG_APP_FOLDER": ""}):
            j = store.open_journal(str(cfg))
        self.assertEqual(j.root, root)
        for d in store.SUBDIRS:
            self.assertTrue((root / d).is_dir(), d)
        j2 = store.open_journal(str(cfg), root=str(self.tmp / "other"))
        self.assertEqual(j2.root, self.tmp / "other")


if __name__ == "__main__":
    unittest.main(verbosity=1)
