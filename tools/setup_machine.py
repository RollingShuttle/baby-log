"""
setup_machine.py — get the app running on another computer.

    python tools/setup_machine.py

config.yaml is the one file that cannot be shared between machines: it holds absolute paths, and
those paths contain a username. That is why it is gitignored, and why a fresh clone has everything
except the thing it needs to start. This writes one for the machine it is run on.

It finds OneDrive, picks the root, and writes paths.app_folder = <OneDrive>/Apps/Baby Log and
paths.output_folder = <OneDrive>/文档/Yisen File, creating both folders when they are missing
(SPEC.md §6.3). Nothing is overwritten: if config.yaml already exists it says so and stops.

The app folder is the important one. The phones and the PC meet there and OneDrive does the
syncing, which is how this machine sees everything the phones have logged. A brand-new empty one
is the right first state, so unlike the whiskey app there is nothing to refuse over.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

TEMPLATE = "config.example.yaml"
TARGET = "config.yaml"
APP_FOLDER_TAIL = Path("Apps") / "Baby Log"
OUTPUT_FOLDER_TAIL = Path("文档") / "Yisen File"


def onedrive_roots():
    """Every OneDrive this account has. Personal and work sign-ins each get their own, and the
    environment names them differently, so look at all of them rather than assuming one."""
    seen = []
    for var in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
        value = os.environ.get(var)
        if value and Path(value).is_dir() and Path(value) not in seen:
            seen.append(Path(value))
    home = Path.home()
    for guess in home.glob("OneDrive*"):
        if guess.is_dir() and guess not in seen:
            seen.append(guess)
    return seen


def find_dir(roots, name, limit=6):
    """Search each OneDrive for a folder by name, shallowest match first — the documents folder
    is named in the account's own language (文档 here, Documents elsewhere), so the path cannot be
    assumed, only the folder name can."""
    for root in roots:
        matches = []
        for depth in range(limit):
            pattern = "/".join(["*"] * depth + [name]) if depth else name
            matches.extend(p for p in root.glob(pattern) if p.is_dir())
            if matches:
                return sorted(matches, key=lambda p: len(p.parts))[0]
    return None


def choose_root(roots):
    """The OneDrive the baby files live in: one that already has the app folder; else the one
    that holds Yisen File; else one with an Apps folder (other app journals live there); else a
    personal one over a work one. A work OneDrive is usually listed too — and first, on this
    PC — and it has a localised documents folder of its own, so "has 文档" is no evidence at
    all. Putting the journal there would be wrong quietly: the phones sign in to the personal
    account and would never see it."""
    for root in roots:
        if (root / APP_FOLDER_TAIL).is_dir():
            return root
    for root in roots:
        if find_dir([root], OUTPUT_FOLDER_TAIL.name):
            return root
    for root in roots:
        if (root / APP_FOLDER_TAIL.parts[0]).is_dir():
            return root
    personal = [r for r in roots if " - " not in r.name]     # "OneDrive - <org>" is a work sign-in
    return (personal or roots)[0]


def find_app_folder(roots):
    """The existing app folder wherever it is, else where it will be created."""
    for root in roots:
        candidate = root / APP_FOLDER_TAIL
        if candidate.is_dir():
            return candidate
    return choose_root(roots) / APP_FOLDER_TAIL


def find_output_folder(roots):
    """An existing Yisen File wherever the localised documents folder put it, else the default."""
    return find_dir(roots, OUTPUT_FOLDER_TAIL.name) or choose_root(roots) / OUTPUT_FOLDER_TAIL


def pin_folder(path):
    """Best effort, Windows only: mark the journal 'always keep on this device' so Files On-Demand
    never leaves placeholders the reader would have to skip. Nothing here may fail the run —
    a journal that is not pinned still works, it just reads a little slower."""
    if os.name != "nt":
        return False
    try:
        done = subprocess.run(["attrib", "+P", "/S", "/D", str(path)], capture_output=True,
                              text=True, encoding="utf-8", errors="replace", timeout=60)
        return done.returncode == 0
    except Exception:                          # noqa: BLE001 — attrib missing, timeout, anything
        return False


def as_yaml_path(p):
    """Forward slashes read the same on every platform and avoid backslash escapes."""
    return str(p).replace("\\", "/")


def main():
    root = Path(__file__).resolve().parent.parent  # this script lives in tools/
    target = root / TARGET
    if target.exists():
        print(f"{TARGET} already exists here — leaving it alone.")
        print("Delete it first if you want this to build a new one.")
        return 0

    template = root / TEMPLATE
    if not template.exists():
        print(f"{TEMPLATE} is missing; this needs to be run inside the project folder.")
        return 1

    roots = onedrive_roots()
    if not roots:
        print("No OneDrive folder found on this machine.")
        print("Sign in to OneDrive first, let it sync, then run this again.")
        return 1

    print("OneDrive:")
    for r in roots:
        print(f"  {r}")

    app_folder = find_app_folder(roots)
    output_folder = find_output_folder(roots)

    print()
    print("Found:")
    print(f"  app folder    : {app_folder}{'' if app_folder.is_dir() else '  (will be created)'}")
    print(f"  output folder : {output_folder}{'' if output_folder.is_dir() else '  (will be created)'}")

    app_folder.mkdir(parents=True, exist_ok=True)
    output_folder.mkdir(parents=True, exist_ok=True)
    if not pin_folder(app_folder):
        print("  (could not pin the app folder to this device; OneDrive may leave placeholders)")

    text = template.read_text(encoding="utf-8")
    replacements = {
        "app_folder": as_yaml_path(app_folder),
        "output_folder": as_yaml_path(output_folder),
    }
    out = []
    for line in text.splitlines():
        stripped = line.strip()
        key = stripped.split(":", 1)[0].strip() if ":" in stripped else ""
        if key in replacements and replacements[key] and not stripped.startswith("#"):
            indent = line[: len(line) - len(line.lstrip())]
            out.append(f'{indent}{key}: "{replacements[key]}"')
        else:
            out.append(line)
    target.write_text("\n".join(out) + "\n", encoding="utf-8")

    print()
    print(f"Wrote {target}")
    print()
    print("Next:")
    print("  pip install -r requirements.txt")
    print("  python -m unittest discover -s tests")
    print("  build_exe.bat            (then: python tools/make_shortcut.py)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
