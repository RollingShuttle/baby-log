"""
push.py — put this computer's changes on GitHub, and so on the phones and the other PCs.

    python tools/push.py ["what changed"]    (or double-click push.bat)

The one thing to run after anything in this folder has been edited. By hand it is four commands
and two rules that are easy to forget, and forgetting either is silent: a change under docs/
without a new service-worker VERSION leaves every installed phone on the old copy for ever, and
a commit made under a personal email lands in a public repository. So this script:

  * bumps VERSION in docs/sw.js itself when anything under docs/ changed and nobody bumped it;
  * runs the whole test suite first, and refuses to push while any test fails;
  * commits under the repository's noreply identity, with the note you typed or an automatic one;
  * pushes, setting the upstream on a fresh clone;
  * says plainly when there is nothing to push, rather than inventing an empty commit.

It never touches config.yaml, data/ or Baby Log.xlsx — they are not in the repository.
"""
from __future__ import annotations

import re
import socket
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # this script lives in tools/
SW = ROOT / "docs" / "sw.js"
IDENTITY = ("RollingShuttle", "RollingShuttle@users.noreply.github.com")
VERSION_RE = re.compile(r'(const VERSION = ")v(\d+)(";)')


def run(args, **kw):
    """Run a command in the project folder and hand back (ok, output)."""
    try:
        done = subprocess.run(args, cwd=ROOT, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", **kw)
    except FileNotFoundError:
        return False, f"{args[0]} is not installed, or not on the PATH."
    return done.returncode == 0, (done.stdout or "") + (done.stderr or "")


# -- the pure parts, tested on their own -----------------------------------------------------------
def changed_paths(porcelain):
    """The paths in `git status --porcelain` output, renames resolved to their new name."""
    out = []
    for line in porcelain.splitlines():
        if len(line) < 4:
            continue
        path = line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        out.append(path.strip().strip('"'))
    return out


def version_of(text):
    m = VERSION_RE.search(text)
    return int(m.group(2)) if m else None


def bump_version(text):
    """The same file with VERSION one higher. Returns (new_text, new_version)."""
    m = VERSION_RE.search(text)
    if not m:
        raise ValueError("docs/sw.js has no `const VERSION = \"vN\";` line")
    n = int(m.group(2)) + 1
    return VERSION_RE.sub(lambda mm: f'{mm.group(1)}v{n}{mm.group(3)}', text, count=1), n


def needs_bump(paths, head_version, work_version):
    """A change under docs/ needs a new service-worker VERSION, unless this change already carries
    one (the working copy's number is above the last commit's)."""
    touched_docs = any(p.replace("\\", "/").startswith("docs/") for p in paths)
    if not touched_docs:
        return False
    if head_version is None or work_version is None:
        return True
    return work_version <= head_version


def auto_message(paths):
    """"Update 26 Sep 2026 from THIS-PC: docs, guide" — enough to tell commits apart later."""
    areas = []
    for p in paths:
        top = p.replace("\\", "/").split("/", 1)[0]
        if top not in areas:
            areas.append(top)
    where = socket.gethostname() or "this PC"
    tail = f": {', '.join(areas)}" if areas else ""
    return f"Update {date.today():%d %b %Y} from {where}{tail}"


# -- the steps ------------------------------------------------------------------------------------
def check_repo():
    ok, _ = run(["git", "rev-parse", "--is-inside-work-tree"])
    if not ok:
        print("This folder is not a git checkout, so there is nothing to push from.")
        return False
    ok, out = run(["git", "remote", "get-url", "origin"])
    if not ok:
        print("No GitHub remote is set. In this folder run once:")
        print("  git remote add origin https://github.com/RollingShuttle/baby-log.git")
        return False
    return True


def ensure_identity():
    """The repository is public, so commits carry the noreply name, never a personal email.
    Set repo-locally, so nothing outside this folder changes."""
    ok, email = run(["git", "config", "user.email"])
    if ok and email.strip().endswith("@users.noreply.github.com"):
        return
    run(["git", "config", "user.name", IDENTITY[0]])
    run(["git", "config", "user.email", IDENTITY[1]])
    print(f"Commits from this folder are signed as {IDENTITY[0]} (no personal email).")


def unpushed():
    """Commits made here that GitHub does not have yet; None when there is no upstream at all."""
    ok, out = run(["git", "log", "@{u}..HEAD", "--oneline"])
    if not ok:
        return None
    return [l for l in out.splitlines() if l.strip()]


def head_sw_version():
    ok, out = run(["git", "show", "HEAD:docs/sw.js"])
    return version_of(out) if ok else None


def run_tests():
    print("Running the tests first (about twenty seconds)...")
    ok, out = run([sys.executable, "-m", "unittest", "discover", "-s", "tests"])
    if not ok:
        print(out[-3000:])
        print("A test failed, so nothing was pushed: a broken phone app would reach both phones")
        print("within a minute. Fix it (or ask Claude to) and run this again.")
    return ok


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    skip_tests = "--no-tests" in argv
    message = " ".join(a for a in argv if a != "--no-tests").strip()

    print("Baby Log — push")
    if not check_repo():
        return 1
    ensure_identity()

    ok, porcelain = run(["git", "status", "--porcelain"])
    if not ok:
        print(porcelain)
        return 1
    paths = changed_paths(porcelain)
    behind = unpushed()

    if not paths and not behind:
        print("Nothing to push — everything here is already on GitHub.")
        return 0

    if paths:
        if needs_bump(paths, head_sw_version(), version_of(SW.read_text(encoding="utf-8"))):
            text, n = bump_version(SW.read_text(encoding="utf-8"))
            SW.write_text(text, encoding="utf-8", newline="\n")
            print(f"Something under docs/ changed, so the phone app's version is now v{n}.")
        if not skip_tests and not run_tests():
            return 1
        ok, out = run(["git", "add", "-A"])
        if not ok:
            print(out)
            return 1
        ok, out = run(["git", "commit", "-q", "-m", message or auto_message(paths)])
        if not ok:
            print(out)
            return 1
        print(f"Committed {len(paths)} changed file{'s' if len(paths) != 1 else ''}.")
    elif behind:
        print(f"{len(behind)} commit{'s' if len(behind) != 1 else ''} made earlier, not yet on GitHub.")

    args = ["git", "push"] if behind is not None else ["git", "push", "-u", "origin", "main"]
    ok, out = run(args)
    if not ok:
        print(out)
        print("The push did not go through. If it asked for a sign-in, sign in and run this again;")
        print("if it says the remote has changes, double-click update.bat first, then push again.")
        return 1

    print("Pushed to GitHub.")
    if any(p.replace("\\", "/").startswith("docs/") for p in paths):
        print("The phone app will update on its own within a minute or two; a phone that is open")
        print("picks it up the next time it is closed and reopened.")
    print("Other computers get this with update.bat.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
