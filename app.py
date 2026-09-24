"""
app.py — the local web server.

Serves the PC front end and its JSON API at http://127.0.0.1:8766 (SPEC.md §6.1). The journal in
the OneDrive app folder (store.py) is the only thing written to on a request; `Baby Log.xlsx` and
the day sheets in Yisen File are regenerated from it by rollup.py in a background thread — at
startup, 20 s after any API write, and whenever a 60 s scan finds a file newer than the last
rollup, because the phones' entries arrive through the OneDrive client with no API call at all.

The app is a factory (create_app) so the tests can inject a temp journal, a temp output folder and
a temp data folder, and switch the background threads off. launch.py calls create_app(config)
with the config path alone and reads STATIC_DIR for the tray icon.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import threading
import time as _time
from datetime import datetime
from pathlib import Path

import yaml
from flask import Flask, Response, jsonify, request, send_from_directory

import rollup as rollup_mod
import store as store_mod

VERSION = "1.0.0"

log = logging.getLogger("baby_log")


def _resource_dir():
    """Where the bundled read-only files live. Packaged, PyInstaller unpacks them to a temp
    folder and points sys._MEIPASS at it; from source they sit beside this file."""
    base = getattr(sys, "_MEIPASS", None)
    return Path(base) if base else Path(__file__).resolve().parent


STATIC_DIR = _resource_dir() / "static"
CORE_JS = _resource_dir() / "docs" / "core.js"

# The one settings shape every device has (§6.1). The phone adds `device`; the PC does not.
SETTINGS_DEFAULTS = {
    "label": "", "units": "ml", "step_ml": None, "quick_mode": "recent", "quick_custom": [],
    "night_from": "21:00", "night_to": "07:00", "child_id": None,
}

# The rhythm of the background rollup (§6.1). The scan is what picks up the phones' files.
SCAN_INTERVAL_S = 60.0

# The only fields a client may send for an event; everything else is stamped here.
EVENT_FIELDS = {"event_id", "child_id", "type", "time", "end", "data", "note", "logged_by"}
CHILD_FIELDS = {"child_id", "name", "born", "born_time", "sex", "birth_weight_g", "targets"}


def _load_cfg(config_path):
    with open(config_path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _now_local():
    return datetime.now().astimezone()


def _today():
    return _now_local().strftime("%Y-%m-%d")


def _date_arg(value, default=None):
    """A `YYYY-MM-DD` query argument, or ValueError."""
    if value in (None, ""):
        if default is None:
            raise ValueError("a date is required")
        return default
    if not isinstance(value, str) or not store_mod.DATE_RE.match(value):
        raise ValueError(f"date must be YYYY-MM-DD, got {value!r}")
    datetime.strptime(value, "%Y-%m-%d")
    return value


# -- settings ---------------------------------------------------------------------------------

def validate_settings(patch):
    """The listed keys only, each with its shape; ValueError names the first bad one."""
    if not isinstance(patch, dict):
        raise ValueError("settings must be an object")
    for k, v in patch.items():
        if k not in SETTINGS_DEFAULTS:
            raise ValueError(f"unknown setting {k!r}")
        if k == "label" and not isinstance(v, str):
            raise ValueError("label must be a string")
        if k == "units" and v not in ("ml", "oz"):
            raise ValueError("units must be ml or oz")
        if k == "step_ml" and v is not None and (not _is_number(v) or v <= 0):
            raise ValueError("step_ml must be null or a number > 0")
        if k == "quick_mode" and v not in ("recent", "custom"):
            raise ValueError("quick_mode must be recent or custom")
        if k == "quick_custom" and (not isinstance(v, list)
                                    or any(not _is_number(x) or x <= 0 for x in v)):
            raise ValueError("quick_custom must be a list of numbers > 0")
        if k in ("night_from", "night_to"):
            if not isinstance(v, str) or not store_mod.HHMM_RE.match(v):
                raise ValueError(f"{k} must be HH:MM")
            datetime.strptime(v, "%H:%M")
        if k == "child_id" and v is not None and (not isinstance(v, str) or not v):
            raise ValueError("child_id must be null or a string")
    return patch


class Settings:
    """`data/settings.json`: read on every access (the file is tiny, and a hand edit while the
    app runs should win), written through a temp file like everything else."""

    def __init__(self, path):
        self.path = Path(path)

    def read(self):
        out = dict(SETTINGS_DEFAULTS)
        try:
            saved = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            saved = {}
        if isinstance(saved, dict):
            out.update({k: v for k, v in saved.items() if k in SETTINGS_DEFAULTS})
        return out

    def update(self, patch):
        merged = self.read()
        merged.update(validate_settings(patch))
        store_mod._atomic_write_json(self.path, merged)
        return merged


# -- the background rollup --------------------------------------------------------------------

class Rollup:
    """One debounced worker for every reason the workbook is rebuilt. Nothing here raises: a
    failed rebuild is logged and tried again on the next trigger, because a request must never
    fail over a file that is merely a convenience copy of the journal."""

    def __init__(self, journal, output_folder, backup_dir, keep, delay_s):
        self.journal = journal
        self.output_folder = Path(output_folder)
        self.backup_dir = Path(backup_dir)
        self.keep = keep
        self.delay_s = delay_s
        self.enabled = delay_s is not None
        self.rollup_at = None
        self.newest_seen = None
        self._build_lock = threading.Lock()
        self._timer_lock = threading.Lock()
        self._timer = None

    def start(self):
        if not self.enabled:
            return
        threading.Thread(target=self.run, name="rollup-startup", daemon=True).start()
        threading.Thread(target=self._scan_forever, name="rollup-scan", daemon=True).start()

    def run(self):
        """Rebuild now, on this thread. Returns the summary or None."""
        with self._build_lock:
            try:
                if rollup_mod.is_locked(self.output_folder):
                    log.warning("rollup skipped: %s is open in Excel", rollup_mod.WORKBOOK)
                    return None
                newest = self.journal.stats().get("newest_at")
                summary = rollup_mod.build(self.journal, self.output_folder, self.backup_dir,
                                           self.keep)
                self.rollup_at = store_mod.now_iso()
                self.newest_seen = newest
                return summary
            except Exception as e:                    # noqa: BLE001 — logged, never raised
                log.warning("rollup failed: %s: %s", type(e).__name__, e)
                return None

    def schedule(self):
        """After an API write: one rebuild `delay_s` from the *last* write, not one per write."""
        if not self.enabled:
            return
        with self._timer_lock:
            if self._timer is not None:
                self._timer.cancel()
            self._timer = threading.Timer(self.delay_s, self.run)
            self._timer.daemon = True
            self._timer.start()

    def scan_once(self):
        """Rebuild when the journal holds a file newer than the last rollup saw — the phones'
        entries arrive through OneDrive with no API call. True when a rebuild ran."""
        try:
            newest = self.journal.stats().get("newest_at")
            if newest and (self.newest_seen is None or newest > self.newest_seen):
                return self.run() is not None
        except Exception as e:                        # noqa: BLE001
            log.warning("rollup scan failed: %s: %s", type(e).__name__, e)
        return False

    def _scan_forever(self):
        while True:
            _time.sleep(SCAN_INTERVAL_S)
            self.scan_once()


# -- the app -----------------------------------------------------------------------------------

def create_app(config_path="config.yaml", *, app_folder=None, output_folder=None, data_dir=None,
               rollup_delay_s=20):
    cfg = _load_cfg(config_path)
    paths = cfg.get("paths") or {}

    journal = store_mod.Journal(store_mod.resolve_root(cfg, app_folder)).ensure()
    out_dir = output_folder or os.environ.get("BABY_LOG_OUTPUT_FOLDER") or paths.get("output_folder")
    if not out_dir:
        raise RuntimeError("no output folder configured")
    out_dir = Path(out_dir)
    if data_dir is not None:
        data_dir = Path(data_dir)
        backup_dir = data_dir / "backups"
    else:
        data_dir = Path(paths.get("local_data") or "./data")
        backup_dir = Path(paths.get("backups") or data_dir / "backups")
    keep = int(paths.get("backup_keep", 30))
    data_dir.mkdir(parents=True, exist_ok=True)
    settings = Settings(data_dir / "settings.json")
    rollup = Rollup(journal, out_dir, backup_dir, keep, rollup_delay_s)

    app = Flask(__name__, static_folder=str(STATIC_DIR), static_url_path="/static")
    app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0        # dev: always serve fresh static files
    app.json.sort_keys = False
    app.config["journal"] = journal
    app.config["rollup"] = rollup
    app.config["lifecycle"] = {"last": _time.monotonic(), "closing": None, "opened": 0.0}

    def _err(msg, code=400):
        return jsonify({"ok": False, "error": str(msg)}), code

    def _body():
        body = request.get_json(silent=True)
        if body is None and not request.data:
            return {}
        if not isinstance(body, dict):
            raise ValueError("expected a JSON object")
        return body

    def _label():
        return settings.read().get("label") or ""

    def _current_child():
        """The device's chosen child when it is live, else the oldest live child (§3.3)."""
        kids = journal.children()
        chosen = settings.read().get("child_id")
        for k in kids:
            if k["child_id"] == chosen:
                return k
        return kids[0] if kids else None

    def _events_for(child):
        """Live events, narrowed to one child when there is more than one."""
        evs = journal.events()
        if child is None or len(journal.children()) < 2:
            return evs
        return [e for e in evs if e.get("child_id") == child["child_id"]]

    @app.errorhandler(404)
    def _not_found(e):
        if request.path.startswith("/api/"):
            return _err(f"no such route {request.path}", 404)
        return e

    # -- the page ------------------------------------------------------------
    @app.get("/")
    def index():
        return send_from_directory(STATIC_DIR, "index.html")

    @app.get("/core.js")
    def core_js():
        """The shared logic, straight from docs/ so the PC and the phone run the same bytes."""
        resp = send_from_directory(CORE_JS.parent, CORE_JS.name, mimetype="text/javascript")
        resp.headers["Cache-Control"] = "no-cache"
        return resp

    # -- config and settings -------------------------------------------------
    @app.get("/api/config")
    def api_config():
        return jsonify({"ok": True, "child": _current_child(), "children": journal.children(),
                        "settings": settings.read(), "version": VERSION,
                        "app_folder": str(journal.root), "output_folder": str(out_dir),
                        "label": _label()})

    @app.get("/api/settings")
    def api_settings():
        return jsonify({"ok": True, "settings": settings.read()})

    @app.post("/api/settings")
    def api_update_settings():
        try:
            merged = settings.update(_body())
        except ValueError as e:
            return _err(e, 400)
        return jsonify({"ok": True, "settings": merged})

    # -- the now panel -------------------------------------------------------
    @app.get("/api/now")
    def api_now():
        now = _now_local()
        child = _current_child()
        evs = _events_for(child)
        last_feed = rollup_mod.last_of(evs, "feed", now)
        gap = rollup_mod.usual_gap_ms(evs, "feed")
        return jsonify({
            "ok": True, "now": store_mod.iso_local(now),
            "last_feed": last_feed,
            "last_diaper": rollup_mod.last_of(evs, "diaper", now),
            "running": [e for e in evs if rollup_mod.is_running(e)],
            "today": rollup_mod.totals(evs, now.strftime("%Y-%m-%d"), now),
            "usual_gap_s": None if gap is None else int(round(gap / 1000)),
            "next_feed_at": rollup_mod.next_feed_at(evs),
            "targets": (child or {}).get("targets") or dict(store_mod.CHILD_TARGETS),
        })

    # -- reading events ------------------------------------------------------
    @app.get("/api/day")
    def api_day():
        try:
            date = _date_arg(request.args.get("date"), _today())
        except ValueError as e:
            return _err(e, 400)
        now = _now_local()
        evs = journal.events()
        dates = {str(e.get("time", ""))[:10] for e in evs}
        return jsonify({"ok": True, "date": date,
                        "events": [e for e in evs if str(e.get("time", ""))[:10] == date],
                        "totals": rollup_mod.totals(evs, date, now),
                        "has_prev": any(d < date for d in dates),
                        "has_next": any(d > date for d in dates)})

    @app.get("/api/events")
    def api_events():
        try:
            d1 = _date_arg(request.args.get("from"))
            d2 = _date_arg(request.args.get("to"), d1)
        except ValueError as e:
            return _err(e, 400)
        if d2 < d1:
            return _err(f"to {d2} is before from {d1}", 400)
        return jsonify({"ok": True, "events": journal.events_between(d1, d2)})

    @app.get("/api/event/<event_id>")
    def api_event(event_id):
        rec = journal.event(event_id)
        if rec is None:
            return _err(f"no such event {event_id}", 404)
        return jsonify({"ok": True, "event": rec, "history": journal.history(event_id)})

    @app.get("/api/deleted")
    def api_deleted():
        return jsonify({"ok": True, "events": journal.deleted()})

    @app.get("/api/needs-check")
    def api_needs_check():
        return jsonify({"ok": True, "events": [e for e in journal.events()
                                               if str(e.get("note") or "").startswith("Check: ")]})

    # -- writing events ------------------------------------------------------
    @app.post("/api/event")
    def api_write_event():
        """New event, or a revision when `event_id` names one on file. The client owns the
        entry's own fields; everything about *who wrote this file* is stamped here."""
        try:
            body = _body()
        except ValueError as e:
            return _err(e, 400)
        unknown = set(body) - EVENT_FIELDS
        if unknown:
            return _err(f"unknown field {sorted(unknown)[0]!r}", 400)

        event_id = body.get("event_id")
        label = _label()
        if event_id is not None:
            if not isinstance(event_id, str) or journal.event(event_id) is None:
                return _err(f"no such event {event_id}", 404)
            edited_by = label
        else:
            edited_by = None

        child_id = body.get("child_id")
        if child_id is None:
            if event_id is not None:
                child_id = journal.event(event_id).get("child_id")
            else:
                child = _current_child()
                if child is None:
                    return _err("no child", 400)
                child_id = child["child_id"]
        elif not isinstance(child_id, str) or journal.child(child_id) is None:
            return _err(f"no such child {child_id}", 400)

        logged_by = body.get("logged_by")
        if logged_by is None and event_id is None:
            logged_by = label

        try:
            rec = journal.write_event(
                child_id=child_id, type=body.get("type"), time=body.get("time"),
                end=body.get("end"), data=body.get("data"), note=body.get("note") or "",
                logged_by=logged_by, device="pc", entered_from="pc", edited_by=edited_by,
                event_id=event_id)
        except FileExistsError as e:
            return _err(e, 409)
        except KeyError as e:
            return _err(e.args[0] if e.args else e, 404)
        except ValueError as e:
            return _err(e, 400)
        rollup.schedule()
        return jsonify({"ok": True, "event": rec}), 201

    @app.delete("/api/event/<event_id>")
    def api_delete_event(event_id):
        current = journal.event(event_id)
        if current is None:
            return _err(f"no such event {event_id}", 404)
        if current.get("deleted"):
            return _err(f"{event_id} is already deleted", 409)
        try:
            reason = _body().get("reason")
            rec = journal.delete_event(event_id, reason, device="pc", edited_by=_label())
        except ValueError as e:
            return _err(e, 400)
        rollup.schedule()
        return jsonify({"ok": True, "event": rec})

    @app.post("/api/event/<event_id>/restore")
    def api_restore_event(event_id):
        current = journal.event(event_id)
        if current is None:
            return _err(f"no such event {event_id}", 404)
        if not current.get("deleted"):
            return _err(f"{event_id} is not deleted", 409)
        try:
            rec = journal.restore_event(event_id, device="pc", edited_by=_label())
        except ValueError as e:
            return _err(e, 400)
        rollup.schedule()
        return jsonify({"ok": True, "event": rec})

    # -- children ------------------------------------------------------------
    @app.get("/api/children")
    def api_children():
        return jsonify({"ok": True, "children": journal.children()})

    @app.post("/api/children")
    def api_write_child():
        try:
            body = _body()
        except ValueError as e:
            return _err(e, 400)
        unknown = set(body) - CHILD_FIELDS
        if unknown:
            return _err(f"unknown field {sorted(unknown)[0]!r}", 400)
        child_id = body.get("child_id")
        held = journal.child(child_id) if child_id is not None else None
        if child_id is not None and held is None:
            return _err(f"no such child {child_id}", 404)
        # A revision keeps whatever the form did not send, so a targets-only edit cannot
        # blank the name.
        fields = {k: held.get(k) for k in ("name", "born", "born_time", "sex", "birth_weight_g",
                                           "targets")} if held else {}
        fields.update({k: v for k, v in body.items() if k != "child_id"})
        try:
            rec = journal.write_child(child_id=child_id, device="pc", **fields)
        except TypeError as e:
            return _err(e, 400)
        except KeyError as e:
            return _err(e.args[0] if e.args else e, 404)
        except ValueError as e:
            return _err(e, 400)
        rollup.schedule()
        return jsonify({"ok": True, "child": rec}), 201

    # -- the readable files --------------------------------------------------
    @app.post("/api/rollup")
    def api_rollup():
        try:
            summary = rollup_mod.build(journal, out_dir, backup_dir, keep)
        except RuntimeError as e:
            return _err(e, 409)
        except Exception as e:                        # noqa: BLE001 — surface the real reason
            return _err(f"{type(e).__name__}: {e}", 500)
        rollup.rollup_at = store_mod.now_iso()
        rollup.newest_seen = journal.stats().get("newest_at")
        return jsonify({"ok": True, "path": summary["path"], "summary": summary})

    @app.post("/api/daysheet/<date>")
    def api_daysheet(date):
        try:
            date = _date_arg(date)
            path = rollup_mod.write_day_sheet(journal, out_dir, date, settings.read(),
                                              child=_current_child())
        except ValueError as e:
            return _err(e, 400)
        except RuntimeError as e:
            return _err(e, 409)
        except OSError as e:
            return _err(f"{type(e).__name__}: {e}", 500)
        return jsonify({"ok": True, "path": str(path)})

    @app.get("/print/day/<date>")
    def print_day(date):
        try:
            date = _date_arg(date)
        except ValueError as e:
            return Response(str(e), status=400, mimetype="text/plain")
        html = rollup_mod.day_sheet_html(_current_child(), journal.events(), date, settings.read())
        return Response(html, mimetype="text/html")

    @app.get("/print/range")
    def print_range():
        try:
            d2 = _date_arg(request.args.get("to"), _today())
            d1 = _date_arg(request.args.get("from"), d2)
        except ValueError as e:
            return Response(str(e), status=400, mimetype="text/plain")
        if d2 < d1:
            return Response(f"to {d2} is before from {d1}", status=400, mimetype="text/plain")
        rows = rollup_mod.daily_rows(journal.events(), d1, d2, _now_local())
        return Response(rollup_mod.range_html(_current_child(), rows, d1, d2, settings.read()),
                        mimetype="text/html")

    # -- status --------------------------------------------------------------
    @app.get("/api/health")
    def api_health():
        stats = journal.stats()
        return jsonify({"ok": True, "journal": stats, "newest_file_at": stats.get("newest_at"),
                        "rollup_at": rollup.rollup_at, "version": VERSION})

    # -- lifecycle -----------------------------------------------------------
    # launch.py attaches its own /api/heartbeat, /api/goodbye and /api/window (endpoints
    # `_heartbeat`, `_goodbye`, `_window`) after create_app returns, and Flask answers with the
    # rule registered first — these. So each one hands over to the launcher's function when it
    # exists, and merely keeps a note otherwise, so `python app.py` answers the page too.
    def _delegate(endpoint, fallback):
        other = app.view_functions.get(endpoint)
        return other() if other is not None else fallback()

    @app.post("/api/heartbeat")
    def api_heartbeat():
        def note():
            state = app.config["lifecycle"]
            state["last"] = _time.monotonic()
            state["closing"] = None
            return {"ok": True}
        return _delegate("_heartbeat", note)

    @app.post("/api/goodbye")
    def api_goodbye():
        def note():
            app.config["lifecycle"]["closing"] = _time.monotonic()
            return "", 204
        return _delegate("_goodbye", note)

    @app.post("/api/window")
    def api_window():
        def note():
            app.config["lifecycle"]["opened"] = _time.monotonic()
            return "", 204
        return _delegate("_window", note)

    rollup.start()
    return app


def main(argv=None):
    ap = argparse.ArgumentParser(description="Baby Log — local server")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--host", help="override server host")
    ap.add_argument("--port", type=int, help="override server port")
    ap.add_argument("--app-folder", help="journal root (also BABY_LOG_APP_FOLDER)")
    ap.add_argument("--output-folder", help="Yisen File folder (also BABY_LOG_OUTPUT_FOLDER)")
    a = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = _load_cfg(a.config)
    srv = cfg.get("server", {})
    host = a.host or ("0.0.0.0" if srv.get("bind_lan") else srv.get("host", "127.0.0.1"))
    port = a.port or int(srv.get("port", 8766))

    app = create_app(a.config, app_folder=a.app_folder, output_folder=a.output_folder)
    print(f"Baby Log  →  http://{host}:{port}")
    print(f"  journal : {app.config['journal'].root}")
    print(f"  output  : {app.config['rollup'].output_folder}")
    app.run(host=host, port=port, debug=False)


if __name__ == "__main__":
    main()
