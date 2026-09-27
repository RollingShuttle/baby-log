"""
test_phone.py — the iPhone bundle in docs/, checked from Python (SPEC.md §7.5).

    python tests/test_phone.py

The screens themselves need a phone to judge, but plenty about this bundle is checkable without
one: that every file the service worker promises to cache exists, that the iOS rules are actually
in the markup and the stylesheet, that every type of entry has a row renderer that opens its
editor, that the open editor is written to bl.draft, and that no client ID has been committed.

The last two classes run the bundle under Node: a syntax check, and a smoke run of app.js on a
small fake DOM and fake IndexedDB — boot, the six screens, an editor of every type, a write, a
delete, a draft and the night switch — so a reference error in a render path fails here rather
than in a nursery at 3 a.m. Both skip with a message when no Node binary is found.
"""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path[:0] = [str(HERE), str(ROOT)]

import json
import re
import struct
import subprocess
import unittest

import _node

DOCS = ROOT / "docs"
REQUIRED = ["index.html", "style.css", "app.js", "config.js", "core.js", "graph.js", "store.js",
            "sync.js", "sw.js", "manifest.webmanifest", "icon-180.png"]
TYPES = ["feed", "diaper", "sleep", "pump", "growth", "health", "note"]   # SPEC.md §3.2
SCRIPT_ORDER = ["config.js", "core.js", "graph.js", "store.js", "sync.js", "app.js"]


def text(name):
    return (DOCS / name).read_text(encoding="utf-8")


def code(name):
    """The file with its comments stripped. The rules below are about what the code does;
    the comments deliberately *name* the things being avoided in order to explain why."""
    src = text(name)
    src = re.sub(r"/\*.*?\*/", " ", src, flags=re.DOTALL)
    return re.sub(r"^\s*//.*$", " ", src, flags=re.MULTILINE)


def rule(css, selector):
    """The body of the first CSS rule whose selector list contains `selector` exactly."""
    css = re.sub(r"/\*.*?\*/", " ", css, flags=re.DOTALL)
    for m in re.finditer(r"([^{}]+)\{([^}]*)\}", css):
        selectors = [s.strip() for s in m.group(1).split(",")]
        if selector in selectors:
            return m.group(2)
    return None


class TestBundle(unittest.TestCase):
    def test_every_file_is_present(self):
        for name in REQUIRED:
            self.assertTrue((DOCS / name).exists(), f"docs/{name} is missing")

    def test_the_service_worker_only_promises_files_that_exist(self):
        """A precache list with a missing entry makes addAll reject and the app never installs."""
        listed = re.findall(r'"\./([^"]*)"', text("sw.js"))
        self.assertIn("", listed, "sw.js must cache ./ — the start_url")
        for name in listed:
            if name:
                self.assertTrue((DOCS / name).exists(), f"sw.js caches {name}, which does not exist")

    def test_the_manifest_is_valid_and_points_at_the_icon(self):
        m = json.loads(text("manifest.webmanifest"))
        self.assertEqual(m["start_url"], ".")
        self.assertEqual(m["scope"], ".")
        self.assertEqual(m["display"], "standalone")
        self.assertEqual(m["theme_color"], "#F2F5F4")
        src = m["icons"][0]["src"]
        self.assertTrue((DOCS / src).exists())

    def test_the_icon_is_a_real_180_square_png(self):
        data = (DOCS / "icon-180.png").read_bytes()
        self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
        width, height = struct.unpack(">II", data[16:24])
        self.assertEqual((width, height), (180, 180), "apple-touch-icon must be 180x180")

    def test_the_files_are_utf8_lf_and_bom_free(self):
        for name in ("index.html", "style.css", "app.js"):
            raw = (DOCS / name).read_bytes()
            self.assertFalse(raw.startswith(b"\xef\xbb\xbf"), f"{name} has a BOM")
            self.assertNotIn(b"\r\n", raw, f"{name} has CRLF line endings")


class TestIosRules(unittest.TestCase):
    """SPEC.md §7.5 — the ones that break in specific ways rather than looking slightly off."""

    def setUp(self):
        self.html = text("index.html")
        self.css = text("style.css")

    def test_home_screen_install_meta_is_present(self):
        for meta in ("apple-mobile-web-app-capable", "mobile-web-app-capable", "apple-touch-icon"):
            self.assertIn(meta, self.html, f"{meta} missing — installs badly")
        self.assertIn('name="apple-mobile-web-app-status-bar-style" content="black-translucent"', self.html)
        self.assertIn('<title>Baby Log</title>', self.html)

    def test_the_theme_colour_meta_is_the_light_background(self):
        self.assertIn('<meta name="theme-color" content="#F2F5F4">', self.html)
        self.assertIn('<link rel="manifest" href="manifest.webmanifest">', self.html)

    def test_the_viewport_covers_the_safe_areas(self):
        self.assertIn("viewport-fit=cover", self.html, "without this the safe-area insets resolve to zero")

    def test_safe_area_insets_are_used_on_every_edge(self):
        for edge in ("safe-area-inset-top", "safe-area-inset-bottom",
                     "safe-area-inset-left", "safe-area-inset-right"):
            self.assertIn(f"env({edge}", self.css, f"{edge} unused")

    def test_no_hundred_vh(self):
        """100vh is wrong on iOS Safari with a visible URL bar; 100dvh is the fix."""
        self.assertNotIn("100vh", code("style.css"))
        self.assertIn("100dvh", self.css)

    def test_inputs_are_sixteen_pixels(self):
        """Anything smaller and Safari zooms the page on focus and never zooms back."""
        block = re.search(r'textarea, input\[type="text"\][^{]*\{[^}]*\}', self.css)
        self.assertIsNotNone(block, "the shared input rule went missing")
        self.assertIn("font-size: 16px", block.group(0))
        for kind in ("number", "date", "time", "datetime-local"):
            self.assertIn(f'input[type="{kind}"]', block.group(0), f"{kind} inputs are not in the 16px rule")

    def test_touch_targets_are_forty_four_pixels(self):
        for selector in (".btn", ".tab", ".chip", ".toast-btn", ".amt button", ".toggle", ".cell", ".back"):
            body = rule(self.css, selector)
            self.assertIsNotNone(body, f"{selector} rule went missing")
            self.assertRegex(body, r"(min-height|height): 44px", f"{selector} is under 44 px")
        confirm = rule(self.css, ".confirm-sheet .actions .btn")
        self.assertIn("min-height: 48px", confirm, "the Keep / Delete buttons are 48 px (§7.4)")

    def test_number_fields_ask_for_the_right_keyboard(self):
        js = text("app.js")
        self.assertIn('inputmode: "numeric"', js)
        self.assertIn('inputmode: "decimal"', js)
        # oz amounts and temperatures are decimal, ml amounts numeric (§7.5)
        self.assertIn('inputmode: u === "oz" ? "decimal" : "numeric"', js)
        self.assertRegex(js, r'"Temp \(°C\)"[\s\S]{0,200}inputmode: "decimal"')

    def test_the_tab_bar_hides_while_the_keyboard_is_up(self):
        self.assertIn("body.keyboard .tabs", self.css)
        self.assertIn('classList.add("keyboard")', text("app.js"))
        self.assertIn('classList.remove("keyboard")', text("app.js"))

    def test_every_pushed_screen_has_its_own_back_control(self):
        """Standalone has no browser back button and no edge-swipe."""
        self.assertIn('id="back"', self.html)
        self.assertIn("function back()", text("app.js"))
        self.assertIn('show("editor", { push: true })', text("app.js"))

    def test_night_is_a_class_not_a_colour_scheme(self):
        self.assertIn("color-scheme: light", self.css)
        self.assertIn('<meta name="color-scheme" content="light">', self.html)
        self.assertIn("body.night", self.css)
        night = rule(self.css, "body.night")
        for token, value in (("--bg", "#060505"), ("--surface", "#110E0C"), ("--ink", "#CF8866"),
                             ("--muted", "#8A6350"), ("--line", "#261C17"), ("--feed", "#D8703F")):
            self.assertIn(f"{token}:", night)
            self.assertRegex(night, rf"{token}:\s*{value}", f"night {token} is not {value}")
        js = code("app.js")
        self.assertIn('classList.toggle("night"', js)
        self.assertIn('"#000000"', js)
        self.assertIn('"#F2F5F4"', js)
        self.assertIn('meta[name="theme-color"]', js)

    def test_the_light_palette_and_font_stack(self):
        root = rule(self.css, ":root")
        for token, value in (("--bg", "#F2F5F4"), ("--surface", "#FFFFFF"), ("--ink", "#15242A"),
                             ("--muted", "#5D6D72"), ("--line", "#DCE3E2"), ("--feed", "#C4661A"),
                             ("--feed-soft", "#FBEAD9"), ("--diaper", "#0E7773"), ("--diaper-soft", "#D8EFEC"),
                             ("--wet", "#2A74BA"), ("--dirty", "#85552A"), ("--ok", "#2B7B3B")):
            self.assertRegex(root, rf"{token}:\s*{value}", f"{token} is not {value}")
        self.assertIn('-apple-system, BlinkMacSystemFont, "SF Pro Text", system-ui, "Microsoft YaHei"', root)
        self.assertIn("tabular-nums", self.css)

    def test_scripts_load_in_order(self):
        srcs = re.findall(r'<script src="([^"]+)"></script>', self.html)
        self.assertEqual(srcs, SCRIPT_ORDER)

    def test_the_toast_sits_above_the_tab_bar_in_the_safe_area(self):
        toast = rule(self.css, ".toast")
        self.assertIn("--tabs-h", toast)
        self.assertIn("--safe-b", toast)


class TestSafety(unittest.TestCase):
    def test_the_client_id_is_a_guid(self):
        """Filled in on 26 Sep 2026 from the owner's Entra registration. It must look like an
        Application (client) ID — a typo here fails silently as a sign-in that never returns."""
        m = re.search(r'CLIENT_ID:\s*"([^"]*)"', text("config.js"))
        self.assertIsNotNone(m, "config.js lost its CLIENT_ID line")
        self.assertRegex(m.group(1).strip(), r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")

    def test_no_system_dialogs(self):
        """confirm() and alert() block the page and look nothing like the app; every ask is an
        in-page sheet (§7.4)."""
        for name in ("app.js", "store.js", "sync.js", "graph.js"):
            src = code(name)
            for bad in ("confirm(", "alert(", "prompt("):
                self.assertNotIn(bad, src, f"{name} calls {bad}")

    def test_the_only_scope_requested_is_the_app_folder(self):
        cfg = code("config.js")
        self.assertIn("Files.ReadWrite.AppFolder", cfg)
        for wider in ("Files.ReadWrite.All", "Files.Read.All", "Sites.", "User.ReadWrite"):
            self.assertNotIn(wider, cfg, f"{wider} would reach beyond the app folder")

    def test_the_phone_never_creates_a_child(self):
        """§3.3: it can revise one; only the PC and the paper import create."""
        js = code("app.js")
        self.assertIn("Store.reviseChild(", js)
        self.assertNotIn("newChild", js)
        self.assertIn("Waiting for the first sync", js)

    def test_the_phone_only_syntax_node_16_understands(self):
        js = code("app.js")
        for bad in ("??=", ".at(", "structuredClone"):
            self.assertNotIn(bad, js)
        self.assertNotRegex(js, r"^\s*await ", "top-level await")


class TestEditingSurfaces(unittest.TestCase):
    """§8.3: every surface that shows an entry opens its editor, and the row carries its id."""

    def test_every_type_has_a_row_renderer_carrying_the_event_id(self):
        src = code("app.js")
        self.assertIn('"data-event-id": ev.event_id', src)
        block = src[src.index("const ROW_SUB = {"):src.index("function eventRow(")]
        for t in TYPES:
            self.assertRegex(block, rf"\b{t}: \(ev\) =>", f"no row renderer for {t}")
        row = src[src.index("function eventRow("):src.index("function feedButton(")]
        self.assertIn('"data-event-id": ev.event_id', row)
        self.assertIn("openEditor({ event: ev })", row)

    def test_the_editor_has_a_section_for_every_type(self):
        src = code("app.js")
        for t in TYPES:
            self.assertIn(f"{t}: {t}Section", src, f"no editor section for {t}")
            self.assertIn(f"function {t}Section(", src)

    def test_tiles_cards_and_cells_carry_the_id(self):
        src = code("app.js")
        for fn, end in (("function nowPanel(", "function runningCard("),
                        ("function runningCard(", "function logBar("),
                        ("function renderDay(", "function renderTrends("),
                        ("function renderDeletedCard(", "function draftFrom(")):
            block = src[src.index(fn):src.index(end)]
            self.assertIn('"data-event-id"', block, f"{fn} renders entries without their id")

    def test_the_toasts_offer_undo_and_edit(self):
        src = code("app.js")
        diaper = src[src.index("async function writeDiaper("):src.index("async function undoNew(")]
        self.assertIn('label: "Undo"', diaper)
        self.assertIn('label: "Edit"', diaper)
        delete = src[src.index("async function deleteEntry("):src.index("function onSync(")]
        self.assertIn('showToast("Deleted", [{ label: "Undo"', delete)

    def test_the_same_diaper_rule_is_two_minutes_from_this_phone(self):
        src = code("app.js")
        block = src[src.index("async function quickDiaper("):src.index("async function writeDiaper(")]
        self.assertIn("2 * MIN", block)
        self.assertIn("sameAs", block)
        self.assertIn("Same as the", src)
        self.assertIn("Log another", src)

    def test_delete_asks_in_page_with_keep_and_delete(self):
        src = code("app.js")
        self.assertIn("confirm-sheet", src)
        block = src[src.index('class: "confirm-sheet"'):]
        block = block[:block.index("ed-foot")]
        self.assertIn('"Keep"', block)
        self.assertIn('"Delete"', block)
        self.assertIn("Delete ${TYPE_LABEL[d.type].toLowerCase()} ${Core.fmtTime(d.time)}?", block)

    def test_feed_always_opens_a_new_bottle_feed(self):
        """§6.2 since 27 Sep 2026: no timer to resume, so Feed never reopens a running one."""
        src = code("app.js")
        block = src[src.index("function feedButton("):src.index("async function sleepButton(")]
        self.assertIn('openEditor({ type: "feed" })', block)
        self.assertNotIn("run[0]", block)
        self.assertNotIn("Start another feed", src)
        self.assertNotIn("Feeding…", src[src.index("function logBar("):src.index("const ROW_SUB")])

    def test_the_validation_messages_match_the_pc(self):
        src = code("app.js")
        for msg in ("Start can't be more than 10 minutes in the future", "End can't be before Start",
                    "Made can't be less than leftover", "That's more than twice his biggest recent feed. Save anyway?",
                    "Not saved — storage full"):
            self.assertIn(msg, src)

    def test_feed_portions_are_cleaned_on_every_write_path(self):
        """"Another portion" leaves a 0 ml row; Save dropped it and a side tap did not, so the
        two paths disagreed about one draft."""
        src = code("app.js")
        self.assertIn("const cleanFeed = (data) =>", src)
        for fn, end in (("async function saveEditor(", "async function deleteEntry("),
                        ("async function writeFromEditor(", "function diaperSection(")):
            body = src[src.index(fn):src.index(end)]
            self.assertIn("cleanFeed(", body, f"{fn} does not clean the portions")
            self.assertLess(body.index("cleanFeed("), body.index("Core.validate("))


class TestBottleOnly(unittest.TestCase):
    """SPEC v3 (27 Sep 2026): breast feeding is no longer entered, amounts come from a range
    the parent moves up as he grows, the formula name is remembered, paper slips have their own
    screen, and the pill is the sync button."""

    def test_no_side_timer_markup_remains(self):
        src = code("app.js")
        for gone in ("Stop at", "startSide(", "stopFeedAt(", "or type minutes", "Tap a side to start",
                     "data-side-from", "usualFeedMs"):
            self.assertNotIn(gone, src, f"{gone} is still in app.js")
        self.assertIn("swipe", src, "the swipe rows must survive the rewrite")
        self.assertIn("function swipeRow(", src)
        css = code("style.css")
        self.assertNotIn(".side {", css)

    def test_end_is_hidden_for_feeds_and_breast_seconds_are_read_only(self):
        src = code("app.js")
        editor = src[src.index("function renderEditor("):src.index("function changeType(")]
        self.assertIn('TIMED.includes(d.type) && d.type !== "feed"', editor)
        feed = src[src.index("function feedSection("):src.index("function rangeControl(")]
        self.assertIn("breast-line", feed)
        self.assertIn("Core.breastSeconds(", feed)
        for control in ("br.left_s = ", "br.right_s = ", "br.total_s = ", "data.timer = "):
            self.assertNotIn(control, feed, f"the feed editor still writes {control.strip()}")
        save = src[src.index("async function saveEditor("):src.index("async function deleteEntry(")]
        self.assertNotIn("data.breast = ", save)
        self.assertNotIn("breast: null", save)

    def test_formula_chips_come_from_core_and_the_last_one_is_preselected(self):
        src = code("app.js")
        self.assertIn("Core.formulaChoices(recentFormulas())", src)
        self.assertIn("const lastFormula = () => formulaChoices()[0]", src)
        self.assertIn('formula: kind === "formula" ? lastFormula() : null', src)
        feed = src[src.index("function feedSection("):src.index("function rangeControl(")]
        self.assertIn('"Other…"', feed)
        self.assertIn('class: "formula-other"', feed)
        self.assertIn('if (b.kind !== "formula") return null;', feed, "switching kind must hide the chips")

    def test_quick_amounts_follow_quick_mode_and_the_range_saves_as_it_changes(self):
        src = code("app.js")
        quick = src[src.index("function quickAmounts("):src.index("function recentFormulas(")]
        self.assertIn('s.quick_mode === "range"', quick)
        self.assertIn("Core.quickRange(s.quick_from, s.quick_to, s.quick_step)", quick)
        rng = src[src.index("function rangeControl("):src.index("function diaperSection(")]
        self.assertIn("Store.setSettings({ [key]: v })", rng)
        self.assertIn("redraw()", rng)
        self.assertIn('inputmode: u === "oz" ? "decimal" : "numeric"', rng)
        form = src[src.index("function settingsForm("):src.index("function renderChildCard(")]
        for key in ("quick_from", "quick_to", "quick_step"):
            self.assertIn(f'"{key}"', form, f"Settings has no {key} field")
        self.assertIn('"a range"', form)
        store = code("store.js")
        defaults = store[store.index("const SETTINGS = {"):store.index("const QUICK_MODES")]
        self.assertIn('quick_mode: "range"', defaults)
        self.assertIn("quick_from: 50, quick_to: 100, quick_step: 10", defaults)

    def test_the_catch_up_screen_exists_and_writes_ordinary_entries(self):
        self.assertIn('id="screen-catchup"', text("index.html"))
        src = code("app.js")
        self.assertIn('catchup: document.getElementById("screen-catchup")', src)
        self.assertIn('case "catchup": renderCatchUp(); break;', src)
        more = src[src.index("function logBar("):src.index("const ROW_SUB")]
        self.assertIn('"Catch up"', more)
        self.assertIn("openCatchUp()", more)
        render = src[src.index("function renderCatchUp("):src.index("async function catchUpWrite(")]
        self.assertIn("rows.map(swipeRow)", render, "the added rows must be swipeable and carry data-event-id")
        self.assertIn('type: "date"', render)
        self.assertIn('type: "time"', render)
        self.assertIn('"Done"', render)
        write = src[src.index("async function catchUpWrite("):src.index("const catchUpFeed")]
        self.assertIn("Store.newEvent({ type, time, end, data", write)
        self.assertIn("Sync.afterWrite()", write)
        self.assertIn("Type the time first", write)
        self.assertIn('cu.time = "";', write)
        self.assertIn("validateDraft(", write)
        self.assertIn('const catchUpFeed = (mlv) => catchUpWrite("feed", { bottles: [newPortion(mlv)] });', src)

    def test_the_pill_is_the_sync_button(self):
        src = code("app.js")
        self.assertIn('document.getElementById("pill").addEventListener("click", pillTap)', src)
        tap = src[src.index("async function pillTap("):src.index("function updateBadge(")]
        self.assertIn("Sync.run()", tap)
        sync = src[src.index("function onSync("):src.index("function tick(")]
        self.assertIn('document.getElementById("sync-line")', sync)
        self.assertIn("Sync.statusText()", sync)
        card = src[src.index("function renderSyncCard("):src.index("function renderNeedsCard(")]
        self.assertLess(card.index('"Sync now"'), card.index('id: "sync-line"'), "the line goes under Sync now")


class TestDoubleTaps(unittest.TestCase):
    """iOS has no click delay at width=device-width: a sleepy double tap must write once."""

    def test_save_and_the_timer_actions_refuse_a_second_tap(self):
        src = code("app.js")
        for fn in ("async function saveEditor(", "async function writeFromEditor("):
            body = src[src.index(fn):]
            body = body[:body.index("\n}")]
            self.assertIn("if (e.saving) return;", body, f"{fn} has no in-flight guard")
            self.assertIn("setSaving(e, true)", body)
        foot = src[src.index('class: "ed-foot"'):]
        foot = foot[:foot.index("renderMsg();")]
        self.assertIn('id: "ed-save", type: "button", disabled: e.saving', foot)
        self.assertIn('id: "ed-delete", type: "button", disabled: e.saving', foot)

    def test_one_tap_diapers_and_the_running_card_are_guarded(self):
        src = code("app.js")
        diaper = src[src.index("async function writeDiaper("):src.index("async function undoNew(")]
        self.assertIn("if (writing) return;", diaper)
        self.assertIn("finally { writing = false; }", diaper)
        for fn in ("async function switchSide(", "async function stopNowFor("):
            body = src[src.index(fn):]
            body = body[:body.index("\n}")]
            self.assertIn("if (busy.has(ev.event_id)) return;", body, f"{fn} has no in-flight guard")
            self.assertIn("finally { busy.delete(ev.event_id); }", body)


class TestDraftsAndSync(unittest.TestCase):
    def test_the_open_editor_is_written_to_a_draft(self):
        """§7.4: bl.draft on each input, debounced 300 ms, restored under 12 h."""
        src = code("app.js")
        self.assertIn("Store.setDraft(", src)
        block = src[src.index("function markDirty("):src.index("function stopDraft(")]
        self.assertIn("300", block)
        self.assertIn('screen: "editor"', block)
        self.assertIn("saved_at: Core.nowIso()", block)
        self.assertIn("DRAFT_MAX_MS = 12 * HOUR", src)
        self.assertIn("Draft restored", src)
        self.assertIn('screens.editor.addEventListener("input", markDirty)', src)
        # cleared on Save / Delete / Cancel
        for fn, end in (("function closeEditor(", "let draftTimer"),):
            self.assertIn("Store.clearDraft()", src[src.index(fn):src.index(end)])

    def test_a_pull_that_changes_the_open_record_re_renders_it(self):
        src = code("app.js")
        block = src[src.index("function onSync("):src.index("function tick(")]
        self.assertIn("Updated from ${whose(rec)}", block)
        self.assertIn("renderEditor()", block)
        self.assertIn("Sync.onChange(onSync)", src)

    def test_switch_and_stop_on_another_devices_feed_flush_then_pull(self):
        src = code("app.js")
        block = src[src.index("async function guardOther("):src.index("async function switchSide(")]
        self.assertIn("Sync.run()", block)
        self.assertIn("Updated on ${whose(cur)} — look again", block)
        for fn in ("async function switchSide(", "async function stopNowFor(", "async function writeFromEditor("):
            body = src[src.index(fn):]
            body = body[:body.index("\n}")]
            self.assertIn("guardOther(", body, f"{fn} skips the guard")

    def test_a_revise_or_delete_pulls_first_when_stale(self):
        src = code("app.js")
        block = src[src.index("async function pullIfStale("):src.index("async function saveEditor(")]
        self.assertIn("Sync.stalePull(Store.meta())", block)
        self.assertIn("Syncing", src)
        save = src[src.index("async function saveEditor("):src.index("async function deleteEntry(")]
        self.assertLess(save.index("pullIfStale(e)"), save.index("Store.revise("))
        delete = src[src.index("async function deleteEntry("):src.index("function onSync(")]
        self.assertLess(delete.index("pullIfStale(e)"), delete.index("Store.tombstone("))

    def test_boot_order(self):
        """Store.open() → label → render → Graph.resume() in the background → Sync.start() after
        it (§7.1: the sign-in library, fetched from a CDN, is never on the critical path)."""
        block = code("app.js")
        block = block[block.index("async function boot("):]
        order = [block.index(s) for s in ("await Store.open()", "askLabel()", "serviceWorker.register",
                                          'setTab("now")', "restoreDraft()", "Graph.resume()", "Sync.start()")]
        self.assertEqual(order, sorted(order))
        self.assertNotIn("await Graph.resume()", block, "the first render must not wait on the CDN")
        self.assertIn("Graph.resume().then(() => { renderPill(); Sync.start(); })", block)
        self.assertIn('"visibilitychange"', block)
        self.assertIn("Who is holding this phone?", code("app.js"))

    def test_a_failed_library_load_is_retried_when_the_phone_comes_back(self):
        """Sync's own triggers skip while signed out, so the app has to call Graph.resume() again
        itself on visibilitychange and online."""
        block = code("app.js")
        block = block[block.index("async function boot("):]
        self.assertIn("resumeIfSignedOut()", block[:block.index("function resumeIfSignedOut(")])
        self.assertIn('addEventListener("online", resumeIfSignedOut)', block)
        retry = block[block.index("function resumeIfSignedOut("):]
        self.assertIn("if (!Graph.configured() || Graph.isSignedIn()) return;", retry)
        self.assertIn("Graph.resume().then((ok) => { if (ok) { renderPill(); Sync.run(); } })", retry)

    def test_an_echo_of_the_open_record_keeps_the_typed_fields(self):
        """A byte-identical copy under another file name is not a change: the object is swapped,
        the draft and the notice are left alone."""
        src = code("app.js")
        block = src[src.index("function onSync("):src.index("function tick(")]
        self.assertIn("rec.revision === e.event.revision && rec.created_at === e.event.created_at", block)
        self.assertIn("rec.device === e.event.device && rec.deleted === e.event.deleted", block)
        self.assertIn("if (!same) {", block)

    def test_a_collision_is_said_on_any_screen_and_listed_in_settings(self):
        src = code("app.js")
        block = src[src.index("function onSync("):src.index("function tick(")]
        self.assertIn("showConflicts(conflicts)", block)
        self.assertIn("Deleted on ${whose(other)}", block)
        self.assertIn("Updated from ${whose(other)}", block)
        card = src[src.index("function renderSyncCard("):src.index("function renderNeedsCard(")]
        self.assertIn("Changed on two devices", card)
        self.assertIn('"data-event-id": c.event_id', card)
        self.assertIn("Sync.fullSync()", card)
        self.assertIn('"Sync now"', card)

    def test_the_pill_taps_to_sign_in_or_to_details(self):
        src = code("app.js")
        block = src[src.index("async function pillTap("):src.index("function updateBadge(")]
        self.assertIn("Graph.signIn()", block)
        self.assertIn('setTab("settings")', block)
        self.assertIn("Sync.status()", src)

    def test_the_night_override_persists_until_the_next_boundary(self):
        src = code("app.js")
        block = src[src.index("function applyNight("):src.index("function toggleNight(")]
        self.assertIn("night_override", block)
        self.assertIn("Core.isNight(", block)
        self.assertIn("Store.setSettings({ night_override: null })", block)


# ---------------------------------------------------------------- under Node
SMOKE = r"""
const fs = require("fs"), path = require("path"), vm = require("vm");
const DOCS = %(docs)s;
const results = [];
const check = (name, ok, detail) => results.push({ name, ok: !!ok, detail: detail === undefined ? "" : String(detail) });

// -- a fake DOM: just enough for el(), fill(), the selectors app.js uses, and the id lookups
const camel = (s) => s.replace(/-([a-z])/g, (m, c) => c.toUpperCase());
class Text { constructor(t) { this.nodeType = 3; this.textContent = String(t); } }
class Node {
  constructor(tag) {
    this.nodeType = 1; this.tagName = tag.toUpperCase(); this.children = []; this.attrs = {};
    this.listeners = {}; this.hidden = false; this.dataset = {}; this.style = {}; this.className = "";
    this.value = ""; this.checked = false; this.disabled = false; this.parent = null;
  }
  get classList() {
    const self = this;
    const set = () => new Set(self.className.split(/\s+/).filter(Boolean));
    const put = (s) => { self.className = Array.from(s).join(" "); };
    return {
      add: (c) => { const s = set(); s.add(c); put(s); },
      remove: (c) => { const s = set(); s.delete(c); put(s); },
      contains: (c) => set().has(c),
      toggle: (c, on) => { const s = set(); if (on === undefined) on = !s.has(c); if (on) s.add(c); else s.delete(c); put(s); return on; },
    };
  }
  setAttribute(k, v) {
    this.attrs[k] = String(v);
    if (k.startsWith("data-")) this.dataset[camel(k.slice(5))] = String(v);
    if (k === "class") this.className = String(v);
    if (k === "value") this.value = String(v);
    if (k === "checked") this.checked = true;
    if (k === "disabled") this.disabled = true;
    if (k === "hidden") this.hidden = true;
  }
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }
  append(...kids) { for (const k of kids) { const n = k && k.nodeType ? k : new Text(k); n.parent = this; this.children.push(n); } }
  replaceChildren(...kids) { this.children = []; this.append(...kids); }
  addEventListener(t, fn) { (this.listeners[t] = this.listeners[t] || []).push(fn); }
  click() { for (const fn of this.listeners.click || []) fn({ target: this }); }
  get textContent() { return this.children.map((c) => c.textContent).join(""); }
  set textContent(v) { this.children = [new Text(v)]; }
  focus() {} scrollIntoView() {}
  matches(sel) { return sel.split(",").some((s) => matchOne(this, s.trim())); }
  querySelectorAll(sel) { const out = []; walk(this, (n) => { if (n !== this && n.matches(sel)) out.push(n); }); return out; }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
}
function walk(n, fn) { if (n.nodeType !== 1) return; fn(n); for (const c of n.children) walk(c, fn); }
function matchOne(n, sel) {
  const m = /^([a-z]*)((?:[.#][\w-]+|\[[^\]]+\])*)$/i.exec(sel);
  if (!m) return false;
  if (m[1] && n.tagName !== m[1].toUpperCase()) return false;
  for (const part of m[2].match(/[.#][\w-]+|\[[^\]]+\]/g) || []) {
    if (part[0] === ".") { if (!n.classList.contains(part.slice(1))) return false; }
    else if (part[0] === "#") { if (n.attrs.id !== part.slice(1)) return false; }
    else {
      const a = /^\[([\w-]+)(?:="([^"]*)")?\]$/.exec(part);
      if (!a || !(a[1] in n.attrs)) return false;
      if (a[2] !== undefined && n.attrs[a[1]] !== a[2]) return false;
    }
  }
  return true;
}
const html = new Node("html"), head = new Node("head"), body = new Node("body");
html.append(head, body);
const theme = new Node("meta"); theme.setAttribute("name", "theme-color"); theme.setAttribute("content", "#F2F5F4"); head.append(theme);
const mk = (tag, id, cls) => { const n = new Node(tag); if (id) n.setAttribute("id", id); if (cls) n.setAttribute("class", cls); return n; };
const bar = mk("header", "bar", "bar");
bar.append(mk("button", "back", "back"), mk("h1", "title"), mk("div", "subtitle"), mk("button", "moon", "moon"), mk("button", "pill", "pill"));
const main = mk("main", "main");
for (const s of ["label", "now", "day", "trends", "settings", "editor", "catchup"]) { const n = mk("section", `screen-${s}`, "screen"); n.hidden = s !== "now"; main.append(n); }
const tabs = mk("nav", "tabs", "tabs");
for (const t of ["now", "day", "trends", "settings"]) { const b = mk("button", null, `tab${t === "now" ? " active" : ""}`); b.setAttribute("data-tab", t); tabs.append(b); if (t === "settings") b.append(mk("span", "tab-badge", "badge")); }
const toast = mk("div", "toast", "toast"); toast.hidden = true;
body.append(bar, main, tabs, toast);
const document = {
  body, head, documentElement: html, visibilityState: "visible", listeners: {},
  createElement: (t) => new Node(t), createTextNode: (t) => new Text(t),
  getElementById: (id) => html.querySelector(`#${id}`),
  querySelector: (s) => html.querySelector(s), querySelectorAll: (s) => html.querySelectorAll(s),
  addEventListener(t, fn) { (this.listeners[t] = this.listeners[t] || []).push(fn); },
};
// -- localStorage and a fake IndexedDB (memory maps, callbacks on the next tick)
const ls = new Map();
const localStorage = { getItem: (k) => (ls.has(k) ? ls.get(k) : null), setItem: (k, v) => { ls.set(k, String(v)); }, removeItem: (k) => { ls.delete(k); } };
const idb = {};
const KEYS = { events: "event_id", children: "child_id", queue: "qid" };
const later = (fn) => setTimeout(fn, 0);
const request = (result) => { const r = {}; later(() => { r.result = result; if (r.onsuccess) r.onsuccess({ target: r }); }); return r; };
const indexedDB = { open() {
  const r = {};
  later(() => {
    r.result = {
      objectStoreNames: { contains: (n) => n in idb },
      createObjectStore: (n) => { idb[n] = new Map(); },
      transaction(names) {
        const tx = { error: null };
        tx.objectStore = (n) => ({
          getAll: () => request(Array.from(idb[n].values())),
          put: (v) => { idb[n].set(v[KEYS[n]], JSON.parse(JSON.stringify(v))); },
          delete: (k) => { idb[n].delete(k); },
        });
        later(() => { if (tx.oncomplete) tx.oncomplete(); });
        return tx;
      },
    };
    if (r.onupgradeneeded) r.onupgradeneeded();
    if (r.onsuccess) r.onsuccess();
  });
  return r;
} };
const sandbox = {
  document, localStorage, indexedDB, console, setTimeout, clearTimeout, setInterval, clearInterval,
  navigator: { onLine: true }, crypto: require("crypto").webcrypto,
};
sandbox.window = sandbox; sandbox.globalThis = sandbox;
sandbox.addEventListener = (t, fn) => {};
sandbox.scrollTo = () => {};
vm.createContext(sandbox);
// Seeded: the label prompt would otherwise wait for a tap that never comes. Everything else is
// left to the defaults, so the range chips are what a fresh phone shows.
localStorage.setItem("bl.settings", JSON.stringify({ label: "Dad", device: "d-0001" }));
for (const f of ["config.js", "core.js", "graph.js", "store.js", "sync.js", "app.js"]) {
  vm.runInContext(fs.readFileSync(path.join(DOCS, f), "utf8"), sandbox, { filename: f });
}
const G = (expr) => vm.runInContext(expr, sandbox);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const screen = (name) => document.getElementById(`screen-${name}`);
const visible = () => ["label", "now", "day", "trends", "settings", "editor", "catchup"].find((s) => !screen(s).hidden);
const fire = (node, kind) => { for (const fn of node.listeners[kind] || []) fn({ target: node }); };
const chipTexts = (host) => host.querySelectorAll(".chip").map((b) => b.textContent);
const rangeInputs = () => { const r = screen("editor").querySelector(".range"); return r ? r.querySelectorAll("input") : []; };
const ids = (host) => host.querySelectorAll("[data-event-id]").map((n) => n.dataset.eventId);

(async () => {
  try {
    await sleep(80);   // boot: Store.open, Graph.resume, setTab("now"), Sync.start
    check("booted on Now", visible() === "now" && screen("now").textContent.includes("Waiting for the first sync"), screen("now").textContent.slice(0, 120));
    const feedBtn = screen("now").querySelectorAll(".btn.feed")[0];
    check("log buttons disabled without a child", feedBtn && feedBtn.disabled);
    check("pill says signed out", document.getElementById("pill").textContent.includes("Signed out"), document.getElementById("pill").textContent);

    // A child arrives from a pull.
    const child = { child_id: "C-20260921-000000-0000", revision: 1, deleted: false, reason: null, name: "Yisen", born: "2026-09-21",
      born_time: null, sex: null, birth_weight_g: 3400, targets: { feeds_per_day: 8, wet_per_day: 6, dirty_per_day: 3 }, device: "pc", created_at: "2026-09-21T00:00:00.000000+00:00" };
    check("child applied", await G("Store").applyRemote(child, "C-20260921-000000-0000-r1-0000.json"));
    G("renderNow(); renderHeader();");
    check("Now shows the child", document.getElementById("title").textContent === "Yisen" && document.getElementById("subtitle").textContent.includes("old"), document.getElementById("subtitle").textContent);
    check("log buttons enabled", !screen("now").querySelectorAll(".btn.feed")[0].disabled);

    // One-tap diaper, then the same-diaper rule.
    await G("quickDiaper(true, false)");
    check("diaper written", G("Store.events()").length === 1 && G("Store.events()")[0].type === "diaper");
    check("undo · edit toast", !toast.hidden && toast.textContent.includes("Wet") && toast.querySelectorAll(".toast-btn").length === 2, toast.textContent);
    check("queued for upload", G("Store.queue()").length === 1);
    await G("quickDiaper(false, true)");
    check("second tap within 2 min opens the editor", visible() === "editor" && screen("editor").textContent.includes("Same as the"), visible());
    check("editor draft has both", G("app.editor.draft.data.wet && app.editor.draft.data.dirty"));
    await G("saveEditor()");
    check("save wrote a revision", visible() === "now" && G("Store.events()").length === 1 && G("Store.events()")[0].revision === 2 && G("Store.events()")[0].data.dirty);

    // A bottle feed: no timer, no End, the range chips, the formula chips.
    G('openEditor({ type: "feed" })');
    check("feed editor pushed with a chevron", visible() === "editor" && !document.getElementById("back").hidden && document.getElementById("title").textContent === "Log a feed");
    check("editor has the shift chips", ["−5", "−15", "−30 min"].every((t) => screen("editor").textContent.includes(t)));
    const edText = screen("editor").textContent;
    check("no side timers, no End for a feed", !edText.includes("Stop at") && !edText.includes("Breast") && !edText.includes("type minutes") && !document.getElementById("ed-end"), edText.slice(0, 200));
    const quick = document.getElementById("ed-quick");
    check("range chips read 50…100 by default", ["50 ml", "60 ml", "70 ml", "80 ml", "90 ml", "100 ml"].every((t) => chipTexts(quick).includes(t)) && !chipTexts(quick).some((t) => t.startsWith("Same as last")), chipTexts(quick).join("|"));
    check("the range control sits beside the chips", rangeInputs().length === 3);
    quick.querySelectorAll(".chip").find((b) => b.textContent === "60 ml").click();
    check("a chip makes a formula portion with the first choice preselected", G("app.editor.draft.data.bottles.length") === 1 && G("app.editor.draft.data.bottles[0].ml") === 60 && G("app.editor.draft.data.bottles[0].formula") === "Similac", JSON.stringify(G("app.editor.draft.data.bottles")));
    check("the starter chips are Similac and Enfamil", chipTexts(screen("editor").querySelector(".chips.formula")).join(",") === "Similac,Enfamil,Other…", chipTexts(screen("editor").querySelector(".chips.formula")).join(","));
    screen("editor").querySelector(".chips.formula").querySelectorAll(".chip").find((b) => b.textContent === "Enfamil").click();
    check("plan B is one tap", G("app.editor.draft.data.bottles[0].formula") === "Enfamil");
    await G("saveEditor()");
    const feed = G("Store.events()").find((e) => e.type === "feed");
    check("feed saved with the formula and an end", feed && feed.data.bottles[0].formula === "Enfamil" && feed.data.bottles[0].ml === 60 && feed.end === feed.time && feed.data.timer === null, JSON.stringify(feed && feed.data));
    check("no breast seconds were invented", feed.data.breast.total_s === null && feed.data.breast.left_s === null);
    // The next feed preselects what was used last; Other… adds a name that becomes the next default.
    G('openEditor({ type: "feed" })');
    check("Same as last chip", chipTexts(document.getElementById("ed-quick"))[0] === "Same as last · 60 ml", chipTexts(document.getElementById("ed-quick")).join("|"));
    document.getElementById("ed-quick").querySelectorAll(".chip").find((b) => b.textContent === "70 ml").click();
    check("the last formula is preselected on the next feed", G("app.editor.draft.data.bottles[0].formula") === "Enfamil" && chipTexts(screen("editor").querySelector(".chips.formula"))[0] === "Enfamil");
    screen("editor").querySelector(".chips.formula").querySelectorAll(".chip").find((b) => b.textContent === "Other…").click();
    const otherInput = screen("editor").querySelector("input.formula-other");
    check("Other… becomes a text field", !!otherInput && G("app.editor.draft.data.bottles[0].formula") === null);
    otherInput.value = "Kendamil"; fire(otherInput, "input");
    check("a typed name lands on the portion", G("app.editor.draft.data.bottles[0].formula") === "Kendamil");
    await G("saveEditor()");
    G('openEditor({ type: "feed" })');
    document.getElementById("ed-quick").querySelectorAll(".chip").find((b) => b.textContent === "80 ml").click();
    check("the typed name is now the first choice", G("app.editor.draft.data.bottles[0].formula") === "Kendamil" && chipTexts(screen("editor").querySelector(".chips.formula")).slice(0, 2).join(",") === "Kendamil,Enfamil", chipTexts(screen("editor").querySelector(".chips.formula")).join(","));
    screen("editor").querySelector(".toggle").click();
    check("breast milk has no formula and no chips", G("app.editor.draft.data.bottles[0].kind") === "breast_milk" && G("app.editor.draft.data.bottles[0].formula") === null && !screen("editor").querySelector(".chips.formula"));
    screen("editor").querySelector(".toggle").click();
    check("back to formula, the name comes back", G("app.editor.draft.data.bottles[0].formula") === "Kendamil");
    // The range moves up the week his feeds do: typed beside the chips, saved at once.
    const rangeFrom = rangeInputs()[0];
    rangeFrom.value = "60"; fire(rangeFrom, "input");
    check("range from saved on input", G("Store.settings().quick_from") === 60 && G("Store.settings().quick_to") === 100);
    check("chips redrawn at once", chipTexts(document.getElementById("ed-quick")).includes("60 ml") && !chipTexts(document.getElementById("ed-quick")).includes("50 ml"), chipTexts(document.getElementById("ed-quick")).join("|"));
    const rangeStep = rangeInputs()[2];
    rangeStep.value = "20"; fire(rangeStep, "input");
    const mlChips = () => chipTexts(document.getElementById("ed-quick")).filter((t) => /^[0-9]+ ml$/.test(t));
    check("range step saved", G("Store.settings().quick_step") === 20 && mlChips().join(",") === "60 ml,80 ml,100 ml", mlChips().join(","));
    await G("saveEditor()");
    check("three bottle feeds saved", G("Store.events()").filter((e) => e.type === "feed").length === 3);
    G('Store.setSettings({ quick_mode: "recent" }); openEditor({ type: "feed" });');
    check("recent mode shows four chips around the median and no range control", mlChips().length === 4 && rangeInputs().length === 0, mlChips().join(","));
    G('closeEditor(); Store.setSettings({ quick_mode: "range", quick_from: 50, quick_step: 10 });');

    // Every type's editor, and Change type… across all of them.
    for (const t of ["feed", "diaper", "sleep", "pump", "growth", "health", "note"]) {
      G(`openEditor({ type: ${JSON.stringify(t)} })`);
      check(`editor renders ${t}`, visible() === "editor" && screen("editor").querySelectorAll("textarea").length === 1);
      for (const t2 of ["feed", "diaper", "sleep", "pump", "growth", "health", "note"]) G(`changeType(${JSON.stringify(t2)})`);
      check(`change type back to ${t} keeps defaults valid`, (G(`changeType(${JSON.stringify(t)}); JSON.stringify(app.editor.draft.data) === JSON.stringify(Core.defaults(${JSON.stringify(t)}))`)));
      G("closeEditor()");
    }
    // A pump saved with data; a growth saved; a health saved; a note saved.
    G('openEditor({ type: "pump" }); app.editor.draft.data.left_ml = 30; app.editor.draft.data.right_ml = 25;');
    await G("saveEditor()");
    G('openEditor({ type: "growth" }); app.editor.draft.data.weight_g = 3500;');
    await G("saveEditor()");
    G('openEditor({ type: "health" }); app.editor.draft.data.medicine = "Vitamin D"; app.editor.draft.data.dose = "1 drop";');
    await G("saveEditor()");
    G('openEditor({ type: "note" }); app.editor.draft.note = "首次微笑";');
    await G("saveEditor()");
    await G("sleepButton()");
    const types = Array.from(new Set(G("Store.events()").map((e) => e.type))).sort().join(",");
    check("one of every type saved", types === "diaper,feed,growth,health,note,pump,sleep", types);

    // Validation refuses in page.
    G('openEditor({ type: "feed" }); app.editor.draft.time = Core.isoLocal(new Date(Date.now() + 3600000));');
    await G("saveEditor()");
    check("future start refused in page", visible() === "editor" && document.getElementById("ed-msg").textContent.includes("10 minutes"), document.getElementById("ed-msg").textContent);
    G("closeEditor()");

    // Now, Day, Trends and Settings render with data, every entry carrying its id.
    G("renderNow()");
    const n = G("Store.events()").length;
    check("recent list has every entry with its id", ids(screen("now")).length >= n, `${ids(screen("now")).length} ids for ${n} events`);
    check("totals against targets", screen("now").textContent.includes("/ 8") && screen("now").textContent.includes("/ 6"));
    G('setTab("day")');
    check("day sheet renders every entry", visible() === "day" && new Set(ids(screen("day"))).size === n && screen("day").textContent.includes("Feeding") && screen("day").textContent.includes("Diapers") && screen("day").textContent.includes("Other"), `${new Set(ids(screen("day"))).size} of ${n}`);
    check("dirty box is tinted", screen("day").querySelectorAll(".glyph-box.dirty").length === 1);
    G('setTab("trends")');
    check("trends shows seven days with targets", visible() === "trends" && screen("trends").querySelectorAll("tr.openable").length === 7 && screen("trends").textContent.includes("target"));
    G('setTab("settings")');
    await sleep(10);
    const st = screen("settings").textContent;
    // With the client ID filled in (26 Sep 2026) the "not configured" notice is gone and the Sync
    // card offers Sign in instead.
    check("settings has every section", ["This phone", "Child", "Sync", "Needs check (0)", "Deleted (0)", "Not signed in", "Sign in"].every((s) => st.includes(s)) && !st.includes("not configured"), st.slice(0, 200));
    check("usage shown", st.includes("entries on this phone"));
    check("child form filled", screen("settings").querySelectorAll("input").some((i) => i.value === "Yisen"));

    // Delete with the in-page sheet, then Restore from Settings.
    const note = G("Store.events()").find((e) => e.type === "note");
    G(`openEditor({ event: Store.event(${JSON.stringify(note.event_id)}) })`);
    check("existing entry has Delete", screen("editor").textContent.includes("Delete") && screen("editor").textContent.includes("Save changes"));
    G("app.editor.confirming = true; renderEditor();");
    check("confirm sheet Keep / Delete", screen("editor").textContent.includes("Delete note") && screen("editor").querySelector(".confirm-sheet").querySelectorAll(".btn").length === 2);
    await G("deleteEntry()");
    check("tombstoned", G("Store.event")(note.event_id).deleted === true && G("Store.deleted()").length === 1 && toast.textContent.includes("Deleted"));
    G('setTab("settings")');
    check("deleted listed with restore", screen("settings").textContent.includes("Deleted (1)") && ids(screen("settings")).includes(note.event_id));
    await G(`restoreEntry(${JSON.stringify(note.event_id)})`);
    check("restored", G("Store.event")(note.event_id).deleted === false && G("Store.event")(note.event_id).note === "首次微笑");

    // Needs check counts on the tab.
    G(`openEditor({ event: Store.event(${JSON.stringify(note.event_id)}) }); app.editor.draft.note = "Check: 09:10 or 09:40?";`);
    await G("saveEditor()");
    check("needs check badge", document.getElementById("tab-badge").textContent === "1" && !document.getElementById("tab-badge").hidden);

    // Swipe actions: Looks right drops the question and only the question; Delete tombstones with Undo.
    G(`openEditor({ event: Store.event(${JSON.stringify(note.event_id)}) }); app.editor.draft.note = "first — Check: 09:10 or 09:40?";`);
    await G("saveEditor()");
    G('setTab("settings")');
    check("needs-check row is wrapped for swiping", !!screen("settings").querySelector(".swipe-check") && !!screen("settings").querySelector(".swipe-act.keep"));
    check("withoutCheck keeps the parent's own note", G("withoutCheck")("first — Check: 09:10 or 09:40?") === "first" && G("withoutCheck")("Check: x") === "");
    await G(`markChecked(Store.event(${JSON.stringify(note.event_id)}))`);
    check("looks right cleared the question", G("Store.event")(note.event_id).note === "first" && G("Store.needsCheck()").length === 0 && toast.textContent.includes("Checked"));
    G('setTab("now")');
    check("plain rows are swipeable too", !!screen("now").querySelector(".swipe-act.del") && !screen("now").querySelector(".swipe-act.keep"));
    await G(`quickDelete(Store.event(${JSON.stringify(note.event_id)}))`);
    check("swipe delete tombstoned with undo", G("Store.event")(note.event_id).deleted === true && toast.textContent.includes("Deleted note") && toast.textContent.includes("Undo"));
    await G(`restoreEntry(${JSON.stringify(note.event_id)})`);
    check("undo of a swipe delete restores", G("Store.event")(note.event_id).deleted === false);
    G(`openEditor({ event: Store.event(${JSON.stringify(note.event_id)}) }); app.editor.draft.note = "首次微笑";`);
    await G("saveEditor()");

    // Drafts: typed fields land in bl.draft after 300 ms and go on Cancel; restored on boot.
    G('openEditor({ type: "sleep" }); app.editor.draft.data.where = "bassinet"; markDirty();');
    check("no draft before the debounce", localStorage.getItem("bl.draft") === null);
    await sleep(400);
    const draft = JSON.parse(localStorage.getItem("bl.draft") || "null");
    check("draft written", draft && draft.screen === "editor" && draft.event_id === null && draft.fields.data.where === "bassinet", JSON.stringify(draft));
    G("app.editor = null;");   // as if the app were killed
    G("restoreDraft()");
    check("draft restored on open", visible() === "editor" && screen("editor").textContent.includes("Draft restored") && G("app.editor.draft.data.where") === "bassinet");
    G("closeEditor()");
    check("cancel clears the draft", localStorage.getItem("bl.draft") === null);
    localStorage.setItem("bl.draft", JSON.stringify({ screen: "editor", event_id: null, fields: { type: "note", data: { milestone: false } }, saved_at: "2020-01-01T00:00:00.000000+00:00" }));
    check("stale draft dropped", G("restoreDraft()") === false && localStorage.getItem("bl.draft") === null);

    // Night mode: the schedule, the moon, the theme-color swap.
    G('Store.setSettings({ night_from: "00:00", night_to: "23:59" }); applyNight();');
    check("night on by schedule", body.classList.contains("night") && theme.attrs.content === "#000000");
    G("toggleNight()");
    check("moon overrides off", !body.classList.contains("night") && theme.attrs.content === "#F2F5F4" && G("Store.settings().night_override") === "off");
    G('Store.setSettings({ night_from: "21:00", night_to: "07:00", night_override: "off" }); applyNight();');
    G('Store.setSettings({ night_from: "00:00", night_to: "00:01" }); applyNight();');
    check("override cleared at the boundary", G("Store.settings().night_override") === null);

    // The pull notice on an open editor.
    const pump = G("Store.events()").find((e) => e.type === "pump");
    G(`openEditor({ event: Store.event(${JSON.stringify(pump.event_id)}) })`);
    const remote = Object.assign({}, pump, { revision: pump.revision + 1, data: Object.assign({}, pump.data, { left_ml: 40 }), device: "d-0002", edited_by: "Mom", created_at: "2099-01-01T00:00:00.000000+00:00" });
    check("remote revision applied", await G("Store").applyRemote(remote, `${pump.event_id}-r${remote.revision}-abcd.json`));
    G(`onSync("applied", { ids: [${JSON.stringify(pump.event_id)}] })`);
    check("editor re-rendered from the pull", screen("editor").textContent.includes("Updated from Mom's phone") && G("app.editor.draft.data.left_ml") === 40, screen("editor").textContent.slice(0, 80));
    G("closeEditor()");

    // Stop on a feed another phone started: flush-then-pull first (a no-op signed out), then the stop.
    const theirs = { event_id: "E-20260924-010000-beef", revision: 1, deleted: false, reason: null, child_id: child.child_id, type: "feed",
      time: G("Core.isoLocal")(new Date(Date.now() - 600000)), end: null,
      data: Object.assign(G("Core.defaults")("feed"), { timer: { side: "left", side_started: G("Core.isoLocal")(new Date(Date.now() - 600000)) } }),
      note: "", logged_by: "Mom", edited_by: null, device: "d-0002", entered_from: "phone", created_at: "2026-09-24T01:00:00.000000+00:00" };
    check("their running feed applied", await G("Store").applyRemote(theirs, "E-20260924-010000-beef-r1-0000.json"));
    G("renderNow()");
    check("their feed shows as running here", screen("now").textContent.includes("Feeding since") && screen("now").textContent.includes("Mom"));
    check("Feed still says Feed", screen("now").querySelector(".btn.feed.big").textContent === "Feed");
    G("feedButton()");
    check("Feed opens a new feed, not the running one", visible() === "editor" && G("app.editor.event") === null, visible());
    G("closeEditor()");
    await G("stopNowFor(Store.event(" + JSON.stringify(theirs.event_id) + "))");
    const stopped = G("Store.event")(theirs.event_id);
    check("stopped their feed after the guard", stopped.end !== null && stopped.revision === 2 && stopped.data.breast.left_s >= 590 && stopped.edited_by === "Dad", JSON.stringify(stopped.data.breast));

    // A double tap writes once: Save on a new entry, the one-tap diaper, and Save/Delete go dark.
    const before = G("Store.events()").length;
    G('openEditor({ type: "growth" }); app.editor.draft.data.weight_g = 3600;');
    await G("Promise.all([saveEditor(), saveEditor()])");
    check("double-tapped Save wrote one entry", G("Store.events()").length === before + 1, G("Store.events()").length - before);
    await G("Promise.all([writeDiaper(true, false), writeDiaper(true, false)])");
    check("double-tapped Wet wrote one diaper", G("Store.events()").length === before + 2, G("Store.events()").length - before);
    G(`openEditor({ event: Store.event(${JSON.stringify(note.event_id)}) })`);
    G("setSaving(app.editor, true)");
    const saveBtn = document.getElementById("ed-save"), delBtn = document.getElementById("ed-delete");
    check("Save and Delete disabled while saving", saveBtn && saveBtn.disabled && delBtn && delBtn.disabled);
    G("setSaving(app.editor, false)");
    check("and enabled again", !saveBtn.disabled && !delBtn.disabled);
    G("closeEditor()");

    // An empty portion row ("Another portion" not yet typed) is dropped on Save, not refused.
    const feedsBefore = G("Store.events()").filter((e) => e.type === "feed").length;
    G('openEditor({ type: "feed" }); app.editor.draft.data.bottles.push({ kind: "formula", ml: 0, formula: "Kendamil" });');
    await G("saveEditor()");
    // The newest write, not the latest `time`: every feed in this run starts "now", to the second.
    const emptyFeed = G("Store.events()").filter((e) => e.type === "feed").sort((a, b) => (a.created_at < b.created_at ? 1 : -1))[0];
    check("save with an empty portion writes a feed with no bottles", visible() === "now" && G("Store.events()").filter((e) => e.type === "feed").length === feedsBefore + 1 && emptyFeed.data.bottles.length === 0, JSON.stringify(emptyFeed && emptyFeed.data));

    // A stored feed with breast seconds (a paper row) opens with one read-only line and saves without losing them.
    const paper = { event_id: "E-paper-20260922-1400-feed", revision: 1, deleted: false, reason: null, child_id: child.child_id, type: "feed",
      time: G("Core.isoLocal")(new Date(Date.now() - 3 * 3600000)), end: null,
      data: { breast: { left_s: null, right_s: null, total_s: 900, last_side: null, approx: true }, bottles: [{ kind: "formula", ml: 20, formula: null }], made_ml: null, leftover_ml: null, timer: null },
      note: "Check: 14:00 or 14:30?", logged_by: "paper", edited_by: null, device: "paper", entered_from: "paper", created_at: "2026-09-24T01:00:00.000000+00:00" };
    check("paper feed applied", await G("Store").applyRemote(paper, "E-paper-20260922-1400-feed-r1-0000.json"));
    G(`openEditor({ event: Store.event(${JSON.stringify(paper.event_id)}) })`);
    const paperText = screen("editor").textContent;
    check("breast seconds show as one read-only line", paperText.includes("Breast ~15 min") && !paperText.includes("Stop") && !screen("editor").querySelector("#ed-end") && screen("editor").querySelectorAll(".breast-line").length === 1, paperText.slice(0, 300));
    check("its portion has no formula chip active but the chips are offered", screen("editor").querySelector(".chips.formula").querySelectorAll(".chip.active").length === 0 && !!screen("editor").querySelector(".chips.formula"));
    G('app.editor.draft.note = "looked again: 14:00";');
    await G("saveEditor()");
    const paper2 = G("Store.event")(paper.event_id);
    check("saved without losing the breast seconds", paper2.revision === 2 && paper2.data.breast.total_s === 900 && paper2.data.breast.approx === true && paper2.data.timer === null && paper2.data.bottles[0].ml === 20 && paper2.note === "looked again: 14:00", JSON.stringify(paper2.data));
    check("its end is start plus the breast minutes", paper2.end !== null && Date.parse(paper2.end) - Date.parse(paper2.time) === 900000, `${paper2.time} → ${paper2.end}`);

    // Catch up: one screen, one tap per paper slip, at the strip's date and time.
    G("openCatchUp()");
    check("catch-up screen pushed", visible() === "catchup" && !document.getElementById("back").hidden && document.getElementById("title").textContent === "Catch up", visible());
    check("catch-up strip has the date, the time, the feed chips and the diaper buttons", document.getElementById("cu-date").value === G("todayStr()") && document.getElementById("cu-time").value === "" && screen("catchup").textContent.includes("Feed · Kendamil") && ["Wet", "Dirty", "Both", "Done"].every((t) => screen("catchup").textContent.includes(t)), screen("catchup").textContent.slice(0, 300));
    const cuBefore = G("Store.events()").length;
    await G("catchUpFeed(60)");
    check("a missing time is refused in page", G("Store.events()").length === cuBefore && screen("catchup").textContent.includes("Type the time first"), screen("catchup").textContent.slice(0, 300));
    const yesterday = G("shiftDay(todayStr(), -1)");
    const cuDate = yesterday >= "2026-09-21" ? yesterday : G("todayStr()");
    G(`app.catchup.date = ${JSON.stringify(cuDate)}; app.catchup.time = "09:10";`);
    const cuFeed = await G("catchUpFeed(60)");
    check("a feed tap writes at the given date and time with the last formula", cuFeed && cuFeed.type === "feed" && cuFeed.time.startsWith(`${cuDate}T09:10:00`) && cuFeed.end === cuFeed.time && cuFeed.data.bottles[0].ml === 60 && cuFeed.data.bottles[0].formula === "Kendamil" && G("Store.events()").length === cuBefore + 1, JSON.stringify(cuFeed));
    check("only the time clears, the date stays, and the row is listed", G("app.catchup.time") === "" && G("app.catchup.date") === cuDate && ids(screen("catchup")).includes(cuFeed.event_id) && !!screen("catchup").querySelector(".swipe-act.del") && screen("catchup").textContent.includes("Added 60 ml"), screen("catchup").textContent.slice(0, 400));
    G('app.catchup.time = "09:40";');
    const cuDiaper = await G("catchUpDiaper(true, true)");
    check("a diaper tap writes wet + dirty at its time", cuDiaper && cuDiaper.type === "diaper" && cuDiaper.data.wet && cuDiaper.data.dirty && cuDiaper.time.startsWith(`${cuDate}T09:40:00`) && new Set(ids(screen("catchup"))).size === 2, JSON.stringify(cuDiaper));
    check("catch-up entries are queued for upload", G("Store.queue()").some((q) => q.body.event_id === cuDiaper.event_id));
    G('app.catchup.time = "23:59"; app.catchup.date = "2020-01-01";');
    await G("catchUpDiaper(true, false)");
    check("the editor's own rules apply", G("Store.events()").length === cuBefore + 2 && screen("catchup").textContent.includes("before Yisen was born"), screen("catchup").textContent.slice(0, 300));
    screen("catchup").querySelectorAll(".btn").find((b) => b.textContent === "Done").click();
    check("Done goes back", visible() === "now");

    // An echo of the record on screen (same substance, new object, new file name) leaves the typed note alone.
    const pump2 = G("Store.event")(pump.event_id);
    G(`openEditor({ event: Store.event(${JSON.stringify(pump.event_id)}) }); app.editor.draft.note = "typed while syncing";`);
    check("echo applied", await G("Store").applyRemote(Object.assign({}, pump2), `${pump.event_id}-r${pump2.revision}-ffff.json`));
    G(`onSync("applied", { ids: [${JSON.stringify(pump.event_id)}] })`);
    check("echo keeps the typed note and shows no notice", G("app.editor.draft.note") === "typed while syncing" && !G("app.editor.notice") && G("app.editor.event._file") === `${pump.event_id}-r${pump2.revision}-ffff.json`, G("app.editor.draft.note"));
    G("closeEditor()");
    check("setFile stamps the held record", await G("Store").setFile(pump.event_id, "stamp.json") && G("Store.event")(pump.event_id)._file === "stamp.json");

    // A collision reported by a pull: a toast on the open screen, and a row in Settings that opens the entry.
    const feedId = feed.event_id;
    G(`Store.setMeta({ conflicts: [{ event_id: ${JSON.stringify(feedId)}, at: Core.nowIso(), other: { device: "pc", edited_by: null, logged_by: "Dad", entered_from: "pc", deleted: false } }] })`);
    G("renderNow()");
    G(`onSync("applied", { ids: [], conflicts: [${JSON.stringify(feedId)}] })`);
    check("collision toast names the other device", !toast.hidden && toast.textContent.includes("Feed") && toast.textContent.includes("Updated from the PC") && toast.querySelectorAll(".toast-btn")[0].textContent === "Edit", toast.textContent);
    G('setTab("settings")');
    await sleep(10);
    check("settings lists the collision", screen("settings").textContent.includes("Changed on two devices (1)") && ids(screen("settings")).includes(feedId) && screen("settings").textContent.includes("Updated from the PC"), screen("settings").textContent.slice(0, 200));
    screen("settings").querySelectorAll("button.qrow")[0].click();
    check("the row opens the editor", visible() === "editor" && G("app.editor.event.event_id") === feedId, visible());
    G("closeEditor()");
  } catch (e) {
    check("smoke run threw", false, (e && e.stack) || String(e));
  }
  console.log(JSON.stringify(results));
  process.exit(0);
})();
"""


class TestSwipeActions(unittest.TestCase):
    """A sideways drag on a row deletes it or, on a paper row, says it looks right. Checked
    statically here; the smoke run below exercises the two actions themselves."""

    def test_every_row_list_is_swipeable(self):
        src = code("app.js")
        self.assertIn("recent.map(swipeRow)", src)
        self.assertIn("others.map(swipeRow)", src)
        self.assertIn("needs.map(swipeRow)", src)

    def test_the_wrapper_leaves_vertical_scrolling_to_the_browser(self):
        css = text("style.css")
        self.assertRegex(css, r"\.swipe\s*\{[^}]*touch-action:\s*pan-y")

    def test_a_swipe_delete_needs_no_confirm_sheet_but_offers_undo(self):
        src = code("app.js")
        fn = src[src.index("async function quickDelete"):src.index("const CHECK_TAIL_RE")]
        self.assertNotIn("confirming", fn)
        self.assertIn('"Undo"', fn)
        self.assertIn("pullIfStale", fn, "the same stale-pull guard as the editor's Delete")


class TestUnderNode(unittest.TestCase):
    def setUp(self):
        if not _node.NODE:
            self.skipTest("no Node binary found (set BABY_LOG_NODE); the JS checks are skipped")

    def test_app_js_parses(self):
        """node --check: the phone loads the file as plain script, so a syntax error is a blank
        screen with no message."""
        for name in ("app.js", "store.js", "sync.js", "graph.js", "core.js", "config.js"):
            proc = subprocess.run([_node.NODE, "--check", str(DOCS / name)], capture_output=True,
                                  text=True, encoding="utf-8", errors="replace", timeout=30)
            self.assertEqual(proc.returncode, 0, f"{name}: {proc.stderr}")

    def test_the_screens_run_on_a_fake_dom(self):
        script = SMOKE % {"docs": json.dumps(str(DOCS))}
        rc, out, err = _node.run_js(script, timeout=60)
        self.assertEqual(rc, 0, err)
        line = [l for l in out.strip().splitlines() if l.startswith("[")]
        self.assertTrue(line, f"no results printed:\n{out}\n{err}")
        results = json.loads(line[-1])
        self.assertGreaterEqual(len(results), 40)
        failed = [r for r in results if not r["ok"]]
        self.assertEqual(failed, [], "\n".join(f"{r['name']}: {r['detail']}" for r in failed))


if __name__ == "__main__":
    unittest.main(verbosity=2)
