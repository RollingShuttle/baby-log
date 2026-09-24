"""
paper.py — importing the hospital paper sheet.

The first three days were written on the hospital's *Feeding & Diapering* sheet before the app
existed. `tools/paper_sheet.json` is that sheet transcribed once, by hand; this module turns it
into journal events so the app's history starts on the day he was born rather than the day the
phones were set up. Readings the transcriber was unsure of carry a `check` question, which
becomes a `Check: …` note so the app lists them under Needs check for correction.

Idempotent by construction: every row has a deterministic id (`E-paper-<YYYYMMDD>-<HHMM>-<type>`),
a row already on file — in any revision, a tombstone included — is skipped, and the store's
`revision=1` guard refuses a second copy if the skip ever misses. See SPEC.md §10.

    python paper.py [--root <journal>] [--sheet <json>] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import store

HERE = Path(__file__).resolve().parent
DEFAULT_SHEET = HERE / "tools" / "paper_sheet.json"
CONFIG = HERE / "config.yaml"

# The sheet has no author; every field that names one says so, so the entries stand out from
# the phones' in every list and can be corrected without confusion about who typed them.
LABEL = "paper"


def load(path):
    """The parsed sheet. Only the shape §10 pins is checked here; the values are checked by the
    store when they are written, and a bad value must name the row, not the file."""
    with open(path, encoding="utf-8") as fh:
        sheet = json.load(fh)
    if not isinstance(sheet, dict):
        raise ValueError(f"{path}: the sheet must be a JSON object")
    for key in ("child", "feeds", "diapers"):
        if key not in sheet:
            raise ValueError(f"{path}: missing {key!r}")
    if not isinstance(sheet["child"], dict) or not sheet["child"].get("name") \
            or not sheet["child"].get("born"):
        raise ValueError(f"{path}: child must have name and born")
    for key in ("feeds", "diapers"):
        if not isinstance(sheet[key], list):
            raise ValueError(f"{path}: {key} must be a list")
    return sheet


def event_id(row, type):
    return f"E-paper-{row['date'].replace('-', '')}-{row['time'].replace(':', '')}-{type}"


def local_time(date, hhmm):
    """The wall-clock time as written, with this PC's offset on *that* date — so a sheet
    imported after a DST change still says what the clock on the wall said."""
    naive = datetime.strptime(f"{date} {hhmm}", "%Y-%m-%d %H:%M")
    return store.iso_local(naive)


def compose_note(row):
    """The row's note, then the transcriber's question as `Check: …`, joined with ` — `."""
    parts = []
    if row.get("note"):
        parts.append(row["note"])
    if row.get("check"):
        parts.append(f"Check: {row['check']}")
    return " — ".join(parts)


def _feed_data(row):
    return {
        "breast": {"left_s": None, "right_s": None, "total_s": row.get("breast_s"),
                   "last_side": None, "approx": bool(row.get("approx", False))},
        # The hospital sheet never says which milk was in the bottle; formula is what it was.
        "bottles": [{"kind": "formula", "ml": ml} for ml in row.get("bottles_ml") or []],
    }


def _diaper_data(row):
    data = {"wet": bool(row.get("wet", False)), "dirty": bool(row.get("dirty", False))}
    for key in ("color", "texture"):
        if row.get(key) is not None:
            data[key] = row[key]
    return data


def _row(row, type, child_id, builder):
    for key in ("date", "time"):
        if not isinstance(row.get(key), str):
            raise ValueError(f"{type} row is missing {key!r}: {row!r}")
    return {
        "event_id": event_id(row, type),
        "child_id": child_id,
        "type": type,
        "time": local_time(row["date"], row["time"]),
        "end": None,
        "data": store.validate_data(type, builder(row)),
        "note": compose_note(row),
        "logged_by": LABEL,
        "device": LABEL,
        "entered_from": LABEL,
    }


def plan(sheet, child_id):
    """Every row as the keyword arguments of `Journal.write_event`, in time order. Refuses the
    whole sheet when two rows share an id: the id is date+time+type, so a clash means a
    transcription slip that must be fixed by hand rather than silently merged."""
    events = [_row(r, "feed", child_id, _feed_data) for r in sheet["feeds"]]
    events += [_row(r, "diaper", child_id, _diaper_data) for r in sheet["diapers"]]
    seen = {}
    for ev in events:
        if ev["event_id"] in seen:
            raise ValueError(f"two rows produce the same id {ev['event_id']}; fix the sheet")
        seen[ev["event_id"]] = ev
    events.sort(key=lambda e: (e["time"], e["type"]))
    return events


def describe(ev):
    """One readable line per planned entry for the summary."""
    d = ev["data"]
    if ev["type"] == "feed":
        parts = []
        b = d["breast"]
        if b["total_s"] is not None:
            parts.append(f"{'~' if b['approx'] else ''}{round(b['total_s'] / 60)} min breast")
        if d["bottles"]:
            parts.append(" + ".join(f"{p['ml']} ml" for p in d["bottles"]))
        text = ", ".join(parts) or "feed"
    else:
        kinds = [k for k in ("wet", "dirty") if d[k]]
        text = " + ".join(kinds) or "diaper"
        detail = [v for v in (d["color"], d["texture"]) if v]
        if detail:
            text += f" ({', '.join(detail)})"
    if ev["note"]:
        text += f" — {ev['note']}"
    return text


def run(journal, sheet_path, dry_run=False):
    """Import the sheet into `journal`; returns `{"written", "skipped", "child_id"}`.

    The child is created only when the journal has none after a fresh read — the Settings form
    may already have made one, and a second Yisen would split the log in two.
    """
    sheet = load(sheet_path)
    journal.load(force=True)
    children = journal.children()
    child_id = children[0]["child_id"] if children else None

    # Plan (and refuse a bad sheet) before the child exists: a rejected import must leave the
    # journal exactly as it found it. The placeholder never reaches the store.
    events = plan(sheet, child_id or "C-pending")
    child_new = not children
    if child_new and not dry_run:
        child = journal.write_child(name=sheet["child"]["name"], born=sheet["child"]["born"],
                                    device=LABEL)
        child_id = child["child_id"]
        for ev in events:
            ev["child_id"] = child_id

    written = skipped = 0
    lines = []
    for ev in events:
        if journal.event(ev["event_id"]) is not None:
            skipped += 1
            lines.append(f"  skip   {ev['time'][:16].replace('T', ' ')}  {ev['type']:<6} {describe(ev)}")
            continue
        if not dry_run:
            journal.write_event(revision=1, **ev)
        written += 1
        verb = "would " if dry_run else "write "
        lines.append(f"  {verb:<6} {ev['time'][:16].replace('T', ' ')}  {ev['type']:<6} {describe(ev)}")

    print(f"Paper sheet: {sheet_path}")
    print(f"Journal:     {journal.root}")
    if child_new:
        print(f"Child:       {sheet['child']['name']} born {sheet['child']['born']} "
              f"({'would be created' if dry_run else 'created'})")
    else:
        print(f"Child:       {children[0]['name']} ({child_id}, already on file)")
    print("\n".join(lines))
    print(f"{'Dry run — ' if dry_run else ''}{written} written, {skipped} skipped"
          f" (of {len(events)} rows)")
    return {"written": 0 if dry_run else written, "skipped": skipped, "child_id": child_id,
            **({"planned": written} if dry_run else {})}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Import the hospital paper sheet into the Baby Log journal")
    ap.add_argument("--root", help="journal root (default: config.yaml paths.app_folder)")
    ap.add_argument("--sheet", default=str(DEFAULT_SHEET), help="the transcribed sheet (JSON)")
    ap.add_argument("--dry-run", action="store_true", help="print the plan; write nothing")
    a = ap.parse_args(argv)
    if a.root:
        journal = store.Journal(a.root).ensure()
    else:
        journal = store.open_journal(str(CONFIG))
    try:
        run(journal, a.sheet, dry_run=a.dry_run)
    except (ValueError, FileExistsError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
