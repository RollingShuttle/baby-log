"""static/i18n.js — the PC page's English/Chinese switch. Its translate() runs under Node against
the real i18n/strings.json; the rest is checked statically. Standalone or under discovery."""
import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _node  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
I18N = ROOT / "static" / "i18n.js"
TABLE = json.loads((ROOT / "i18n" / "strings.json").read_text(encoding="utf-8"))["strings"]


def zh(key):
    return TABLE[key]["zh-Hans"]


class TestStatic(unittest.TestCase):
    def test_loaded_before_the_app(self):
        html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
        self.assertLess(html.index("/static/i18n.js"), html.index("/static/app.js"))

    def test_nothing_node_16_cannot_run(self):
        src = I18N.read_text(encoding="utf-8")
        for bad in ("??=", ".at(", "||=", "&&="):
            self.assertNotIn(bad, src)

    def test_bundled_into_the_exe(self):
        for f in ("build_exe.bat", "tools/update.py"):
            self.assertIn("strings.json", (ROOT / f).read_text(encoding="utf-8"), f)


SCRIPT = r"""
const I18n = require(%(path)s);
const table = require(%(table)s).strings;
const t = I18n.make(table);
const out = {
  exact: t("Save settings"),
  spaced: t("  Save settings\n"),
  template: t("3 wet"),
  nested: t("Feed saved · 3:00 PM"),
  name: t("Yisen"),
  date: t("2026-11-13 10:20"),
  zhSystem: I18n.resolved("zh-CN"),
  enSystem: I18n.resolved("en-US"),
};
console.log(JSON.stringify(out));
"""


class TestUnderNode(unittest.TestCase):
    def test_translate(self):
        if not _node.NODE:
            self.skipTest("no Node binary found (set BABY_LOG_NODE or install node)")
        rc, out, err = _node.run_js(SCRIPT % {"path": json.dumps(str(I18N)),
                                              "table": json.dumps(str(ROOT / "i18n" / "strings.json"))})
        self.assertEqual(rc, 0, err)
        got = json.loads(out.strip().splitlines()[-1])
        self.assertEqual(got["exact"], zh("settings.saveSettings"))
        self.assertEqual(got["spaced"], "  " + zh("settings.saveSettings") + "\n")
        self.assertEqual(got["template"], zh("now.wetTotal").replace("{n}", "3"))
        self.assertNotIn("saved", got["nested"])
        self.assertIn("3:00 PM", got["nested"])
        self.assertEqual(got["name"], "Yisen")
        self.assertEqual(got["date"], "2026-11-13 10:20")
        self.assertEqual((got["zhSystem"], got["enSystem"]), ("zh-Hans", "en"))

    def test_parses_under_node_check(self):
        if not _node.NODE:
            self.skipTest("no Node binary found")
        proc = subprocess.run([_node.NODE, "--check", str(I18N)], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)


if __name__ == "__main__":
    unittest.main()
