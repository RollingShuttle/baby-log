"""
test_setup_machine.py — the second-machine setup.

    python tests/test_setup_machine.py

config.yaml is the one file that cannot be shared between computers, so this is the only thing
standing between a fresh clone and an app that will not start. The parts worth checking are the
ones that would go wrong quietly: writing a config that points at the wrong folder, creating the
folders somewhere real, or overwriting a config that already works.

Nothing here may touch the real OneDrive: onedrive_roots() also globs the home folder, so every
test that reaches main() patches it to a temp list rather than trusting the environment variables.
"""

# Run straight from the shell, only tests/ is on the path; discovered from the repo root, only
# the root is. Put all three where imports can find them so both ways of running behave alike.
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path[:0] = [str(HERE), str(ROOT), str(ROOT / "tools")]

import os
import tempfile
import unittest
from unittest import mock

import setup_machine as sm
import yaml


def key_paths(tree, prefix=""):
    """Every dotted key in a nested mapping, so two configs can be compared shape for shape."""
    out = set()
    for k, v in (tree or {}).items():
        name = f"{prefix}{k}"
        out.add(name)
        if isinstance(v, dict):
            out |= key_paths(v, name + ".")
    return out


def run_main_in(work, onedrive):
    """Drive main() with the project at `work` and `onedrive` as the only OneDrive."""
    was, sm.__file__ = sm.__file__, str(work / "tools" / "setup_machine.py")
    try:
        with mock.patch.object(sm, "onedrive_roots", return_value=[onedrive]):
            return sm.main()
    finally:
        sm.__file__ = was


class TestPathFormatting(unittest.TestCase):
    def test_windows_paths_are_written_with_forward_slashes(self):
        """Backslashes in a YAML double-quoted string are escapes, so a Windows path written
        literally would either break the parse or silently lose a separator."""
        out = sm.as_yaml_path(Path(r"C:\Users\someone\OneDrive\Apps\Baby Log"))
        self.assertNotIn("\\", out)
        self.assertTrue(out.startswith("C:/Users/"))

    def test_a_written_path_survives_a_yaml_round_trip(self):
        p = sm.as_yaml_path(Path(r"C:\Users\someone\OneDrive\文档\Yisen File"))
        parsed = yaml.safe_load('paths:\n  app_folder: "%s"\n' % p)
        self.assertEqual(parsed["paths"]["app_folder"], p)


class TestOneDriveDiscovery(unittest.TestCase):
    def test_every_sign_in_is_considered(self):
        """A work and a personal OneDrive are separate folders, and the baby files are only in
        one of them. Looking at just the first would find the wrong one half the time."""
        with tempfile.TemporaryDirectory() as d:
            a, b = Path(d) / "OneDrive", Path(d) / "OneDrive - work.example"
            a.mkdir(), b.mkdir()
            keep = {k: os.environ.get(k) for k in ("OneDrive", "OneDriveCommercial")}
            os.environ["OneDrive"], os.environ["OneDriveCommercial"] = str(a), str(b)
            try:
                found = sm.onedrive_roots()
            finally:
                for k, v in keep.items():
                    if v is None:
                        os.environ.pop(k, None)
                    else:
                        os.environ[k] = v
            self.assertIn(a, found)
            self.assertIn(b, found)

    def test_the_same_folder_is_not_listed_twice(self):
        with tempfile.TemporaryDirectory() as d:
            one = Path(d) / "OneDrive"
            one.mkdir()
            keep = {k: os.environ.get(k) for k in ("OneDrive", "OneDriveConsumer")}
            os.environ["OneDrive"] = os.environ["OneDriveConsumer"] = str(one)
            try:
                found = sm.onedrive_roots()
            finally:
                for k, v in keep.items():
                    if v is None:
                        os.environ.pop(k, None)
                    else:
                        os.environ[k] = v
            self.assertEqual(found.count(one), 1)

    def test_the_app_folder_is_looked_for_where_it_actually_lives(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / sm.APP_FOLDER_TAIL).mkdir(parents=True)
            self.assertEqual(sm.find_app_folder([root]), root / sm.APP_FOLDER_TAIL)

    def test_a_missing_app_folder_gets_its_default_place(self):
        """A brand-new empty journal folder is the right first state, so a missing one is a
        place to create, not a reason to stop."""
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self.assertEqual(sm.find_app_folder([root]), root / sm.APP_FOLDER_TAIL)

    def test_the_onedrive_that_already_holds_the_journal_wins(self):
        """With a work OneDrive listed first, the app folder must still land beside the existing
        journal rather than starting a second one."""
        with tempfile.TemporaryDirectory() as d:
            work, personal = Path(d) / "OneDrive - work", Path(d) / "OneDrive"
            (personal / sm.APP_FOLDER_TAIL).mkdir(parents=True)
            work.mkdir()
            self.assertEqual(sm.choose_root([work, personal]), personal)
            self.assertEqual(sm.find_app_folder([work, personal]), personal / sm.APP_FOLDER_TAIL)

    def test_the_output_folder_is_found_however_deep_the_folder_is_localised(self):
        """The documents folder is named in the account's own language, so the path cannot be
        assumed — only the folder name can."""
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            deep = root / "文档" / "Yisen File"
            deep.mkdir(parents=True)
            self.assertEqual(sm.find_dir([root], "Yisen File"), deep)
            self.assertEqual(sm.find_output_folder([root]), deep)

    def test_a_missing_output_folder_is_not_invented_elsewhere(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self.assertIsNone(sm.find_dir([root], "Yisen File"))
            self.assertEqual(sm.find_output_folder([root]), root / sm.OUTPUT_FOLDER_TAIL)


class TestItRefusesToClobber(unittest.TestCase):
    def test_an_existing_config_is_left_alone(self):
        """Someone running this twice on a working machine must not lose the paths that work,
        and must not have folders created either."""
        with tempfile.TemporaryDirectory() as d:
            work = Path(d) / "project"
            onedrive = Path(d) / "OneDrive"
            work.mkdir(), onedrive.mkdir()
            (work / sm.TEMPLATE).write_text("paths:\n  app_folder: \"x\"\n", encoding="utf-8")
            existing = work / sm.TARGET
            existing.write_text("mine\n", encoding="utf-8")
            self.assertEqual(run_main_in(work, onedrive), 0)
            self.assertEqual(existing.read_text(encoding="utf-8"), "mine\n")
            self.assertEqual(list(onedrive.iterdir()), [])


class TestItWritesTheConfig(unittest.TestCase):
    def test_missing_folders_are_created_not_refused(self):
        """SPEC §6.3: the app folder and the output folder are created when absent, and the
        config points at exactly those two."""
        with tempfile.TemporaryDirectory() as d:
            work = Path(d) / "project"
            onedrive = Path(d) / "OneDrive"
            work.mkdir(), onedrive.mkdir()
            (work / sm.TEMPLATE).write_bytes((ROOT / sm.TEMPLATE).read_bytes())
            with mock.patch.object(sm, "pin_folder", return_value=True) as pinned:
                self.assertEqual(run_main_in(work, onedrive), 0)
            app_folder = onedrive / sm.APP_FOLDER_TAIL
            output_folder = onedrive / sm.OUTPUT_FOLDER_TAIL
            self.assertTrue(app_folder.is_dir())
            self.assertTrue(output_folder.is_dir())
            pinned.assert_called_once_with(app_folder)
            cfg = yaml.safe_load((work / sm.TARGET).read_text(encoding="utf-8"))
            self.assertEqual(cfg["paths"]["app_folder"], sm.as_yaml_path(app_folder))
            self.assertEqual(cfg["paths"]["output_folder"], sm.as_yaml_path(output_folder))

    def test_the_generated_config_has_the_templates_keys_exactly(self):
        """The template is the contract (SPEC §6.1): a key the rewrite dropped or invented would
        fail somewhere far from the cause."""
        with tempfile.TemporaryDirectory() as d:
            work = Path(d) / "project"
            onedrive = Path(d) / "OneDrive"
            work.mkdir(), onedrive.mkdir()
            (work / sm.TEMPLATE).write_bytes((ROOT / sm.TEMPLATE).read_bytes())
            with mock.patch.object(sm, "pin_folder", return_value=True):
                self.assertEqual(run_main_in(work, onedrive), 0)
            template = yaml.safe_load((ROOT / sm.TEMPLATE).read_text(encoding="utf-8"))
            written = yaml.safe_load((work / sm.TARGET).read_text(encoding="utf-8"))
            self.assertEqual(key_paths(written), key_paths(template))
            self.assertEqual(key_paths(template), {
                "paths", "paths.app_folder", "paths.output_folder", "paths.local_data",
                "paths.backups", "paths.backup_keep",
                "server", "server.host", "server.port", "server.bind_lan",
                "auth", "auth.client_id", "auth.authority", "auth.scopes",
                "auth.redirect_uri_dev", "auth.redirect_uri_prod",
            })
            # Only the two paths change; everything else is carried from the template verbatim.
            for section in ("server", "auth"):
                self.assertEqual(written[section], template[section])
            self.assertEqual(written["server"]["port"], 8766)

    def test_a_failed_pin_never_fails_the_run(self):
        """Pinning is a nicety for Files On-Demand; a machine without attrib still gets a config."""
        with tempfile.TemporaryDirectory() as d:
            work = Path(d) / "project"
            onedrive = Path(d) / "OneDrive"
            work.mkdir(), onedrive.mkdir()
            (work / sm.TEMPLATE).write_bytes((ROOT / sm.TEMPLATE).read_bytes())
            with mock.patch.object(sm, "pin_folder", return_value=False):
                self.assertEqual(run_main_in(work, onedrive), 0)
            self.assertTrue((work / sm.TARGET).exists())

    def test_pinning_itself_swallows_every_failure(self):
        with mock.patch.object(sm.subprocess, "run", side_effect=OSError("no attrib")):
            self.assertFalse(sm.pin_folder(Path("Z:/nowhere")))

    def test_no_onedrive_stops_rather_than_guessing(self):
        with tempfile.TemporaryDirectory() as d:
            work = Path(d) / "project"
            work.mkdir()
            (work / sm.TEMPLATE).write_bytes((ROOT / sm.TEMPLATE).read_bytes())
            was, sm.__file__ = sm.__file__, str(work / "tools" / "setup_machine.py")
            try:
                with mock.patch.object(sm, "onedrive_roots", return_value=[]):
                    self.assertEqual(sm.main(), 1)
            finally:
                sm.__file__ = was
            self.assertFalse((work / sm.TARGET).exists())


class TestTheTemplateItStartsFrom(unittest.TestCase):
    def test_the_template_carries_the_keys_it_rewrites(self):
        """If a key were renamed in the template this would write a config missing it, and the
        app would fail somewhere far away from the cause."""
        text = (ROOT / sm.TEMPLATE).read_text(encoding="utf-8")
        for key in ("app_folder", "output_folder"):
            self.assertIn(key + ":", text)

    def test_the_template_is_committed_and_the_config_is_not(self):
        """The template is the shareable half; config.yaml holds a username."""
        ignored = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("config.yaml", ignored)
        self.assertTrue((ROOT / sm.TEMPLATE).exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
