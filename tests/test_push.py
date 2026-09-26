"""
test_push.py — the push script.

    python tests/test_push.py

What matters here is what it must never do: push while a test fails, leave a docs/ change
without a new service-worker VERSION, commit under a personal email, or invent a commit when
there is nothing to push. The git calls are faked; the real repository is never touched.
"""

# Run straight from the shell, only tests/ is on the path; discovered from the repo root, only
# the root is. Put all three where imports can find them so both ways of running behave alike.
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path[:0] = [str(HERE), str(ROOT), str(ROOT / "tools")]

import tempfile
import unittest
from unittest import mock

import push


def fake_run(script):
    """A stand-in for push.run, driven by {substring-of-the-command: (ok, output)}. Anything
    not listed succeeds silently, which is the boring case."""
    calls = []

    def run(args, **kw):
        calls.append(list(args))
        joined = " ".join(str(a) for a in args)
        key = next((k for k in script if k in joined), None)
        return script[key] if key else (True, "")

    run.calls = calls
    return run


def called(run, *words):
    return any(all(w in " ".join(c) for w in words) for c in run.calls)


class TestThePureParts(unittest.TestCase):
    def test_changed_paths_reads_porcelain_output(self):
        out = " M docs/app.js\n?? guide/NEW.md\nR  old.txt -> tools/new.txt\n"
        self.assertEqual(push.changed_paths(out), ["docs/app.js", "guide/NEW.md", "tools/new.txt"])

    def test_bump_moves_the_version_by_one_and_nothing_else(self):
        text = 'const VERSION = "v5";\nconst SHELL = "shell-" + VERSION;\n'
        new, n = push.bump_version(text)
        self.assertEqual(n, 6)
        self.assertEqual(new, 'const VERSION = "v6";\nconst SHELL = "shell-" + VERSION;\n')
        self.assertEqual(push.version_of(new), 6)

    def test_bump_refuses_a_file_without_a_version(self):
        with self.assertRaises(ValueError):
            push.bump_version("nothing here")

    def test_a_docs_change_needs_a_bump_unless_it_already_carries_one(self):
        self.assertTrue(push.needs_bump(["docs/app.js"], 5, 5))
        self.assertFalse(push.needs_bump(["docs/app.js", "docs/sw.js"], 5, 6))
        self.assertFalse(push.needs_bump(["static/app.js", "guide/RUNNING.md"], 5, 5))
        self.assertTrue(push.needs_bump(["docs\\style.css"], 5, 5), "Windows separators count too")
        self.assertTrue(push.needs_bump(["docs/app.js"], None, 5), "no previous commit: bump anyway")

    def test_the_automatic_message_names_the_areas_touched(self):
        msg = push.auto_message(["docs/app.js", "docs/sw.js", "guide/RUNNING.md", "app.py"])
        self.assertTrue(msg.startswith("Update "))
        self.assertIn(": docs, guide, app.py", msg)
        self.assertNotIn("docs, docs", msg)

    def test_the_real_service_worker_has_a_version_line(self):
        self.assertIsNotNone(push.version_of(push.SW.read_text(encoding="utf-8")))


class TestWhatItMustNeverDo(unittest.TestCase):
    def setUp(self):
        # A scratch sw.js so a bump never touches the real one.
        self.tmp = tempfile.TemporaryDirectory()
        sw = Path(self.tmp.name) / "sw.js"
        sw.write_text('const VERSION = "v5";\n', encoding="utf-8")
        self.sw_patch = mock.patch.object(push, "SW", sw)
        self.sw_patch.start()
        self.sw = sw

    def tearDown(self):
        self.sw_patch.stop()
        self.tmp.cleanup()

    def test_nothing_to_push_is_said_and_no_commit_is_made(self):
        run = fake_run({"status --porcelain": (True, ""), "log @{u}..HEAD": (True, "")})
        with mock.patch.object(push, "run", run):
            self.assertEqual(push.main([]), 0)
        self.assertFalse(called(run, "commit"))
        self.assertFalse(called(run, "push"))

    def test_a_failing_test_stops_the_push(self):
        run = fake_run({"status --porcelain": (True, " M app.py\n"), "log @{u}..HEAD": (True, ""),
                        "unittest": (False, "FAILED (failures=1)")})
        with mock.patch.object(push, "run", run):
            self.assertEqual(push.main([]), 1)
        self.assertTrue(called(run, "unittest"))
        self.assertFalse(called(run, "commit"))
        self.assertFalse(called(run, "push"))

    def test_a_docs_change_bumps_the_version_before_the_commit(self):
        run = fake_run({"status --porcelain": (True, " M docs/app.js\n"), "log @{u}..HEAD": (True, ""),
                        "show HEAD:docs/sw.js": (True, 'const VERSION = "v5";\n')})
        with mock.patch.object(push, "run", run):
            self.assertEqual(push.main(["--no-tests"]), 0)
        self.assertEqual(push.version_of(self.sw.read_text(encoding="utf-8")), 6)
        self.assertTrue(called(run, "add", "-A"))
        self.assertTrue(called(run, "commit"))
        self.assertTrue(called(run, "push"))

    def test_a_docs_change_that_already_bumped_is_left_alone(self):
        self.sw.write_text('const VERSION = "v6";\n', encoding="utf-8")
        run = fake_run({"status --porcelain": (True, " M docs/sw.js\n M docs/app.js\n"),
                        "log @{u}..HEAD": (True, ""),
                        "show HEAD:docs/sw.js": (True, 'const VERSION = "v5";\n')})
        with mock.patch.object(push, "run", run):
            self.assertEqual(push.main(["--no-tests"]), 0)
        self.assertEqual(push.version_of(self.sw.read_text(encoding="utf-8")), 6)

    def test_a_change_outside_docs_never_bumps(self):
        run = fake_run({"status --porcelain": (True, " M static/app.js\n"), "log @{u}..HEAD": (True, "")})
        with mock.patch.object(push, "run", run):
            self.assertEqual(push.main(["--no-tests"]), 0)
        self.assertEqual(push.version_of(self.sw.read_text(encoding="utf-8")), 5)

    def test_the_typed_note_becomes_the_commit_message(self):
        run = fake_run({"status --porcelain": (True, " M guide/RUNNING.md\n"), "log @{u}..HEAD": (True, "")})
        with mock.patch.object(push, "run", run):
            push.main(["--no-tests", "Fixed", "a", "typo"])
        commit = next(c for c in run.calls if "commit" in c)
        self.assertEqual(commit[-1], "Fixed a typo")

    def test_earlier_commits_are_pushed_even_with_nothing_new_to_commit(self):
        run = fake_run({"status --porcelain": (True, ""), "log @{u}..HEAD": (True, "abc123 Earlier\n")})
        with mock.patch.object(push, "run", run):
            self.assertEqual(push.main([]), 0)
        self.assertFalse(called(run, "commit"))
        self.assertTrue(called(run, "push"))
        self.assertFalse(called(run, "unittest"), "nothing changed here, so nothing to test")

    def test_a_fresh_clone_sets_the_upstream(self):
        run = fake_run({"status --porcelain": (True, " M app.py\n"),
                        "log @{u}..HEAD": (False, "fatal: no upstream configured")})
        with mock.patch.object(push, "run", run):
            self.assertEqual(push.main(["--no-tests"]), 0)
        self.assertTrue(called(run, "push", "-u", "origin", "main"))

    def test_a_personal_email_is_replaced_by_the_noreply_identity(self):
        run = fake_run({"config user.email": (True, "someone@gmail.com\n")})
        with mock.patch.object(push, "run", run):
            push.ensure_identity()
        self.assertTrue(called(run, "config", "user.email", push.IDENTITY[1]))
        self.assertTrue(called(run, "config", "user.name", push.IDENTITY[0]))

    def test_the_noreply_identity_is_left_alone(self):
        run = fake_run({"config user.email": (True, "RollingShuttle@users.noreply.github.com\n")})
        with mock.patch.object(push, "run", run):
            push.ensure_identity()
        self.assertFalse(called(run, "config", "user.name"))

    def test_a_failed_push_is_reported_not_hidden(self):
        run = fake_run({"status --porcelain": (True, ""), "log @{u}..HEAD": (True, "abc123 Earlier\n"),
                        "git push": (False, "rejected")})
        with mock.patch.object(push, "run", run):
            self.assertEqual(push.main([]), 1)


class TestTheBatFile(unittest.TestCase):
    def test_push_bat_is_a_double_click_that_waits_to_be_read(self):
        bat = (ROOT / "push.bat").read_text(encoding="utf-8")
        self.assertIn('cd /d "%~dp0"', bat)
        self.assertIn("tools\\push.py", bat)
        self.assertIn("pause", bat)
        self.assertIn("set /p", bat, "it asks what changed")


if __name__ == "__main__":
    unittest.main(verbosity=2)
