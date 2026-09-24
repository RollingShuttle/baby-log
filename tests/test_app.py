"""
test_app.py — the local server, in isolation.

    python tests/test_app.py

Runs against Flask's test client. The journal, the output folder and the data folder are all
under one throwaway temp directory and the background rollup threads are switched off
(rollup_delay_s=None), so this touches no OneDrive folder and leaves no timer firing into a
deleted directory.
"""

# Run straight from the shell, only tests/ is on the path; discovered from the repo root, only
# the root is. Put all three where imports can find them so both ways of running behave alike.
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path[:0] = [str(HERE), str(ROOT), str(ROOT / "tools")]

import json
import os
import shutil
import tempfile
import threading
import time
import unittest
from unittest import mock

import app as app_mod
import rollup as rollup_mod
import store as store_mod

# Fixed-offset times, so the assertions do not depend on the machine's zone.
D1 = "2026-09-23"
T1 = "2026-09-23T17:50:00-05:00"
T2 = "2026-09-23T18:10:00-05:00"
T3 = "2026-09-23T20:30:00-05:00"
T4 = "2026-09-23T23:00:00-05:00"


def _tree(folder):
    """Every entry under a folder, one level deep, minus Python's own cache."""
    folder = Path(folder)
    if not folder.exists():
        return set()
    return {p.name for p in folder.iterdir() if p.name != "__pycache__"}


class AppCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="app-test-"))
        self.journal_dir = self.tmp / "journal"
        self.out = self.tmp / "out"
        self.data = self.tmp / "data"
        self.cfg = self.tmp / "config.yaml"
        self.write_config()
        self.app = self.make_app()
        self.c = self.app.test_client()
        self.journal = self.app.config["journal"]

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write_config(self, **over):
        paths = {"app_folder": str(self.tmp / "cfg-journal"),
                 "output_folder": str(self.tmp / "cfg-out"),
                 "local_data": str(self.tmp / "cfg-data"),
                 "backups": str(self.tmp / "cfg-data" / "backups"), "backup_keep": 30}
        paths.update(over)
        lines = ["paths:"] + [f"  {k}: {json.dumps(v)}" for k, v in paths.items()]
        lines += ["server:", "  host: \"127.0.0.1\"", "  port: 8766", "  bind_lan: false"]
        self.cfg.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def make_app(self, **kw):
        args = dict(app_folder=str(self.journal_dir), output_folder=str(self.out),
                    data_dir=str(self.data), rollup_delay_s=None)
        args.update(kw)
        return app_mod.create_app(str(self.cfg), **args)

    def child(self, **kw):
        body = {"name": "Yisen", "born": "2026-09-21"}
        body.update(kw)
        r = self.c.post("/api/children", json=body)
        self.assertEqual(r.status_code, 201, r.get_json())
        return r.get_json()["child"]

    def post_event(self, **kw):
        body = {"type": "feed", "time": T1, "end": None, "data": {}, "note": ""}
        body.update(kw)
        return self.c.post("/api/event", json=body)

    def event(self, **kw):
        r = self.post_event(**kw)
        self.assertEqual(r.status_code, 201, r.get_json())
        return r.get_json()["event"]


class ChildCase(AppCase):
    """Most routes need a child on file; this is the ordinary state of the app."""

    def setUp(self):
        super().setUp()
        self.kid = self.child()


# -- static files ---------------------------------------------------------------------------

class TestStatic(AppCase):
    def test_index_is_served_when_it_exists(self):
        index = app_mod.STATIC_DIR / "index.html"
        r = self.c.get("/")
        if not index.exists():
            self.assertEqual(r.status_code, 404, "another agent writes static/index.html")
            return
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"Baby Log", r.data)
        self.assertIn(b"<title>Baby Log</title>", r.data)

    def test_core_js_is_the_shared_file_byte_for_byte(self):
        r = self.c.get("/core.js")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data, (ROOT / "docs" / "core.js").read_bytes())
        self.assertEqual(app_mod.CORE_JS, app_mod._resource_dir() / "docs" / "core.js")

    def test_core_js_is_never_cached(self):
        r = self.c.get("/core.js")
        self.assertEqual(r.headers.get("Cache-Control"), "no-cache")
        self.assertIn("javascript", r.headers.get("Content-Type", ""))

    def test_static_files_are_served_under_static(self):
        r = self.c.get("/static/print.css")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"size: Letter", r.data)
        r.close()

    def test_static_dir_is_a_public_module_name(self):
        self.assertTrue(str(app_mod.STATIC_DIR).endswith("static"))
        self.assertTrue((app_mod.STATIC_DIR / "icon.ico").exists(), "the tray reads this")

    def test_unknown_api_route_is_a_json_404(self):
        r = self.c.get("/api/nope")
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r.get_json()["ok"], False)
        self.assertIn("error", r.get_json())


# -- create_app -------------------------------------------------------------------------------

class TestCreateApp(AppCase):
    def test_arguments_beat_env_beat_config(self):
        with mock.patch.dict(os.environ, {"BABY_LOG_APP_FOLDER": str(self.tmp / "env-journal"),
                                          "BABY_LOG_OUTPUT_FOLDER": str(self.tmp / "env-out")}):
            by_arg = self.make_app()
            by_env = app_mod.create_app(str(self.cfg), data_dir=str(self.data),
                                        rollup_delay_s=None)
        by_cfg = app_mod.create_app(str(self.cfg), data_dir=str(self.data), rollup_delay_s=None)
        self.assertEqual(by_arg.config["journal"].root, self.journal_dir)
        self.assertEqual(by_arg.config["rollup"].output_folder, self.out)
        self.assertEqual(by_env.config["journal"].root, self.tmp / "env-journal")
        self.assertEqual(by_env.config["rollup"].output_folder, self.tmp / "env-out")
        self.assertEqual(by_cfg.config["journal"].root, self.tmp / "cfg-journal")
        self.assertEqual(by_cfg.config["rollup"].output_folder, self.tmp / "cfg-out")

    def test_data_dir_defaults_to_local_data_and_holds_backups(self):
        a = app_mod.create_app(str(self.cfg), app_folder=str(self.journal_dir),
                               output_folder=str(self.out), rollup_delay_s=None)
        self.assertEqual(a.config["rollup"].backup_dir, self.tmp / "cfg-data" / "backups")
        self.assertEqual(self.app.config["rollup"].backup_dir, self.data / "backups")
        self.assertEqual(self.app.config["rollup"].keep, 30)

    def test_no_output_folder_anywhere_is_refused(self):
        self.write_config(output_folder=None)
        with mock.patch.dict(os.environ, {"BABY_LOG_OUTPUT_FOLDER": ""}):
            with self.assertRaises(RuntimeError):
                app_mod.create_app(str(self.cfg), app_folder=str(self.journal_dir),
                                   data_dir=str(self.data), rollup_delay_s=None)

    def test_the_journal_folders_are_created(self):
        for d in ("children", "events", "meta"):
            self.assertTrue((self.journal_dir / d).is_dir())

    def test_no_background_threads_when_disabled(self):
        self.assertFalse(self.app.config["rollup"].enabled)
        self.assertFalse(any(t.name.startswith("rollup-") for t in threading.enumerate()))

    def test_config_path_alone_is_enough_for_the_launcher(self):
        """launch.py calls create_app(config) with one positional argument."""
        self.write_config(app_folder=str(self.journal_dir), output_folder=str(self.out),
                          local_data=str(self.data))
        a = app_mod.create_app(str(self.cfg), rollup_delay_s=None)
        self.assertEqual(a.config["journal"].root, self.journal_dir)


# -- config and settings ----------------------------------------------------------------------

class TestConfig(AppCase):
    def test_envelope_before_any_child(self):
        d = self.c.get("/api/config").get_json()
        self.assertEqual(set(d), {"ok", "child", "children", "settings", "version", "app_folder",
                                  "output_folder", "label"})
        self.assertTrue(d["ok"])
        self.assertIsNone(d["child"])
        self.assertEqual(d["children"], [])
        self.assertEqual(d["version"], app_mod.VERSION)
        self.assertEqual(Path(d["app_folder"]), self.journal_dir)
        self.assertEqual(Path(d["output_folder"]), self.out)
        self.assertEqual(d["label"], "")

    def test_child_and_label_appear_once_set(self):
        kid = self.child()
        self.c.post("/api/settings", json={"label": "Dad"})
        d = self.c.get("/api/config").get_json()
        self.assertEqual(d["child"]["child_id"], kid["child_id"])
        self.assertEqual(len(d["children"]), 1)
        self.assertEqual(d["label"], "Dad")
        self.assertEqual(d["settings"]["label"], "Dad")


class TestSettings(AppCase):
    def test_defaults_are_exactly_the_spec_keys(self):
        s = self.c.get("/api/settings").get_json()["settings"]
        self.assertEqual(s, {"label": "", "units": "ml", "step_ml": None, "quick_mode": "recent",
                             "quick_custom": [], "night_from": "21:00", "night_to": "07:00",
                             "child_id": None})

    def test_post_is_a_shallow_merge(self):
        r = self.c.post("/api/settings", json={"units": "oz", "quick_custom": [30, 60]})
        self.assertEqual(r.status_code, 200)
        s = r.get_json()["settings"]
        self.assertEqual((s["units"], s["quick_custom"], s["night_from"]), ("oz", [30, 60], "21:00"))
        s2 = self.c.post("/api/settings", json={"label": "Mom"}).get_json()["settings"]
        self.assertEqual((s2["units"], s2["label"]), ("oz", "Mom"))

    def test_settings_persist_in_data_dir(self):
        self.c.post("/api/settings", json={"label": "Dad"})
        saved = json.loads((self.data / "settings.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["label"], "Dad")
        self.assertEqual(set(saved), set(app_mod.SETTINGS_DEFAULTS))

    def test_unknown_key_is_400_and_nothing_changes(self):
        r = self.c.post("/api/settings", json={"units": "oz", "bogus": 1})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.get_json()["ok"], False)
        self.assertIn("bogus", r.get_json()["error"])
        self.assertEqual(self.c.get("/api/settings").get_json()["settings"]["units"], "ml")

    def test_values_are_checked(self):
        for bad in ({"units": "cups"}, {"step_ml": -1}, {"step_ml": "5"}, {"quick_mode": "x"},
                    {"quick_custom": [0]}, {"quick_custom": "30"}, {"night_from": "9pm"},
                    {"night_to": "25:00"}, {"child_id": 7}, {"label": None}):
            r = self.c.post("/api/settings", json=bad)
            self.assertEqual(r.status_code, 400, bad)

    def test_non_object_body_is_400(self):
        self.assertEqual(self.c.post("/api/settings", json=[1]).status_code, 400)
        self.assertEqual(self.c.post("/api/settings", data="x", content_type="text/plain").status_code, 400)

    def test_a_hand_edited_file_wins_over_memory(self):
        (self.data / "settings.json").write_text(json.dumps({"label": "Edited", "junk": 1}),
                                                 encoding="utf-8")
        s = self.c.get("/api/settings").get_json()["settings"]
        self.assertEqual(s["label"], "Edited")
        self.assertNotIn("junk", s)

    def test_a_corrupt_file_falls_back_to_defaults(self):
        (self.data / "settings.json").write_text("{not json", encoding="utf-8")
        self.assertEqual(self.c.get("/api/settings").get_json()["settings"]["units"], "ml")


# -- children -------------------------------------------------------------------------------

class TestChildren(AppCase):
    def test_create_returns_201_and_lists(self):
        kid = self.child(birth_weight_g=3420, targets={"feeds_per_day": 8})
        self.assertEqual(kid["name"], "Yisen")
        self.assertEqual(kid["targets"], {"feeds_per_day": 8, "wet_per_day": None,
                                          "dirty_per_day": None})
        self.assertEqual(kid["device"], "pc")
        d = self.c.get("/api/children").get_json()
        self.assertTrue(d["ok"])
        self.assertEqual([k["child_id"] for k in d["children"]], [kid["child_id"]])

    def test_missing_or_bad_fields_are_400(self):
        self.assertEqual(self.c.post("/api/children", json={"born": "2026-09-21"}).status_code, 400)
        self.assertEqual(self.c.post("/api/children", json={"name": "X", "born": "yesterday"}).status_code, 400)
        self.assertEqual(self.c.post("/api/children", json={"name": "X", "born": "2026-09-21",
                                                             "hair": "none"}).status_code, 400)
        self.assertEqual(self.c.post("/api/children", json=[]).status_code, 400)

    def test_revision_keeps_what_the_form_did_not_send(self):
        kid = self.child(birth_weight_g=3420)
        r = self.c.post("/api/children", json={"child_id": kid["child_id"],
                                               "targets": {"wet_per_day": 6}})
        self.assertEqual(r.status_code, 201)
        rev = r.get_json()["child"]
        self.assertEqual(rev["revision"], 2)
        self.assertEqual(rev["name"], "Yisen")
        self.assertEqual(rev["birth_weight_g"], 3420)
        self.assertEqual(rev["targets"]["wet_per_day"], 6)
        self.assertEqual(len(self.c.get("/api/children").get_json()["children"]), 1)

    def test_unknown_child_id_is_404(self):
        r = self.c.post("/api/children", json={"child_id": "C-20200101-000000-0000", "name": "X"})
        self.assertEqual(r.status_code, 404)

    def test_current_child_is_the_lexically_smallest_live_one(self):
        second = self.child(name="Later")
        # An older id planted as another device would have written it.
        older = {"child_id": "C-20200101-000000-0000", "revision": 1, "deleted": False,
                 "reason": None, "name": "Older", "born": "2020-01-01", "born_time": None,
                 "sex": None, "birth_weight_g": None, "targets": dict(store_mod.CHILD_TARGETS),
                 "device": "d-1111", "created_at": store_mod.now_iso()}
        (self.journal_dir / "children" / "C-20200101-000000-0000-r1-aaaa.json").write_text(
            json.dumps(older), encoding="utf-8")
        self.journal.load(force=True)
        d = self.c.get("/api/config").get_json()
        self.assertEqual(d["child"]["name"], "Older")
        self.assertEqual([k["name"] for k in d["children"]], ["Older", "Later"])
        self.assertNotEqual(second["child_id"], d["child"]["child_id"])

    def test_the_settings_choice_picks_among_live_children(self):
        first = self.child(name="First")
        second = self.child(name="Second")
        self.c.post("/api/settings", json={"child_id": second["child_id"]})
        self.assertEqual(self.c.get("/api/config").get_json()["child"]["name"], "Second")
        self.c.post("/api/settings", json={"child_id": "C-nope"})
        # Two ids minted in the same second differ only by their random suffix, so "oldest"
        # is whichever sorts first, not whichever was created first.
        smallest = min(first["child_id"], second["child_id"])
        self.assertEqual(self.c.get("/api/config").get_json()["child"]["child_id"], smallest)


# -- writing events ---------------------------------------------------------------------------

class TestWriteEvent(ChildCase):
    def test_new_event_is_201_with_the_pc_stamps(self):
        self.c.post("/api/settings", json={"label": "Dad"})
        ev = self.event(data={"bottles": [{"kind": "formula", "ml": 22}]}, note="ok")
        self.assertEqual(ev["revision"], 1)
        self.assertEqual(ev["child_id"], self.kid["child_id"])
        self.assertEqual((ev["device"], ev["entered_from"], ev["edited_by"]), ("pc", "pc", None))
        self.assertEqual(ev["logged_by"], "Dad")
        self.assertEqual(ev["data"]["bottles"], [{"kind": "formula", "ml": 22}])
        self.assertEqual(ev["data"]["breast"]["approx"], False)   # defaults filled in
        self.assertTrue(ev["event_id"].startswith("E-"))
        self.assertEqual(len(list((self.journal_dir / "events").rglob("*.json"))), 1)

    def test_logged_by_can_be_sent_explicitly(self):
        self.assertEqual(self.event(logged_by="Mom")["logged_by"], "Mom")

    def test_child_defaults_to_the_current_child_and_may_be_named(self):
        other = self.child(name="Two")
        ev = self.event(child_id=other["child_id"])
        self.assertEqual(ev["child_id"], other["child_id"])
        # Two ids minted in the same second sort by their random suffix, so pin the current
        # child rather than assume the first one made is the "oldest".
        self.c.post("/api/settings", json={"child_id": self.kid["child_id"]})
        self.assertEqual(self.event()["child_id"], self.kid["child_id"])

    def test_unknown_child_is_400(self):
        r = self.post_event(child_id="C-20200101-000000-0000")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.get_json()["ok"], False)

    def test_no_child_at_all_is_400_no_child(self):
        fresh = AppCase()
        fresh.setUp()
        try:
            r = fresh.c.post("/api/event", json={"type": "feed", "time": T1, "end": None,
                                                 "data": {}, "note": ""})
            self.assertEqual(r.status_code, 400)
            self.assertEqual(r.get_json()["error"], "no child")
        finally:
            fresh.tearDown()

    def test_invalid_data_is_400_and_nothing_is_written(self):
        r = self.post_event(data={"bottles": [{"kind": "juice", "ml": 22}]})
        self.assertEqual(r.status_code, 400)
        self.assertIn("kind", r.get_json()["error"])
        self.assertEqual(list((self.journal_dir / "events").rglob("*.json")), [])

    def test_shape_errors_are_400(self):
        self.assertEqual(self.post_event(time="2026-09-23T17:50:00Z").status_code, 400)
        self.assertEqual(self.post_event(type="bath").status_code, 400)
        self.assertEqual(self.post_event(end="2026-09-23T17:00:00-05:00").status_code, 400)
        self.assertEqual(self.post_event(data={"left_ml": 1}).status_code, 400)
        self.assertEqual(self.post_event(extra=1).status_code, 400)
        self.assertEqual(self.c.post("/api/event", json=[1]).status_code, 400)
        self.assertEqual(self.c.post("/api/event", data="nope", content_type="text/plain").status_code, 400)

    def test_unknown_event_id_is_404(self):
        r = self.post_event(event_id="E-20200101-000000-0000")
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r.get_json()["ok"], False)

    def test_an_event_id_on_file_writes_a_revision(self):
        self.c.post("/api/settings", json={"label": "Dad"})
        ev = self.event(logged_by="Mom")
        self.c.post("/api/settings", json={"label": "Dad"})
        r = self.post_event(event_id=ev["event_id"], note="fixed")
        self.assertEqual(r.status_code, 201)
        rev = r.get_json()["event"]
        self.assertEqual(rev["revision"], 2)
        self.assertEqual(rev["note"], "fixed")
        self.assertEqual(rev["logged_by"], "Mom", "carried unless sent")
        self.assertEqual(rev["edited_by"], "Dad")
        self.assertEqual(rev["device"], "pc")
        self.assertEqual(len(self.c.get(f"/api/event/{ev['event_id']}").get_json()["history"]), 2)

    def test_a_revision_may_change_who_and_type(self):
        ev = self.event(logged_by="Mom")
        rev = self.event(event_id=ev["event_id"], type="note", data={"milestone": True},
                         logged_by="Dad")
        self.assertEqual((rev["type"], rev["logged_by"]), ("note", "Dad"))
        self.assertEqual(rev["data"], {"milestone": True})
        self.assertEqual(rev["child_id"], self.kid["child_id"], "child carried when not sent")

    def test_the_event_body_wins_over_the_defaults(self):
        ev = self.event(type="diaper", time=T2, data={"wet": True, "color": "yellow"})
        self.assertEqual(ev["data"]["wet"], True)
        self.assertEqual(ev["data"]["dirty"], False)
        self.assertEqual(ev["data"]["color"], "yellow")

    def test_needs_check_notes_are_stored_verbatim(self):
        ev = self.event(note="Check: smudged 22?")
        self.assertEqual(ev["note"], "Check: smudged 22?")

    def test_every_write_schedules_the_rollup(self):
        rollup = self.app.config["rollup"]
        with mock.patch.object(rollup, "schedule") as sched:
            ev = self.event()
            self.c.delete(f"/api/event/{ev['event_id']}")
            self.c.post(f"/api/event/{ev['event_id']}/restore")
            self.c.post("/api/children", json={"child_id": self.kid["child_id"], "name": "Y"})
        self.assertEqual(sched.call_count, 4)


class TestTimers(ChildCase):
    def test_a_feed_with_a_timer_and_no_end_is_running(self):
        ev = self.event(data={"timer": {"side": "left", "side_started": T1}})
        self.assertIsNone(ev["end"])
        self.assertEqual(ev["data"]["timer"], {"side": "left", "side_started": T1})
        now = self.c.get("/api/now").get_json()
        self.assertEqual([r["event_id"] for r in now["running"]], [ev["event_id"]])
        self.assertEqual(now["last_feed"]["event_id"], ev["event_id"])

    def test_the_folded_revision_stops_it(self):
        ev = self.event(data={"timer": {"side": "left", "side_started": T1}})
        rev = self.event(event_id=ev["event_id"], end=T2,
                         data={"breast": {"left_s": 1200, "total_s": 1200, "last_side": "left"},
                               "timer": None})
        self.assertEqual(rev["revision"], 2)
        self.assertEqual(rev["end"], T2)
        self.assertIsNone(rev["data"]["timer"])
        now = self.c.get("/api/now").get_json()
        self.assertEqual(now["running"], [])
        day = self.c.get(f"/api/day?date={D1}").get_json()
        self.assertEqual(day["totals"]["breast_s"], 1200)
        self.assertEqual(day["events"][0]["data"]["breast"]["left_s"], 1200)

    def test_a_running_sleep_shows_too(self):
        ev = self.event(type="sleep", time=T3, data={"timer": {"running": True}})
        now = self.c.get("/api/now").get_json()
        self.assertEqual([r["type"] for r in now["running"]], ["sleep"])
        stop = self.event(event_id=ev["event_id"], type="sleep", end=T4, data={"timer": None})
        self.assertEqual(stop["end"], T4)
        self.assertEqual(self.c.get("/api/now").get_json()["running"], [])

    def test_a_bad_timer_is_refused(self):
        self.assertEqual(self.post_event(data={"timer": {"side": "up", "side_started": T1}}).status_code, 400)
        self.assertEqual(self.post_event(type="sleep", data={"timer": {"running": False}}).status_code, 400)


# -- reading events ---------------------------------------------------------------------------

class TestDay(ChildCase):
    def seed(self):
        self.f1 = self.event(time=T1, data={"bottles": [{"kind": "formula", "ml": 22}],
                                            "breast": {"total_s": 600}})
        self.d1 = self.event(type="diaper", time=T2, data={"wet": True, "dirty": True})
        self.s1 = self.event(type="sleep", time=T3, end=T4, data={"where": "crib"})
        self.prev = self.event(time="2026-09-22T08:00:00-05:00")
        self.next = self.event(time="2026-09-24T08:00:00-05:00")

    def test_envelope_and_sorting(self):
        self.seed()
        d = self.c.get(f"/api/day?date={D1}").get_json()
        self.assertEqual(set(d), {"ok", "date", "events", "totals", "has_prev", "has_next"})
        self.assertEqual(d["date"], D1)
        self.assertEqual([e["event_id"] for e in d["events"]],
                         [self.f1["event_id"], self.d1["event_id"], self.s1["event_id"]])
        self.assertTrue(d["has_prev"])
        self.assertTrue(d["has_next"])

    def test_totals_match_the_store_and_the_core_port(self):
        self.seed()
        d = self.c.get(f"/api/day?date={D1}").get_json()
        expect = rollup_mod.totals(self.journal.events_on(D1), D1)
        self.assertEqual(d["totals"], expect)
        self.assertEqual(d["totals"], {"feeds": 1, "bottle_ml": 22, "breast_s": 600, "wet": 1,
                                       "dirty": 1, "sleeps": 1, "sleep_s": 9000, "pumps": 0,
                                       "pump_ml": 0})

    def test_prev_and_next_at_the_edges(self):
        self.seed()
        first = self.c.get("/api/day?date=2026-09-22").get_json()
        last = self.c.get("/api/day?date=2026-09-24").get_json()
        self.assertEqual((first["has_prev"], first["has_next"]), (False, True))
        self.assertEqual((last["has_prev"], last["has_next"]), (True, False))

    def test_date_defaults_to_today(self):
        d = self.c.get("/api/day").get_json()
        self.assertEqual(d["date"], app_mod._today())
        self.assertEqual(d["events"], [])

    def test_bad_date_is_400(self):
        r = self.c.get("/api/day?date=23-09-2026")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.get_json()["ok"], False)
        self.assertEqual(self.c.get("/api/day?date=2026-02-30").status_code, 400)

    def test_deleted_events_leave_the_day(self):
        self.seed()
        self.c.delete(f"/api/event/{self.d1['event_id']}")
        d = self.c.get(f"/api/day?date={D1}").get_json()
        self.assertEqual(len(d["events"]), 2)
        self.assertEqual(d["totals"]["wet"], 0)

    def test_a_revision_shows_once_with_the_latest_values(self):
        self.seed()
        self.event(event_id=self.f1["event_id"], data={"bottles": [{"kind": "formula", "ml": 40}]})
        d = self.c.get(f"/api/day?date={D1}").get_json()
        feeds = [e for e in d["events"] if e["type"] == "feed"]
        self.assertEqual(len(feeds), 1)
        self.assertEqual(feeds[0]["revision"], 2)
        self.assertEqual(d["totals"]["bottle_ml"], 40)


class TestEvents(ChildCase):
    def test_range_is_inclusive_on_local_dates(self):
        a = self.event(time="2026-09-22T23:30:00-05:00")
        b = self.event(time="2026-09-23T00:10:00-05:00")
        c = self.event(time="2026-09-24T23:59:00-05:00")
        self.event(time="2026-09-25T00:00:00-05:00")
        d = self.c.get("/api/events?from=2026-09-22&to=2026-09-24").get_json()
        self.assertEqual(set(d), {"ok", "events"})
        self.assertEqual([e["event_id"] for e in d["events"]],
                         [a["event_id"], b["event_id"], c["event_id"]])

    def test_to_defaults_to_from(self):
        self.event(time=T1)
        self.event(time="2026-09-24T08:00:00-05:00")
        d = self.c.get(f"/api/events?from={D1}").get_json()
        self.assertEqual(len(d["events"]), 1)

    def test_bad_ranges_are_400(self):
        self.assertEqual(self.c.get("/api/events").status_code, 400)
        self.assertEqual(self.c.get("/api/events?from=2026-09-24&to=2026-09-23").status_code, 400)
        self.assertEqual(self.c.get("/api/events?from=x&to=2026-09-23").status_code, 400)


class TestEvent(ChildCase):
    def test_latest_record_with_ascending_history(self):
        ev = self.event(note="one")
        self.event(event_id=ev["event_id"], note="two")
        self.event(event_id=ev["event_id"], note="three")
        d = self.c.get(f"/api/event/{ev['event_id']}").get_json()
        self.assertEqual(set(d), {"ok", "event", "history"})
        self.assertEqual(d["event"]["note"], "three")
        self.assertEqual([h["revision"] for h in d["history"]], [1, 2, 3])
        self.assertEqual([h["note"] for h in d["history"]], ["one", "two", "three"])

    def test_a_tombstone_is_returned_here(self):
        ev = self.event()
        self.c.delete(f"/api/event/{ev['event_id']}", json={"reason": "undo"})
        d = self.c.get(f"/api/event/{ev['event_id']}").get_json()
        self.assertTrue(d["event"]["deleted"])
        self.assertEqual(d["event"]["reason"], "undo")
        self.assertEqual(len(d["history"]), 2)

    def test_unknown_is_404(self):
        r = self.c.get("/api/event/E-20200101-000000-0000")
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r.get_json(), {"ok": False, "error": "no such event E-20200101-000000-0000"})


class TestDeletedAndNeedsCheck(ChildCase):
    def test_deleted_lists_tombstones_newest_first(self):
        a = self.event(time=T1)
        b = self.event(time=T2)
        self.c.delete(f"/api/event/{a['event_id']}")
        self.c.delete(f"/api/event/{b['event_id']}")
        d = self.c.get("/api/deleted").get_json()
        self.assertEqual(set(d), {"ok", "events"})
        self.assertEqual([e["event_id"] for e in d["events"]], [b["event_id"], a["event_id"]])
        self.assertTrue(all(e["deleted"] for e in d["events"]))

    def test_needs_check_is_the_check_prefix_only(self):
        keep = self.event(note="Check: 22 or 27 ml?")
        # The paper import joins a row's own note and its question with " — " (§10).
        joined = self.event(time=T1, note="green + solid — Check: the rest is unclear")
        self.event(note="check: lower case")
        self.event(note="Please Check: this")
        self.event(note="Checked")
        gone = self.event(time=T2, note="Check: deleted one")
        self.c.delete(f"/api/event/{gone['event_id']}")
        d = self.c.get("/api/needs-check").get_json()
        self.assertEqual(sorted(e["event_id"] for e in d["events"]),
                         sorted([keep["event_id"], joined["event_id"]]))

    def test_a_corrected_entry_leaves_needs_check(self):
        ev = self.event(note="Check: 22 or 27 ml?")
        self.event(event_id=ev["event_id"], note="27 ml")
        self.assertEqual(self.c.get("/api/needs-check").get_json()["events"], [])


# -- delete and restore ------------------------------------------------------------------------

class TestDeleteRestore(ChildCase):
    def test_delete_writes_a_tombstone_with_the_reason(self):
        self.c.post("/api/settings", json={"label": "Dad"})
        ev = self.event(logged_by="Mom")
        r = self.c.delete(f"/api/event/{ev['event_id']}", json={"reason": "undo"})
        self.assertEqual(r.status_code, 200)
        t = r.get_json()["event"]
        self.assertEqual((t["deleted"], t["reason"], t["revision"]), (True, "undo", 2))
        self.assertEqual((t["logged_by"], t["edited_by"], t["device"]), ("Mom", "Dad", "pc"))
        self.assertEqual(self.c.get(f"/api/day?date={D1}").get_json()["events"], [])

    def test_delete_without_a_body_is_fine(self):
        ev = self.event()
        r = self.c.delete(f"/api/event/{ev['event_id']}")
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(r.get_json()["event"]["reason"])

    def test_delete_twice_is_409(self):
        ev = self.event()
        self.c.delete(f"/api/event/{ev['event_id']}")
        r = self.c.delete(f"/api/event/{ev['event_id']}")
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.get_json()["ok"], False)
        self.assertEqual(len(self.c.get(f"/api/event/{ev['event_id']}").get_json()["history"]), 2)

    def test_delete_unknown_is_404(self):
        self.assertEqual(self.c.delete("/api/event/E-20200101-000000-0000").status_code, 404)

    def test_restore_brings_the_last_live_body_back(self):
        ev = self.event(note="original")
        self.event(event_id=ev["event_id"], note="edited")
        self.c.delete(f"/api/event/{ev['event_id']}")
        r = self.c.post(f"/api/event/{ev['event_id']}/restore")
        self.assertEqual(r.status_code, 200)
        back = r.get_json()["event"]
        self.assertEqual((back["deleted"], back["reason"], back["revision"], back["note"]),
                         (False, None, 4, "edited"))
        self.assertEqual(len(self.c.get(f"/api/day?date={D1}").get_json()["events"]), 1)
        self.assertEqual(self.c.get("/api/deleted").get_json()["events"], [])

    def test_restore_a_live_event_is_409(self):
        ev = self.event()
        r = self.c.post(f"/api/event/{ev['event_id']}/restore")
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.get_json()["ok"], False)

    def test_restore_unknown_is_404(self):
        self.assertEqual(self.c.post("/api/event/E-20200101-000000-0000/restore").status_code, 404)

    def test_a_revision_of_a_deleted_event_is_still_allowed(self):
        """The editor can save over a tombstone; the store writes the next revision live."""
        ev = self.event()
        self.c.delete(f"/api/event/{ev['event_id']}")
        r = self.post_event(event_id=ev["event_id"], note="back")
        self.assertEqual(r.status_code, 201)
        self.assertFalse(r.get_json()["event"]["deleted"])


# -- the now panel -----------------------------------------------------------------------------

class TestNow(ChildCase):
    def test_envelope_when_empty(self):
        d = self.c.get("/api/now").get_json()
        self.assertEqual(set(d), {"ok", "now", "last_feed", "last_diaper", "running", "today",
                                  "usual_gap_s", "next_feed_at", "targets"})
        self.assertTrue(store_mod.TIME_RE.match(d["now"]))
        self.assertIsNone(d["last_feed"])
        self.assertIsNone(d["last_diaper"])
        self.assertEqual(d["running"], [])
        self.assertEqual(set(d["today"]), {"feeds", "bottle_ml", "breast_s", "wet", "dirty",
                                           "sleeps", "sleep_s", "pumps", "pump_ml"})
        self.assertIsNone(d["usual_gap_s"])
        self.assertIsNone(d["next_feed_at"])
        self.assertEqual(d["targets"], {"feeds_per_day": None, "wet_per_day": None,
                                        "dirty_per_day": None})

    def test_last_feed_and_diaper_are_the_latest_by_time(self):
        self.event(time=T1)
        late = self.event(time=T3)
        self.event(time=T2)
        dia = self.event(type="diaper", time=T2, data={"wet": True})
        d = self.c.get("/api/now").get_json()
        self.assertEqual(d["last_feed"]["event_id"], late["event_id"])
        self.assertEqual(d["last_diaper"]["event_id"], dia["event_id"])

    def test_usual_gap_needs_three_feeds_and_is_the_median(self):
        self.event(time="2026-09-23T10:00:00-05:00")
        self.event(time="2026-09-23T12:00:00-05:00")
        self.assertIsNone(self.c.get("/api/now").get_json()["usual_gap_s"])
        self.event(time="2026-09-23T15:00:00-05:00")
        d = self.c.get("/api/now").get_json()
        self.assertEqual(d["usual_gap_s"], 2.5 * 3600)
        self.assertTrue(store_mod.TIME_RE.match(d["next_feed_at"]))
        # last feed 15:00 -05:00 + 2 h 30 = 17:30 -05:00, expressed in this machine's zone.
        from datetime import datetime
        self.assertEqual(datetime.fromisoformat(d["next_feed_at"]).timestamp(),
                         datetime.fromisoformat("2026-09-23T17:30:00-05:00").timestamp())

    def test_targets_come_from_the_current_child(self):
        self.c.post("/api/children", json={"child_id": self.kid["child_id"],
                                           "targets": {"feeds_per_day": 8, "wet_per_day": 6}})
        d = self.c.get("/api/now").get_json()
        self.assertEqual(d["targets"]["feeds_per_day"], 8)

    def test_today_counts_only_today(self):
        self.event(time=T1)                        # a past day
        now = app_mod._now_local()
        self.event(time=store_mod.iso_local(now), data={"bottles": [{"kind": "formula", "ml": 30}]})
        d = self.c.get("/api/now").get_json()
        self.assertEqual((d["today"]["feeds"], d["today"]["bottle_ml"]), (1, 30))

    def test_a_second_child_narrows_the_panel(self):
        other = self.child(name="Two")
        self.c.post("/api/settings", json={"child_id": self.kid["child_id"]})
        mine = self.event(time=T1, child_id=self.kid["child_id"])
        self.event(time=T2, child_id=other["child_id"])
        d = self.c.get("/api/now").get_json()
        self.assertEqual(d["last_feed"]["event_id"], mine["event_id"])


# -- the readable files ------------------------------------------------------------------------

class TestRollupRoutes(ChildCase):
    def test_rollup_writes_the_workbook_and_reports_its_path(self):
        self.event()
        r = self.c.post("/api/rollup")
        self.assertEqual(r.status_code, 200, r.get_json())
        d = r.get_json()
        self.assertTrue(d["ok"])
        self.assertEqual(Path(d["path"]), self.out / "Baby Log.xlsx")
        self.assertTrue((self.out / "Baby Log.xlsx").exists())
        self.assertIsNotNone(self.c.get("/api/health").get_json()["rollup_at"])

    def test_rollup_is_409_while_excel_holds_the_file(self):
        self.out.mkdir(parents=True, exist_ok=True)
        (self.out / "~$Baby Log.xlsx").write_bytes(b"")
        r = self.c.post("/api/rollup")
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.get_json()["ok"], False)
        self.assertIn("open in Excel", r.get_json()["error"])
        self.assertFalse((self.out / "Baby Log.xlsx").exists())

    def test_daysheet_writes_into_day_sheets(self):
        self.event()
        r = self.c.post(f"/api/daysheet/{D1}")
        self.assertEqual(r.status_code, 200)
        path = Path(r.get_json()["path"])
        self.assertEqual(path, self.out / "Day sheets" / f"{D1}.html")
        text = path.read_text(encoding="utf-8")
        self.assertIn("Yisen — Feeding &amp; Diapering — Wed 23 Sep (day 3)", text)
        self.assertEqual(text, self.c.get(f"/print/day/{D1}").data.decode("utf-8"))

    def test_daysheet_bad_date_is_400(self):
        self.assertEqual(self.c.post("/api/daysheet/2026-9-3").status_code, 400)

    def test_print_day_is_html_with_no_external_urls(self):
        self.event(data={"bottles": [{"kind": "formula", "ml": 22}]})
        r = self.c.get(f"/print/day/{D1}")
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/html", r.headers["Content-Type"])
        text = r.data.decode("utf-8")
        self.assertIn("22 ml formula", text)
        self.assertNotIn("http://", text)
        self.assertNotIn("https://", text)
        self.assertIn("@page { size: Letter; margin: 0.5in; }", text)

    def test_print_day_honours_the_unit_setting(self):
        self.event(data={"bottles": [{"kind": "formula", "ml": 59}]})
        self.c.post("/api/settings", json={"units": "oz"})
        self.assertIn("2 oz formula", self.c.get(f"/print/day/{D1}").data.decode("utf-8"))

    def test_print_day_bad_date_is_400(self):
        self.assertEqual(self.c.get("/print/day/nope").status_code, 400)

    def test_print_range_is_one_daily_table(self):
        self.event(time="2026-09-22T08:00:00-05:00")
        self.event(time=T1, data={"bottles": [{"kind": "formula", "ml": 22}]})
        r = self.c.get("/print/range?from=2026-09-21&to=2026-09-23")
        self.assertEqual(r.status_code, 200)
        text = r.data.decode("utf-8")
        for col in rollup_mod.DAILY_COLUMNS:
            self.assertIn(f"<th class=\"num\">{col}</th>" if col != "date" else "<th>date</th>", text)
        self.assertEqual(text.count("<tr>"), 4)          # header + three days
        self.assertIn("2026-09-21", text)
        self.assertNotIn("http", text)

    def test_print_range_defaults_and_errors(self):
        self.assertEqual(self.c.get("/print/range").status_code, 200)
        self.assertEqual(self.c.get("/print/range?from=2026-09-24&to=2026-09-23").status_code, 400)
        self.assertEqual(self.c.get("/print/range?from=x").status_code, 400)


class TestHealth(ChildCase):
    def test_envelope(self):
        ev = self.event()
        d = self.c.get("/api/health").get_json()
        self.assertEqual(set(d), {"ok", "journal", "newest_file_at", "rollup_at", "version"})
        self.assertIs(d["ok"], True)
        self.assertEqual(d["journal"]["events"], 1)
        self.assertEqual(d["journal"]["children"], 1)
        self.assertEqual(d["newest_file_at"], ev["created_at"])
        self.assertIsNone(d["rollup_at"])
        self.assertEqual(d["version"], app_mod.VERSION)

    def test_unreadable_files_are_reported_not_fatal(self):
        day = self.journal_dir / "events" / "2026-09-23"
        day.mkdir(parents=True, exist_ok=True)
        (day / "E-20260923-000000-0000-r1-abcd.json").write_text("{half", encoding="utf-8")
        self.journal.load(force=True)
        d = self.c.get("/api/health").get_json()
        self.assertEqual(d["journal"]["unreadable"], ["E-20260923-000000-0000-r1-abcd.json"])
        self.assertEqual(self.c.get(f"/api/day?date={D1}").status_code, 200)


# -- lifecycle ---------------------------------------------------------------------------------

class TestLifecycle(AppCase):
    def test_the_three_routes_answer_as_the_launcher_expects(self):
        self.assertEqual(self.c.post("/api/heartbeat").get_json(), {"ok": True})
        self.assertEqual(self.c.post("/api/goodbye").status_code, 204)
        self.assertEqual(self.c.post("/api/window").status_code, 204)

    def test_they_keep_a_note_without_a_launcher(self):
        state = self.app.config["lifecycle"]
        self.c.post("/api/goodbye")
        self.assertIsNotNone(state["closing"])
        self.c.post("/api/heartbeat")
        self.assertIsNone(state["closing"])
        self.c.post("/api/window")
        self.assertGreater(state["opened"], 0.0)

    def test_a_launcher_that_attaches_its_own_handlers_is_the_one_answering(self):
        """launch.attach_lifecycle registers _heartbeat/_goodbye/_window after create_app;
        Flask keeps answering with the rule registered first, so ours hand over."""
        state = {"last": 0.0, "closing": None, "shown": 0}

        @self.app.post("/api/heartbeat")
        def _heartbeat():
            state["last"] = time.monotonic()
            state["closing"] = None
            return {"ok": True, "who": "launcher"}

        @self.app.post("/api/goodbye")
        def _goodbye():
            state["closing"] = time.monotonic()
            return "", 204

        @self.app.post("/api/window")
        def _window():
            state["shown"] += 1
            return "", 204

        c = self.app.test_client()
        self.assertEqual(c.post("/api/heartbeat").get_json()["who"], "launcher")
        self.assertGreater(state["last"], 0.0)
        self.assertEqual(c.post("/api/goodbye").status_code, 204)
        self.assertIsNotNone(state["closing"])
        self.assertEqual(c.post("/api/window").status_code, 204)
        self.assertEqual(state["shown"], 1)


# -- the background rollup ---------------------------------------------------------------------

class TestBackgroundRollup(AppCase):
    def rollup(self, delay):
        return app_mod.Rollup(self.journal, self.out, self.data / "backups", 30, delay)

    def test_disabled_means_no_timer_no_thread_no_file(self):
        r = self.rollup(None)
        r.start()
        r.schedule()
        self.assertIsNone(r._timer)
        self.assertFalse((self.out / "Baby Log.xlsx").exists())

    def test_startup_builds_once(self):
        with mock.patch.object(app_mod.threading.Thread, "start") as start:
            r = self.rollup(20)
            r.start()
        self.assertEqual(start.call_count, 2, "startup build + scan loop")
        self.assertIsNotNone(r.run())
        self.assertTrue((self.out / "Baby Log.xlsx").exists())
        self.assertIsNotNone(r.rollup_at)

    def test_schedule_debounces_into_one_build(self):
        r = self.rollup(0.15)
        with mock.patch.object(r, "run", wraps=r.run) as run:
            for _ in range(5):
                r.schedule()
            deadline = time.monotonic() + 5
            while run.call_count < 1 and time.monotonic() < deadline:
                time.sleep(0.02)
            time.sleep(0.3)
        self.assertEqual(run.call_count, 1)
        self.assertTrue((self.out / "Baby Log.xlsx").exists())

    def test_the_scan_rebuilds_only_when_the_journal_moved(self):
        r = self.rollup(20)
        self.assertFalse(r.scan_once(), "nothing in the journal, nothing to do")
        self.child()
        self.assertTrue(r.scan_once())
        self.assertFalse(r.scan_once(), "already seen")
        self.child(name="Two")                   # a file newer than the last rollup
        self.assertTrue(r.scan_once())

    def test_a_locked_workbook_is_skipped_with_a_warning(self):
        self.out.mkdir(parents=True, exist_ok=True)
        (self.out / "~$Baby Log.xlsx").write_bytes(b"")
        r = self.rollup(20)
        with self.assertLogs("baby_log", level="WARNING") as logs:
            self.assertIsNone(r.run())
        self.assertTrue(any("open in Excel" in line for line in logs.output))
        self.assertIsNone(r.rollup_at)

    def test_a_failing_build_is_logged_not_raised(self):
        r = self.rollup(20)
        with mock.patch.object(rollup_mod, "build", side_effect=OSError("disk gone")):
            with self.assertLogs("baby_log", level="WARNING") as logs:
                self.assertIsNone(r.run())
                self.assertFalse(r.scan_once())
        self.assertTrue(any("disk gone" in line for line in logs.output))

    def test_create_app_starts_the_threads_when_enabled(self):
        with mock.patch.object(app_mod.threading.Thread, "start") as start:
            a = self.make_app(rollup_delay_s=20)
        self.assertTrue(a.config["rollup"].enabled)
        self.assertEqual(start.call_count, 2)


# -- isolation ---------------------------------------------------------------------------------

class TestIsolation(ChildCase):
    def test_a_full_workflow_writes_nothing_outside_the_temp_dir(self):
        before = {"root": _tree(ROOT), "data": _tree(ROOT / "data"),
                  "backups": _tree(ROOT / "data" / "backups"), "static": _tree(ROOT / "static"),
                  "docs": _tree(ROOT / "docs")}
        ev = self.event(data={"bottles": [{"kind": "formula", "ml": 22}]})
        self.c.post("/api/settings", json={"label": "Dad"})
        self.c.delete(f"/api/event/{ev['event_id']}")
        self.c.post(f"/api/event/{ev['event_id']}/restore")
        self.c.post("/api/rollup")
        self.c.post("/api/rollup")
        self.c.post(f"/api/daysheet/{D1}")
        after = {"root": _tree(ROOT), "data": _tree(ROOT / "data"),
                 "backups": _tree(ROOT / "data" / "backups"), "static": _tree(ROOT / "static"),
                 "docs": _tree(ROOT / "docs")}
        self.assertEqual(before, after)
        self.assertTrue((self.data / "settings.json").exists())
        self.assertTrue((self.data / "backups").is_dir())
        self.assertTrue((self.out / "Day sheets" / f"{D1}.html").exists())

    def test_journal_files_never_carry_the_in_memory_name(self):
        ev = self.event()
        files = list((self.journal_dir / "events").rglob("*.json"))
        self.assertEqual(len(files), 1)
        self.assertNotIn("_file", json.loads(files[0].read_text(encoding="utf-8")))
        self.assertEqual(files[0].name, ev["_file"])


# -- main --------------------------------------------------------------------------------------

class TestMain(AppCase):
    """main() would start the real background threads; they are stubbed so nothing runs on
    after the test and the temp folder can be removed."""

    def test_serves_on_the_configured_port(self):
        with mock.patch.object(app_mod.Flask, "run") as run, \
                mock.patch.object(app_mod.Rollup, "start"):
            app_mod.main(["--config", str(self.cfg), "--app-folder", str(self.journal_dir),
                          "--output-folder", str(self.out)])
        run.assert_called_once()
        self.assertEqual(run.call_args.kwargs["host"], "127.0.0.1")
        self.assertEqual(run.call_args.kwargs["port"], 8766)

    def test_bind_lan_serves_the_home_network(self):
        self.cfg.write_text(self.cfg.read_text(encoding="utf-8").replace("bind_lan: false",
                                                                        "bind_lan: true"),
                            encoding="utf-8")
        with mock.patch.object(app_mod.Flask, "run") as run, \
                mock.patch.object(app_mod.Rollup, "start"):
            app_mod.main(["--config", str(self.cfg), "--app-folder", str(self.journal_dir),
                          "--output-folder", str(self.out), "--port", "9000"])
        self.assertEqual(run.call_args.kwargs["host"], "0.0.0.0")
        self.assertEqual(run.call_args.kwargs["port"], 9000)


if __name__ == "__main__":
    unittest.main(verbosity=1)
