"""The iOS project under ios/: the files Xcode will see are well-formed and agree with the other
two implementations (the filename and time regexes, the client ID, the string table). Nothing
here compiles Swift; Xcode on the Mac does that. Reads only; runs standalone and under
discovery."""
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IOS = ROOT / "ios"
SWIFT = sorted((IOS / "BabyLog").rglob("*.swift"))
HEX24 = re.compile(r"\b[0-9A-F]{24}\b")
TEXT_SUFFIXES = (".swift", ".json", ".pbxproj", ".xcworkspacedata", ".xcstrings")


class TestIOS(unittest.TestCase):
    def test_text_files_are_utf8_lf_without_bom(self):
        checked = 0
        for p in IOS.rglob("*"):
            if p.is_file() and p.suffix in TEXT_SUFFIXES:
                raw = p.read_bytes()
                self.assertFalse(raw.startswith(b"\xef\xbb\xbf"), p)
                self.assertNotIn(b"\r", raw, p)
                raw.decode("utf-8")
                checked += 1
        self.assertGreater(checked, 15)

    def test_strings_copy_matches_i18n(self):
        copy = IOS / "BabyLog" / "Resources" / "strings.json"
        self.assertEqual(copy.read_bytes(), (ROOT / "i18n" / "strings.json").read_bytes(),
                         "copy i18n/strings.json to ios/BabyLog/Resources/strings.json")

    def test_every_string_key_used_exists(self):
        table = json.loads((ROOT / "i18n" / "strings.json").read_text(encoding="utf-8"))["strings"]
        used, plural = set(), set()
        for p in SWIFT:
            src = p.read_text(encoding="utf-8")
            used.update(re.findall(r'\bS\("([^"]+)"', src))
            plural.update(re.findall(r'\bSP\("([^"]+)"', src))
        self.assertTrue(used)
        missing = sorted(k for k in used if k not in table)
        missing += sorted(k + s for k in plural for s in (".one", ".other") if k + s not in table)
        self.assertEqual(missing, [])

    def test_filename_and_time_patterns_match_core_js(self):
        core = (ROOT / "docs" / "core.js").read_text(encoding="utf-8")
        names = (IOS / "BabyLog" / "Core" / "Names.swift").read_text(encoding="utf-8")
        for js_name, swift_name in (("NAME_RE", "namePattern"), ("ISO_RE", "isoPattern")):
            js = re.search(r"const %s = /(.*)/;" % js_name, core).group(1)
            swift = re.search(r'static let %s = "(.*)"' % swift_name, names).group(1).replace("\\\\", "\\")
            self.assertEqual(swift, js, js_name)

    def test_client_id_matches_docs_config(self):
        js = re.search(r'CLIENT_ID: "([^"]+)"', (ROOT / "docs" / "config.js").read_text(encoding="utf-8"))
        swift = re.search(r'clientId = "([^"]+)"', (IOS / "BabyLog" / "Config.swift").read_text(encoding="utf-8"))
        self.assertEqual(swift.group(1), js.group(1))

    def test_pbxproj_references_resolve(self):
        text = (IOS / "BabyLog.xcodeproj" / "project.pbxproj").read_text(encoding="utf-8")
        self.assertIn("objectVersion = 77;", text)
        defined = set(re.findall(r"^\s+([0-9A-F]{24}) (?:/\*.*?\*/ )?= \{", text, re.M))
        self.assertEqual(HEX24.findall(text) and set(HEX24.findall(text)) - defined, set())
        self.assertIn("path = BabyLog;", text)
        self.assertTrue((IOS / "BabyLog" / "BabyLogApp.swift").is_file())

    def test_no_personal_data(self):
        for p in SWIFT + [IOS / "BabyLog.xcodeproj" / "project.pbxproj"]:
            low = p.read_text(encoding="utf-8").lower()
            for word in ("mikey", "@gmail", "yisen"):
                self.assertNotIn(word, low, p)


if __name__ == "__main__":
    unittest.main()
