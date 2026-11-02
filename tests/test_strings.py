"""
test_strings.py — i18n/strings.json, the bilingual string table the native app is built from.

    python tests/test_strings.py

Static checks only, no Node: the JSON parses, the locales are en and zh-Hans, every entry has
both languages and a `where`, the {placeholders} agree between the two, every Chinese value is
actually Chinese (brand names excepted), the keys are unique and sorted, the file is UTF-8
without a BOM with LF endings, and the table is big enough to be the whole app.
"""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path[:0] = [str(HERE), str(ROOT)]

import json
import re
import unittest

STRINGS = ROOT / "i18n" / "strings.json"
LOCALES = ["en", "zh-Hans"]
MIN_ENTRIES = 250

# A zh-Hans value may be free of Chinese only when the English is one of these product or brand
# names, which are not translated.
BRAND_NAMES = {"Similac", "Enfamil", "Baby Log", "Siri", "OneDrive", "GitHub", "TestFlight", "ml", "oz"}

PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
CJK = re.compile(r"[一-鿿㐀-䶿]")
KEY = re.compile(r"^[a-z][a-zA-Z0-9]*(\.[a-z][a-zA-Z0-9]*)+$")


def _no_duplicates(pairs):
    seen = set()
    for k, _ in pairs:
        if k in seen:
            raise ValueError(f"duplicate key {k!r}")
        seen.add(k)
    return dict(pairs)


class StringsFile(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = STRINGS.read_bytes()
        cls.doc = json.loads(cls.raw.decode("utf-8"), object_pairs_hook=_no_duplicates)
        cls.strings = cls.doc["strings"]

    def test_encoding_utf8_no_bom_lf(self):
        self.assertFalse(self.raw.startswith(b"\xef\xbb\xbf"), "a BOM")
        self.raw.decode("utf-8")  # strict: raises on anything that is not UTF-8
        self.assertNotIn(b"\r", self.raw, "CR endings")
        self.assertTrue(self.raw.endswith(b"\n"))

    def test_shape(self):
        self.assertEqual(self.doc["_locales"], LOCALES)
        self.assertTrue(self.doc["_about"].strip())
        self.assertIsInstance(self.doc["_glossary"], dict)
        self.assertTrue(self.doc["_glossary"])
        self.assertIsInstance(self.strings, dict)

    def test_enough_entries(self):
        self.assertGreaterEqual(len(self.strings), MIN_ENTRIES)

    def test_keys_unique_sorted_and_well_formed(self):
        keys = list(self.strings)
        self.assertEqual(keys, sorted(keys), "keys are not sorted")
        self.assertEqual(len(keys), len(set(keys)))
        for k in keys:
            self.assertRegex(k, KEY)

    def test_every_entry_has_both_languages_and_where(self):
        for key, entry in self.strings.items():
            with self.subTest(key=key):
                self.assertEqual(set(entry), {"en", "zh-Hans", "where"}, "exactly en, zh-Hans, where")
                for field in ("en", "zh-Hans", "where"):
                    self.assertIsInstance(entry[field], str)
                    self.assertTrue(entry[field].strip(), f"empty {field}")

    def test_placeholders_match(self):
        for key, entry in self.strings.items():
            with self.subTest(key=key):
                en, zh = set(PLACEHOLDER.findall(entry["en"])), set(PLACEHOLDER.findall(entry["zh-Hans"]))
                self.assertEqual(en, zh, "placeholders differ between en and zh-Hans")
                # A brace that is not a placeholder is a typo in either language.
                for text in (entry["en"], entry["zh-Hans"]):
                    self.assertEqual(text.count("{"), len(PLACEHOLDER.findall(text)), f"stray brace in {text!r}")
                    self.assertEqual(text.count("}"), len(PLACEHOLDER.findall(text)))

    def test_chinese_is_chinese(self):
        for key, entry in self.strings.items():
            with self.subTest(key=key):
                if entry["en"] in BRAND_NAMES:
                    continue
                self.assertRegex(entry["zh-Hans"], CJK, f"no Chinese in {entry['zh-Hans']!r}")

    def test_plural_pairs_are_complete(self):
        """A `.one` has its `.other`, the English forms differ and the Chinese forms are one
        string. (A bare `.other` — day.other, colour.other — is the word Other, not a plural.)"""
        for key, entry in self.strings.items():
            if not key.endswith(".one"):
                continue
            other = key[:-len(".one")] + ".other"
            with self.subTest(key=key):
                self.assertTrue(other in self.strings, f"{key} has no {other}")
                self.assertNotEqual(entry["en"], self.strings[other]["en"], "a plural pair with one English form")
                self.assertEqual(entry["zh-Hans"], self.strings[other]["zh-Hans"], "Chinese does not inflect")

    def test_glossary_words_are_used(self):
        """The glossary's core vocabulary appears in the table — the file is not padded with
        unrelated words while the real screens go untranslated."""
        for en, zh in [("Feed", "喂奶"), ("Wet", "尿湿"), ("Dirty", "便便"), ("Catch up", "补记"),
                       ("Needs check", "待核对"), ("Looks right", "没问题"), ("Same as last", "同上次"),
                       ("Night mode", "夜间模式"), ("Outing checklist", "出门清单")]:
            with self.subTest(en=en):
                hits = [e for e in self.strings.values() if en in e["en"] and zh in e["zh-Hans"]]
                self.assertTrue(hits, f"{en!r} → {zh!r} not in the table")


if __name__ == "__main__":
    unittest.main(verbosity=2)
