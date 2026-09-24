"""
_node.py — find a Node binary and run a script with it, for the JS tests.

node is not on PATH on this machine, but two Adobe products ship one. The search order is the
env var BABY_LOG_NODE, then PATH, then those two copies (v16 first: it has webcrypto, v14 does
not). Callers skip with a message when none exists; the suite must never depend on Node.
"""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

BUNDLED = [
    r"C:\Program Files\Adobe\Adobe Creative Cloud Experience\libs\node.exe",   # v16.2
    r"C:\Program Files\Adobe\Adobe Photoshop 2022\node.exe",                   # v14
]


def find_node():
    """The first Node that exists, or None."""
    env = os.environ.get("BABY_LOG_NODE")
    if env and Path(env).is_file():
        return env
    found = shutil.which("node")
    if found:
        return found
    for candidate in BUNDLED:
        if Path(candidate).is_file():
            return candidate
    return None


NODE = find_node()


def run_js(script_text, timeout=30):
    """Run a script under Node with cwd = the repo root; (returncode, stdout, stderr).

    The script lands in its own temp folder, so it must require project files by absolute
    path — build one from ROOT and json.dumps it into the script."""
    if not NODE:
        raise RuntimeError("no Node binary found")
    with tempfile.TemporaryDirectory() as d:
        script = Path(d) / "script.js"
        script.write_text(script_text, encoding="utf-8")
        proc = subprocess.run([NODE, str(script)], cwd=str(ROOT), capture_output=True,
                              text=True, encoding="utf-8", errors="replace", timeout=timeout)
        return proc.returncode, proc.stdout, proc.stderr
