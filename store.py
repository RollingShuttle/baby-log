"""
store.py — the journal.

An append-only folder of small immutable JSON files in the OneDrive app folder that both phones
and the PC reach. Nothing is edited in place: a correction is a new revision file, a deletion is a
tombstone revision, and every write gets a fresh random suffix, so two devices writing the same
revision in the same second produce two files and OneDrive never has to pick a winner.

  children/   C-<stamp>-<rand>-r<n>-<w>.json                one child; revisions for edits
  events/     <YYYY-MM-DD>/E-<stamp>-<rand>-r<n>-<w>.json   one feed / diaper / … per file
  meta/       (reserved; nothing in v1)

The day folder is the UTC date of the *write*, not the event's date — that is what lets a phone
find every change by listing only the folders since its last pull. Readers resolve each id to one
record with the ordering rule in SPEC.md §3.4. See SPEC.md §3 and §4.
"""
from __future__ import annotations

import copy
import json
import math
import os
import re
import secrets
import tempfile
import threading
import time as _time
from datetime import datetime, timezone
from pathlib import Path

import yaml

SUBDIRS = ("children", "events", "meta")

# §3.1. `<rev>` is decimal with no padding, so a leading zero is not a journal file. Kept
# case-sensitive on purpose: `<w>` is lower-case hex and an upper-case name is not ours.
NAME_RE = re.compile(r"^(?P<id>[EC]-.+)-r(?P<rev>[1-9]\d*)-(?P<w>[0-9a-f]{4})\.json$")

# §3.2. Whole seconds, numeric offset, never Z, never fractional seconds.
TIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}$")
# created_at is fixed width so ties break by plain string comparison.
CREATED_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}\+00:00$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
HHMM_RE = re.compile(r"^\d{2}:\d{2}$")

TYPES = ("feed", "diaper", "sleep", "pump", "growth", "health", "note")
ENTERED_FROM = ("pc", "phone", "paper")

DEFAULTS = {
    "feed": {"breast": {"left_s": None, "right_s": None, "total_s": None, "last_side": None,
                        "approx": False},
             "bottles": [], "made_ml": None, "leftover_ml": None, "timer": None},
    "diaper": {"wet": False, "dirty": False, "color": None, "texture": None, "size": None,
               "rash": False, "blowout": False},
    "sleep": {"where": None, "timer": None},
    "pump": {"left_ml": None, "right_ml": None, "minutes": None},
    "growth": {"weight_g": None, "length_cm": None, "head_cm": None},
    "health": {"temp_c": None, "medicine": None, "dose": None, "symptom": None},
    "note": {"milestone": False},
}

ENUMS = {
    "bottle_kind": ("formula", "breast_milk"),
    "side": ("left", "right"),
    "color": ("black", "dark_green", "green", "yellow", "brown", "other"),
    "texture": ("sticky", "seedy", "soft", "solid", "watery"),
    "size": ("small", "medium", "large"),
}

CHILD_TARGETS = {"feeds_per_day": None, "wet_per_day": None, "dirty_per_day": None}

# The end-not-null rule (§3.4) applies only to the types that have an end at all.
TIMED_TYPES = ("feed", "sleep", "pump")

# How long a scan stays fresh. Phones' files arrive through the OneDrive client at their own
# pace, so a rescan every couple of seconds is plenty; re-statting every file on every request
# is not.
SCAN_TTL_S = 2.0


# -- names, stamps and times ----------------------------------------------------------------

def stamp(dt=None):
    """UTC `YYYYMMDD-HHMMSS`, the timestamp part of every id."""
    return (dt or datetime.now(timezone.utc)).astimezone(timezone.utc).strftime("%Y%m%d-%H%M%S")


def rand4():
    return secrets.token_hex(2)


def parse_name(name):
    """`{id, rev, w}` for a journal filename, or None for anything else — OneDrive's temp files,
    our own `*.tmp`, and whatever else drifts into the folder."""
    m = NAME_RE.match(name)
    if not m:
        return None
    return {"id": m.group("id"), "rev": int(m.group("rev")), "w": m.group("w")}


def now_iso():
    """Microsecond precision, deliberately. Second-resolution timestamps tie when two records are
    created in the same second, and ordering would then fall back to a random filename suffix."""
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def iso_local(dt):
    """The §3.2 shape for an instant: whole seconds and the zone's offset *on that date*, so an
    entry edited in November keeps its September offset. A naive datetime is local wall-clock
    time; an aware one keeps the zone it came with."""
    if dt.tzinfo is None or dt.utcoffset() is None:
        dt = dt.astimezone()
    return dt.replace(microsecond=0).isoformat(timespec="seconds")


def validate_time(s):
    """The exact `YYYY-MM-DDTHH:MM:SS±HH:MM` shape; returns the aware datetime. Anything else —
    `Z`, fractional seconds, a bare date, a number — is refused rather than repaired, because a
    writer that rewrites times is a writer that changes them."""
    if not isinstance(s, str) or not TIME_RE.match(s):
        raise ValueError(f"time must be YYYY-MM-DDTHH:MM:SS±HH:MM, got {s!r}")
    try:
        return datetime.fromisoformat(s)
    except ValueError as e:
        raise ValueError(f"time is not a real date-time: {s!r} ({e})") from None


def _instant(s):
    """Seconds since the epoch for sorting, or 0 for anything unparsable — a child record has no
    time at all, and a foreign file must not crash the reader."""
    try:
        return datetime.fromisoformat(s).timestamp()
    except (TypeError, ValueError):
        return 0.0


# -- data validation --------------------------------------------------------------------------

def _is_number(v):
    # bool is an int in Python; `left_s: true` is still not a number of seconds.
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _amount(v, path, positive=False):
    if v is None and not positive:
        return
    if not _is_number(v) or v < 0 or (positive and v <= 0):
        want = "a number > 0" if positive else "null or a number >= 0"
        raise ValueError(f"data.{path} must be {want}, got {v!r}")


def _bool(v, path):
    if not isinstance(v, bool):
        raise ValueError(f"data.{path} must be true or false, got {v!r}")


def _enum(v, path, name):
    if v is not None and v not in ENUMS[name]:
        raise ValueError(f"data.{path} must be one of {', '.join(ENUMS[name])} or null, got {v!r}")


def _text(v, path):
    if v is not None and not isinstance(v, str):
        raise ValueError(f"data.{path} must be a string or null, got {v!r}")


def _object(v, path, keys):
    """A nested object with exactly these keys — the timer shapes."""
    if not isinstance(v, dict):
        raise ValueError(f"data.{path} must be an object or null, got {v!r}")
    unknown = set(v) - set(keys)
    if unknown:
        raise ValueError(f"data.{path} has unknown key {sorted(unknown)[0]!r}")
    missing = set(keys) - set(v)
    if missing:
        raise ValueError(f"data.{path} is missing {sorted(missing)[0]!r}")


def _merge(base, data, path="data"):
    """Deep-merge the caller's data over the defaults. Objects merge, arrays and scalars replace,
    and a key the defaults do not know is refused at any depth — a typo like `left_ml` for the
    leftover must fail loudly, not be stored and never shown."""
    if not isinstance(data, dict):
        raise ValueError(f"{path} must be an object, got {data!r}")
    for k, v in data.items():
        if k not in base:
            raise ValueError(f"{path}.{k} is not a known key")
        if isinstance(base[k], dict) and isinstance(v, dict):
            _merge(base[k], v, f"{path}.{k}")
        else:
            base[k] = copy.deepcopy(v)
    return base


def _check_feed(d):
    b = d["breast"]
    if not isinstance(b, dict):
        raise ValueError("data.breast must be an object")
    for k in ("left_s", "right_s", "total_s"):
        _amount(b[k], f"breast.{k}")
    _enum(b["last_side"], "breast.last_side", "side")
    _bool(b["approx"], "breast.approx")
    if not isinstance(d["bottles"], list):
        raise ValueError("data.bottles must be a list")
    for i, p in enumerate(d["bottles"]):
        # `formula` is optional on the way in (older records and the paper import carry only
        # kind and ml) and always present on the way out, so every stored portion has one shape.
        if isinstance(p, dict) and "formula" not in p:
            p["formula"] = None
        _object(p, f"bottles[{i}]", ("kind", "ml", "formula"))
        if p["kind"] not in ENUMS["bottle_kind"]:
            raise ValueError(f"data.bottles[{i}].kind must be formula or breast_milk, got {p['kind']!r}")
        _amount(p["ml"], f"bottles[{i}].ml", positive=True)
        f = p["formula"]
        if f is not None and (not isinstance(f, str) or f == ""):
            raise ValueError(f"data.bottles[{i}].formula must be a non-empty string or null, got {f!r}")
    _amount(d["made_ml"], "made_ml")
    _amount(d["leftover_ml"], "leftover_ml")
    if d["timer"] is not None:
        _object(d["timer"], "timer", ("side", "side_started"))
        if d["timer"]["side"] not in ENUMS["side"]:
            raise ValueError(f"data.timer.side must be left or right, got {d['timer']['side']!r}")
        try:
            validate_time(d["timer"]["side_started"])
        except ValueError as e:
            raise ValueError(f"data.timer.side_started: {e}") from None


def _check_diaper(d):
    for k in ("wet", "dirty", "rash", "blowout"):
        _bool(d[k], k)
    for k in ("color", "texture", "size"):
        _enum(d[k], k, k)


def _check_sleep(d):
    _text(d["where"], "where")
    if d["timer"] is not None:
        _object(d["timer"], "timer", ("running",))
        if d["timer"]["running"] is not True:
            raise ValueError("data.timer must be exactly {\"running\": true} or null")


def _check_amounts(keys):
    def check(d):
        for k in keys:
            _amount(d[k], k)
    return check


def _check_health(d):
    _amount(d["temp_c"], "temp_c")
    for k in ("medicine", "dose", "symptom"):
        _text(d[k], k)


def _check_note(d):
    _bool(d["milestone"], "milestone")


_CHECKS = {
    "feed": _check_feed,
    "diaper": _check_diaper,
    "sleep": _check_sleep,
    "pump": _check_amounts(("left_ml", "right_ml", "minutes")),
    "growth": _check_amounts(("weight_g", "length_cm", "head_cm")),
    "health": _check_health,
    "note": _check_note,
}


def validate_data(type, data):
    """The full `data` object for a type — the caller's values merged over the defaults — or a
    ValueError with the offending key. Identical in rule to Core.validate (§3.2); the shared
    fixture in tests/fixtures/data_cases.json holds both to it."""
    if type not in DEFAULTS:
        raise ValueError(f"unknown type {type!r}")
    merged = _merge(copy.deepcopy(DEFAULTS[type]), {} if data is None else data)
    _CHECKS[type](merged)
    return merged


# -- resolution -------------------------------------------------------------------------------

# Only the tail of the name matters for the tiebreak; the id part is whatever the record says.
_W_RE = re.compile(r"-r\d+-([0-9a-f]{4})\.json$")


def _rank(rec):
    """The §3.4 ordering key. A stopped feed beats a running one at the same revision because a
    Stop must never be undone by a concurrent Switch; after that the later write wins."""
    ended = 1 if rec.get("type") in TIMED_TYPES and rec.get("end") is not None else 0
    m = _W_RE.search(str(rec.get("_file") or ""))
    return (int(rec.get("revision") or 0), ended, str(rec.get("created_at") or ""),
            str(rec.get("device") or ""), m.group(1) if m else "")


def resolve(records, key="event_id"):
    """`dict id -> winning record`, tombstones kept."""
    best = {}
    for rec in records:
        rid = rec.get(key)
        if rid is None:
            continue
        if rid not in best or _rank(rec) > _rank(best[rid]):
            best[rid] = rec
    return best


def live(records, key="event_id"):
    """The resolved records that are not deleted, sorted by `time` as an instant, ties by id."""
    out = [r for r in resolve(records, key).values() if not r.get("deleted")]
    out.sort(key=lambda r: (_instant(r.get("time")), str(r.get(key))))
    return out


# -- files ------------------------------------------------------------------------------------

def _atomic_write_json(path, payload):
    """Write via a temp file in the same directory, then replace. A half-written journal file
    would be worse than a missing one, and os.replace is atomic on Windows and POSIX alike. The
    temp name ends in `.tmp` because the OneDrive client does not upload those."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=1, sort_keys=True)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return path


def _public(rec):
    """The record as written to disk: `_file` lives only in memory."""
    return {k: v for k, v in rec.items() if k != "_file"}


class Journal:
    def __init__(self, root):
        self.root = Path(root)
        # path -> (size, mtime_ns, record). Unreadable files are never entered, so they are
        # retried on every scan rather than remembered as absent.
        self._index = {}
        self._unreadable = []
        self._files = 0
        self._scanned_at = None
        self._resolved = None
        # One Journal serves Flask's request threads, the 60 s scan and the post-write timer.
        # Without this a write landing mid-iteration raised "dictionary changed size during
        # iteration" (a 500), and a write landing mid-rescan vanished until the next scan.
        # Re-entrant because the writers call the readers while they hold it.
        self._lock = threading.RLock()

    # -- setup ---------------------------------------------------------------
    def ensure(self):
        for d in SUBDIRS:
            (self.root / d).mkdir(parents=True, exist_ok=True)
        return self

    def _dir(self, name):
        return self.root / name

    # -- reading -------------------------------------------------------------
    def _candidate_files(self):
        """Every `*.json` under children/ and events/<day>/. A folder that cannot be listed (a
        placeholder OneDrive has not materialised) is skipped, not fatal."""
        for p in self._list(self._dir("children")):
            if p.is_file() and p.suffix == ".json":
                yield p
        for day in self._list(self._dir("events")):
            if day.is_dir():
                for p in self._list(day):
                    if p.is_file() and p.suffix == ".json":
                        yield p

    @staticmethod
    def _list(folder):
        try:
            return sorted(folder.iterdir())
        except OSError:
            return []

    def _read(self, path):
        text = path.read_text(encoding="utf-8")
        rec = json.loads(text)
        if not isinstance(rec, dict):
            raise ValueError("journal file is not an object")
        rec["_file"] = path.name
        return rec

    def load(self, force=False):
        """Rescan the tree, parsing only files whose (path, size, mtime) changed since last time.
        The scan is skipped while the last one is fresh (SCAN_TTL_S) unless forced. The whole
        scan holds the lock, so a write on another thread waits and then lands in the new
        index instead of the one about to be thrown away."""
        with self._lock:
            if not force and self._scanned_at is not None and \
                    _time.monotonic() - self._scanned_at < SCAN_TTL_S:
                return self
            index, unreadable, files = {}, [], 0
            for p in self._candidate_files():
                files += 1
                key = str(p)
                if parse_name(p.name) is None:
                    continue
                try:
                    st = p.stat()
                    known = self._index.get(key)
                    if known and known[0] == st.st_size and known[1] == st.st_mtime_ns:
                        index[key] = known
                        continue
                    index[key] = (st.st_size, st.st_mtime_ns, self._read(p))
                except (OSError, ValueError):
                    # Files-On-Demand placeholder, zero bytes mid-download, half-written: skip
                    # it this time and look again next scan.
                    unreadable.append(p.name)
            self._index, self._unreadable, self._files = index, unreadable, files
            self._scanned_at = _time.monotonic()
            self._resolved = None
            return self

    def _remember(self, path, rec):
        """Put a file this process just wrote straight into the index; no rescan needed."""
        with self._lock:
            st = path.stat()
            self._index[str(path)] = (st.st_size, st.st_mtime_ns, rec)
            self._files += 1
            self._resolved = None

    def _records(self):
        """Every indexed record, copied under the lock: a request thread iterates the copy
        while a write on another thread adds to the dict."""
        with self._lock:
            self.load()
            return [rec for (_, _, rec) in self._index.values()]

    def _all_events(self):
        return [rec for rec in self._records() if "event_id" in rec]

    def _all_children(self):
        # An event carries a child_id too; a child record is the one with no event_id.
        return [rec for rec in self._records() if "child_id" in rec and "event_id" not in rec]

    def _resolved_events(self):
        # Under the lock too: a _remember between the snapshot and the assignment would
        # otherwise leave a resolved map that lacks the write it just cleared the cache for.
        with self._lock:
            self.load()
            if self._resolved is None:
                self._resolved = resolve(self._all_events(), "event_id")
            return self._resolved

    def _highest_revision(self, event_id):
        return max((int(r.get("revision") or 0) for r in self._all_events()
                    if r.get("event_id") == event_id), default=0)

    # -- children ------------------------------------------------------------
    def write_child(self, *, name, born, born_time=None, sex=None, birth_weight_g=None,
                    targets=None, child_id=None, device="pc"):
        """Create a child, or revise one when child_id is given. Targets are what the
        pediatrician said, merged over null defaults; the app never invents them."""
        if not isinstance(name, str) or not name.strip():
            raise ValueError("name must be a non-empty string")
        if not isinstance(born, str) or not DATE_RE.match(born):
            raise ValueError(f"born must be YYYY-MM-DD, got {born!r}")
        datetime.strptime(born, "%Y-%m-%d")
        if born_time is not None:
            if not isinstance(born_time, str) or not HHMM_RE.match(born_time):
                raise ValueError(f"born_time must be HH:MM or null, got {born_time!r}")
            datetime.strptime(born_time, "%H:%M")
        _text(sex, "sex")
        _amount(birth_weight_g, "birth_weight_g")
        merged = _merge(dict(CHILD_TARGETS), {} if targets is None else targets, "targets")
        for k, v in merged.items():
            _amount(v, f"targets.{k}")
        if not isinstance(device, str) or not device:
            raise ValueError("device must be a string")

        # The revision lookup and the write are one step, or two threads revising the same
        # child would both compute r2.
        with self._lock:
            if child_id is None:
                child_id = f"C-{stamp()}-{rand4()}"
                revision = 1
            else:
                highest = max((int(r.get("revision") or 0) for r in self._all_children()
                               if r.get("child_id") == child_id), default=0)
                if highest == 0:
                    raise KeyError(f"no such child {child_id}")
                revision = highest + 1

            rec = {
                "child_id": child_id, "revision": revision, "deleted": False, "reason": None,
                "name": name, "born": born, "born_time": born_time, "sex": sex,
                "birth_weight_g": birth_weight_g, "targets": merged,
                "device": device, "created_at": now_iso(),
            }
            path = self._dir("children") / f"{child_id}-r{revision}-{rand4()}.json"
            _atomic_write_json(path, rec)
            rec["_file"] = path.name
            self._remember(path, rec)
            return rec

    def children(self):
        """Live children, oldest id first — the first one is the current child."""
        return live(self._all_children(), "child_id")

    def child(self, child_id):
        return resolve(self._all_children(), "child_id").get(child_id)

    # -- events --------------------------------------------------------------
    def write_event(self, *, child_id, type, time, end=None, data=None, note="", logged_by=None,
                    device="pc", entered_from="pc", edited_by=None, event_id=None, revision=None,
                    reason=None, deleted=False):
        """Record one event, or a revision of one when event_id is given.

        A new event gets `E-<stamp>-<rand4>` — the random suffix is load-bearing: two devices
        logging in the same second must not share an id, and the same id would mean the same
        filename. A revision is `highest on file + 1` and carries `logged_by` unless the editor
        changed it. An explicit `revision=1` against an id already on file is refused, which is
        the paper import's second line of defence against importing twice.
        """
        if type not in DEFAULTS:
            raise ValueError(f"unknown type {type!r}")
        if not isinstance(child_id, str) or not child_id:
            raise ValueError("child_id must be a string")
        started = validate_time(time)
        if end is not None and validate_time(end) < started:
            raise ValueError(f"end {end!r} is earlier than time {time!r}")
        data = validate_data(type, data)
        if not isinstance(note, str):
            raise ValueError("note must be a string")
        if logged_by is not None and not isinstance(logged_by, str):
            raise ValueError("logged_by must be a string")
        if edited_by is not None and not isinstance(edited_by, str):
            raise ValueError("edited_by must be a string or null")
        if not isinstance(device, str) or not device:
            raise ValueError("device must be a string")
        if entered_from not in ENTERED_FROM:
            raise ValueError(f"entered_from must be one of {', '.join(ENTERED_FROM)}")
        if reason is not None and not isinstance(reason, str):
            raise ValueError("reason must be a string or null")
        if not isinstance(deleted, bool):
            raise ValueError("deleted must be true or false")

        # From the highest-revision lookup to the write is one critical section: a Stop on the
        # PC and a Switch from the scan's rescan must not both read r1 and both write r2.
        with self._lock:
            if event_id is None:
                event_id = f"E-{stamp()}-{rand4()}"
                revision = 1
            else:
                if not isinstance(event_id, str) or not event_id.startswith("E-"):
                    raise ValueError(f"event_id must start with E-, got {event_id!r}")
                highest = self._highest_revision(event_id)
                if revision is None:
                    if highest == 0:
                        raise KeyError(f"no such event {event_id}")
                    revision = highest + 1
                elif int(revision) <= highest:
                    raise FileExistsError(
                        f"refusing to overwrite revision {revision} of {event_id}: r{highest} "
                        "is on file. Journal files are immutable; write a new revision instead.")
                else:
                    revision = int(revision)
                if logged_by is None and highest:
                    logged_by = self._resolved_events()[event_id].get("logged_by")
            if logged_by is None:
                raise ValueError("logged_by is required for a new event")

            rec = {
                "event_id": event_id,
                "revision": revision,
                "deleted": deleted,
                "reason": reason,
                "child_id": child_id,
                "type": type,
                "time": time,
                "end": end,
                "data": data,
                "note": note,
                "logged_by": logged_by,
                "edited_by": edited_by,
                "device": device,
                "entered_from": entered_from,
                "created_at": now_iso(),
            }
            return self._write_event_file(rec)

    def _write_event_file(self, rec):
        # The day folder is the UTC date of the write, not the event's date (§3.1).
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        path = self._dir("events") / day / f"{rec['event_id']}-r{rec['revision']}-{rand4()}.json"
        _atomic_write_json(path, _public(rec))
        rec["_file"] = path.name
        self._remember(path, rec)
        return rec

    def _restamp(self, rec, *, device, edited_by, entered_from):
        if not isinstance(device, str) or not device:
            raise ValueError("device must be a string")
        if edited_by is not None and not isinstance(edited_by, str):
            raise ValueError("edited_by must be a string or null")
        if entered_from is None:
            entered_from = "pc" if device == "pc" else "phone"
        if entered_from not in ENTERED_FROM:
            raise ValueError(f"entered_from must be one of {', '.join(ENTERED_FROM)}")
        rec.update(device=device, edited_by=edited_by, entered_from=entered_from,
                   created_at=now_iso())
        return rec

    def delete_event(self, event_id, reason=None, *, device, edited_by, entered_from=None):
        """A tombstone: the latest record with every field carried, one revision up. Deleting
        something already deleted is an error (API 409), not a second tombstone."""
        with self._lock:
            latest = self.event(event_id)
            if latest is None:
                raise KeyError(f"no such event {event_id}")
            if latest.get("deleted"):
                raise ValueError(f"{event_id} is already deleted")
            if reason is not None and not isinstance(reason, str):
                raise ValueError("reason must be a string or null")
            rec = copy.deepcopy(_public(latest))
            rec.update(revision=self._highest_revision(event_id) + 1, deleted=True,
                       reason=reason)
            self._restamp(rec, device=device, edited_by=edited_by, entered_from=entered_from)
            return self._write_event_file(rec)

    def restore_event(self, event_id, *, device, edited_by, entered_from=None):
        """Bring a deleted event back as a new revision copied from the latest non-deleted one
        (the tombstone's own body when there is none). Restoring a live event is an error."""
        with self._lock:
            latest = self.event(event_id)
            if latest is None:
                raise KeyError(f"no such event {event_id}")
            if not latest.get("deleted"):
                raise ValueError(f"{event_id} is not deleted")
            alive = [r for r in self.history(event_id) if not r.get("deleted")]
            base = max(alive, key=_rank) if alive else latest
            rec = copy.deepcopy(_public(base))
            rec.update(revision=self._highest_revision(event_id) + 1, deleted=False, reason=None)
            self._restamp(rec, device=device, edited_by=edited_by, entered_from=entered_from)
            return self._write_event_file(rec)

    def events(self):
        """Every live event, oldest first."""
        return live(self._all_events(), "event_id")

    def events_on(self, date):
        """The writer's local date is the first ten characters of `time`; no zone arithmetic."""
        return [e for e in self.events() if str(e.get("time", ""))[:10] == date]

    def events_between(self, d1, d2):
        return [e for e in self.events() if d1 <= str(e.get("time", ""))[:10] <= d2]

    def event(self, event_id):
        """The resolved record, a tombstone included, or None."""
        return self._resolved_events().get(event_id)

    def history(self, event_id):
        """Every revision file for an id, ascending — duplicates of one revision included, so the
        PC's history view shows what both devices wrote."""
        recs = [r for r in self._all_events() if r.get("event_id") == event_id]
        recs.sort(key=lambda r: (int(r.get("revision") or 0), str(r.get("created_at") or "")))
        return recs

    def deleted(self):
        """Tombstoned events, newest tombstone first."""
        out = [r for r in self._resolved_events().values() if r.get("deleted")]
        out.sort(key=lambda r: (str(r.get("created_at") or ""), r.get("event_id")), reverse=True)
        return out

    def stats(self):
        with self._lock:
            recs = self._records()
            newest = max((str(r.get("created_at")) for r in recs if r.get("created_at")),
                         default=None)
            return {"events": len(self.events()), "deleted": len(self.deleted()),
                    "children": len(self.children()), "files": self._files,
                    "newest_at": newest, "unreadable": list(self._unreadable)}

    def fingerprint(self):
        """What the tree holds right now — file count, indexed count, newest mtime — so the
        rollup scan can tell that *any* file arrived. It cannot key on max(created_at): a
        phone's queued upload keeps its original created_at (§7.6), so it lands with an older
        stamp than the last PC write and still has to reach Baby Log.xlsx."""
        with self._lock:
            self.load()
            newest = max((mtime for (_, mtime, _) in self._index.values()), default=0)
            return (self._files, len(self._index), newest)


def resolve_root(cfg, override=None):
    for c in (override, os.environ.get("BABY_LOG_APP_FOLDER"), (cfg or {}).get("paths", {}).get("app_folder")):
        if c:
            return Path(c)
    raise RuntimeError("no app folder configured")


def open_journal(config_path="config.yaml", root=None):
    with open(config_path, encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)
    return Journal(resolve_root(cfg, root)).ensure()


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Baby Log journal status")
    ap.add_argument("--root", help="journal root (also BABY_LOG_APP_FOLDER)")
    a = ap.parse_args()
    j = open_journal(root=a.root)
    print(f"Journal: {j.root}")
    for k, v in j.stats().items():
        print(f"  {k:<12} {v}")
