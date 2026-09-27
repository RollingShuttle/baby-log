/* Baby Log — the iPhone client (SPEC.md §7.4–§7.6, §8).

   Four tabs (Now, Day, Trends, Settings) and one editor screen for every type of entry, pushed
   with its own back chevron because an installed web app has no browser chrome. Every number and
   every format goes through Core, so this screen and the PC never disagree; every write goes
   through Store (saved locally and queued before the UI says so) and then pokes Sync.

   Nothing here is held only in memory: the open editor's fields are written to bl.draft as they
   are typed, because iOS reloads a home-screen app freely and a redirect sign-in reloads it too.
   Must parse under Node 16 for the syntax check — no top-level await, no ??=, no .at(). */
"use strict";

const MIN = 60000, HOUR = 3600000;
const TYPE_LABEL = { feed: "Feed", diaper: "Diaper", sleep: "Sleep", pump: "Pump", growth: "Growth", health: "Health", note: "Note" };
const NEW_TITLE = { feed: "Log a feed", diaper: "Diaper", sleep: "Sleep", pump: "Pump", growth: "Weight", health: "Health", note: "Note" };
const TIMED = ["feed", "sleep", "pump"];          // the types that carry an End
const STOOL = { black: "#2A2A2A", dark_green: "#2F5A36", green: "#4F8A3A", yellow: "#D0A02A", brown: "#85552A", other: "#8A8A8A" };
const THEME_LIGHT = "#F2F5F4", THEME_NIGHT = "#000000";
const DRAFT_MAX_MS = 12 * HOUR;
const LAST_DIAPER_KEY = "bl.last_diaper";

const el = (tag, props = {}, ...kids) => {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === "class") n.className = v;
    else if (k.startsWith("on") && typeof v === "function") n.addEventListener(k.slice(2), v);
    else if (v !== null && v !== undefined && v !== false) n.setAttribute(k, v);
  }
  for (const kid of kids.flat()) {
    if (kid === null || kid === undefined || kid === false) continue;
    n.append(kid && kid.nodeType ? kid : document.createTextNode(kid));
  }
  return n;
};
/* replaceChildren turns a null into the text "null" — el() skips them, this must too. */
const fill = (host, ...kids) => host.replaceChildren(...kids.flat().filter(Boolean));

const app = {
  tab: "now",
  stack: [],          // pushed screens, for the back chevron
  date: null,         // the day the Day screen shows
  editor: null,       // see openEditor
  lastDiaper: null,   // {event_id, ms}: the last one-tap diaper from this phone (the 2-minute rule)
  night: false,
  more: false,        // the More row (Health, Note, Catch up) unfolded on Now
  storage: true,      // false when IndexedDB would not open: nothing can be saved
  catchup: null,      // see openCatchUp: {date, time, rows, msg, added, writing}
};

const screens = {
  label: document.getElementById("screen-label"),
  now: document.getElementById("screen-now"),
  day: document.getElementById("screen-day"),
  trends: document.getElementById("screen-trends"),
  settings: document.getElementById("screen-settings"),
  editor: document.getElementById("screen-editor"),
  catchup: document.getElementById("screen-catchup"),
};

// ---------------------------------------------------------------- small helpers
const pad = (n) => String(n).padStart(2, "0");
const nowIso = () => Core.isoLocal(new Date());
const todayStr = () => Core.localDate(nowIso());
const clone = (v) => JSON.parse(JSON.stringify(v));
const settings = () => Store.settings();
const unit = () => settings().units || "ml";
const myLabel = () => settings().label || "";
const amount = (ml) => Core.fmtAmount(ml, unit());
const isCheck = (ev) => /^Check: | — Check: /.test(String(ev.note || ""));   // paper joins "note — Check: …"
const events = () => Store.events();

// Milliseconds for a §3.2 string; anything else parses as best it can rather than crashing.
function ms(iso) {
  const d = Core.parseIso(iso);
  return d ? d.getTime() : Date.parse(iso);
}
// "YYYY-MM-DD" moved by n days, by local calendar (so DST days do not skip).
function shiftDay(date, n) {
  const d = new Date(Number(date.slice(0, 4)), Number(date.slice(5, 7)) - 1, Number(date.slice(8, 10)) + n);
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}
// A datetime-local input shows the string's own wall clock, exactly what every list shows.
const dtValue = (iso) => (iso ? String(iso).slice(0, 16) : "");
// ...and what is typed back becomes a §3.2 string in this phone's zone.
function dtParse(v) {
  const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(v || "");
  if (!m) return null;
  return Core.isoLocal(new Date(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], 0));
}
// A UTC created_at / last_sync_at shown as this phone's wall clock.
const clockOf = (iso) => Core.fmtTime(Core.isoLocal(new Date(Date.parse(iso))));
// "12:34" / "1:02:03" for a live feed timer — seconds matter while it runs.
function elapsedText(msv) {
  const s = Math.max(0, Math.floor(msv / 1000));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
  return h ? `${h}:${pad(m)}:${pad(sec)}` : `${m}:${pad(sec)}`;
}
// What a StorageError means to the person holding the phone (§7.2).
const errText = (e) => (e && e.name === "StorageError" ? "Not saved — storage full" : (e && e.message) || String(e));
// Whose change this was, for the "Updated from …" lines.
function whose(rec) {
  if (!rec) return "another device";
  if (rec.device === "pc") return "the PC";
  if (rec.entered_from === "paper") return "the paper sheet";
  return `${rec.edited_by || rec.logged_by || "another"}'s phone`;
}
function notice(kind, ...kids) { return el("div", { class: `notice ${kind}` }, ...kids); }

// The last one-tap diaper survives a reload, so the 2-minute rule does too.
function loadLastDiaper() {
  try { app.lastDiaper = JSON.parse(localStorage.getItem(LAST_DIAPER_KEY)) || null; } catch { app.lastDiaper = null; }
}
function saveLastDiaper(v) {
  app.lastDiaper = v;
  try { localStorage.setItem(LAST_DIAPER_KEY, JSON.stringify(v)); } catch { /* a convenience only */ }
}

// ---------------------------------------------------------------- derived from the journal
// Bottle totals of the last 10 feeds that had any bottle — what every step and chip grows from.
function recentMls(evs = events()) {
  return evs.filter((ev) => ev.type === "feed" && Core.bottleMl(ev) > 0).slice(-10).map(Core.bottleMl);
}
function stepMl() {
  const s = settings().step_ml;
  return s ? Number(s) : Core.stepMl(recentMls(), unit());
}
// The quick-amount chips by quick_mode (§8.1): the range (the default), the recent feeds, or
// the typed list. A range with a bound missing falls back to the recent feeds rather than to
// no chips at all.
function quickAmounts() {
  const s = settings();
  if (s.quick_mode === "range") {
    const r = Core.quickRange(s.quick_from, s.quick_to, s.quick_step);
    if (r.length) return r;
  }
  return Core.quickAmounts(recentMls(), unit(), s.quick_mode === "custom" ? s.quick_custom : null);
}
// Formula names of the most recent portions, newest first — what the formula chips are built
// from (§8.1). Nothing is stored for this, so both phones and the PC agree. Two feeds logged
// in the same minute share a `time` to the second, so ties go to the later write, never to
// the id (which is random in its last four characters).
function recentFormulas(evs = events()) {
  const feeds = evs.filter((ev) => ev.type === "feed").sort((a, b) =>
    (ms(b.time) - ms(a.time)) || (String(b.created_at || "") < String(a.created_at || "") ? -1 : String(b.created_at || "") > String(a.created_at || "") ? 1 : 0));
  const out = [];
  for (const ev of feeds) {
    for (const b of (ev.data && ev.data.bottles) || []) if (b.kind === "formula" && b.formula) out.push(b.formula);
  }
  return out;
}
const formulaChoices = () => Core.formulaChoices(recentFormulas());
const lastFormula = () => formulaChoices()[0];
// A fresh formula portion: the last-used name preselected, so plan A is no taps and plan B one.
const newPortion = (mlv, kind = "formula") => ({ kind, ml: mlv, formula: kind === "formula" ? lastFormula() : null });
// Everyone who has logged or edited anything, plus this phone — the Who chips.
function knownLabels(evs = events()) {
  const seen = new Set();
  if (myLabel()) seen.add(myLabel());
  for (const ev of evs) {
    if (ev.logged_by) seen.add(ev.logged_by);
    if (ev.edited_by) seen.add(ev.edited_by);
  }
  seen.delete("paper");
  return Array.from(seen);
}
function knownMedicines(evs = events()) {
  const seen = new Set(["Vitamin D"]);
  for (const ev of evs) if (ev.type === "health" && ev.data && ev.data.medicine) seen.add(ev.data.medicine);
  return Array.from(seen);
}
const running = (evs, type) => evs.filter((ev) => Core.isRunning(ev) && (!type || ev.type === type));
const targets = () => ((Store.child() || {}).targets) || {};

// ---------------------------------------------------------------- navigation
const currentScreen = () => Object.keys(screens).find((k) => !screens[k].hidden) || "now";

function show(name, { push = false } = {}) {
  if (push) app.stack.push(currentScreen());
  for (const [key, node] of Object.entries(screens)) node.hidden = key !== name;
  document.getElementById("back").hidden = app.stack.length === 0;
  document.getElementById("tabs").hidden = name === "label";
  renderHeader();
  window.scrollTo(0, 0);
}

function back() {
  if (app.editor) { closeEditor(); return; }
  const prev = app.stack.pop();
  if (!prev) return;
  renderScreen(prev);
  show(prev);
}

const markTab = (tab) => document.querySelectorAll(".tab")
  .forEach((b) => b.classList.toggle("active", b.dataset.tab === tab));

function setTab(tab) {
  // A tab tap while the editor is open is a Cancel: the draft goes with it.
  if (app.editor) { stopDraft(); Store.clearDraft(); app.editor = null; }
  app.tab = tab;
  app.stack = [];
  markTab(tab);
  renderScreen(tab);
  show(tab);
}

function renderScreen(name) {
  switch (name) {
    case "now": renderNow(); break;
    case "day": renderDay(); break;
    case "trends": renderTrends(); break;
    case "settings": renderSettings(); break;
    case "editor": renderEditor(); break;
    case "catchup": renderCatchUp(); break;
    default: break;
  }
}
// Whatever tab is underneath, after the journal changed (a write here, or a pull).
function renderTab() {
  if (currentScreen() !== "editor") renderScreen(currentScreen());
  updateBadge();
}

const SCREEN_TITLE = { day: "Day", trends: "Trends", settings: "Settings", catchup: "Catch up" };
function renderHeader() {
  const name = currentScreen();
  const c = Store.child();
  const title = document.getElementById("title"), sub = document.getElementById("subtitle");
  const age = c && c.born ? Core.ageText(c.born, new Date()) : "";
  if (name === "editor" && app.editor) {
    title.textContent = editorTitle();
    sub.textContent = c ? c.name : "";
  } else if (name === "now" || name === "label") {
    title.textContent = c ? c.name : "Baby Log";
    sub.textContent = c ? age : (name === "label" ? "" : "Waiting for the first sync");
  } else {
    title.textContent = SCREEN_TITLE[name] || "Baby Log";
    sub.textContent = c ? `${c.name} · ${age}` : "Waiting for the first sync";
  }
  renderPill();
  updateBadge();
}

// The status pill (§7.3, §7.6): Sync owns the words and the tone.
function renderPill() {
  const pill = document.getElementById("pill");
  const st = Sync.status();
  pill.textContent = st.text;
  pill.className = `pill ${st.tone}`;
}
/** The pill is the sync button (§7.3): signed in, a tap runs a sync at once and the pill
    reads its phases; signed out, it signs in; stuck or failed, it also opens the details. */
async function pillTap() {
  if (!Graph.isSignedIn() && Graph.configured()) {
    // Never a redirect while an editor is open: it would tear the typed entry down (§7.1).
    if (app.editor) { showToast("Finish this entry first — then sign in from Settings"); return; }
    try { await Graph.signIn(); } catch (e) { showToast(errText(e)); }
    return;
  }
  if (app.editor) return;
  if (!Graph.isSignedIn() || Sync.status().tone === "error") setTab("settings");
  if (Graph.isSignedIn()) {
    Sync.run();
    renderPill();
  }
}

function updateBadge() {
  const n = Store.needsCheck().length;
  const badge = document.getElementById("tab-badge");
  badge.textContent = String(n);
  badge.hidden = n === 0;
}

// A 6-second toast with Undo / Edit style actions, above the tab bar (§7.4). One at a time.
let toastTimer = null;
/** Asks the running service worker for its VERSION; null when there is none (http:// dev). */
function swVersion(cb) {
  const c = typeof navigator !== "undefined" && navigator.serviceWorker && navigator.serviceWorker.controller;
  if (!c || typeof MessageChannel === "undefined") { cb(null); return; }
  const ch = new MessageChannel();
  ch.port1.onmessage = (e) => cb(e.data && e.data.version);
  try { c.postMessage("version", [ch.port2]); } catch (_) { cb(null); }
}

function showToast(text, actions = [], msv = 6000) {
  const t = document.getElementById("toast");
  const kids = [el("span", { class: "toast-text" }, text)];
  for (const a of actions) {
    kids.push(el("button", { class: "toast-btn", type: "button", onclick: () => { hideToast(); a.fn(); } }, a.label));
  }
  t.replaceChildren(...kids);
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(hideToast, msv);
}
function hideToast() { document.getElementById("toast").hidden = true; }

// ---------------------------------------------------------------- night mode (§7.4)
/* Scheduled by night_from/night_to; the moon overrides it. The override lives in bl.settings as
   "on" | "off" | null and clears at the next scheduled boundary: "on" (set while the schedule
   says day) is spent once the schedule itself turns on; "off" (set during a scheduled night) is
   spent once the night ends. */
function applyNight() {
  const s = settings();
  const scheduled = Core.isNight(new Date(), s);
  let override = s.night_override || null;
  if ((override === "on" && scheduled) || (override === "off" && !scheduled)) {
    override = null;
    Store.setSettings({ night_override: null });
  }
  const on = override ? override === "on" : scheduled;
  app.night = on;
  document.body.classList.toggle("night", on);
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.setAttribute("content", on ? THEME_NIGHT : THEME_LIGHT);
  const moon = document.getElementById("moon");
  moon.classList.toggle("on", on);
  moon.setAttribute("aria-pressed", String(on));
}
function toggleNight() {
  Store.setSettings({ night_override: app.night ? "off" : "on" });
  applyNight();
}

// ---------------------------------------------------------------- first run (§7.4)
/** "Who is holding this phone?" — resolves once a label is saved. Everything waits on it. */
function askLabel() {
  return new Promise((resolve) => {
    const host = screens.label;
    const choose = (label) => {
      const name = String(label || "").trim();
      if (!name) return;
      if (!Store.setSettings({ label: name })) { fill(host, notice("err", "Could not save the name — storage is blocked on this phone.")); return; }
      resolve(name);
    };
    const other = el("input", { type: "text", placeholder: "Name", autocapitalize: "words", "aria-label": "Name" });
    const otherRow = el("div", { hidden: true },
      other,
      el("div", { class: "actions" }, el("button", { class: "btn primary wide", type: "button", onclick: () => choose(other.value) }, "Continue")));
    fill(host,
      el("div", { class: "card feed" },
        el("div", { class: "h2" }, "Who is holding this phone?"),
        el("p", { class: "muted" }, "It is stamped on every entry logged here as who did it. You can change it in Settings."),
        el("div", { class: "label-choice" },
          el("button", { class: "btn feed tall", type: "button", onclick: () => choose("Dad") }, "Dad"),
          el("button", { class: "btn feed tall", type: "button", onclick: () => choose("Mom") }, "Mom")),
        el("button", { class: "btn ghost wide", type: "button", onclick: () => { otherRow.hidden = false; other.focus(); } }, "Other…"),
        otherRow));
    show("label");
  });
}

// ---------------------------------------------------------------- Now
function renderNow() {
  const host = screens.now;
  const c = Store.child();
  const evs = events();
  const now = Date.now();
  const kids = [];

  if (!app.storage) kids.push(notice("err", "Storage is unavailable on this phone — nothing can be saved. Reopen the app; if it persists, free some space."));
  if (!c) {
    kids.push(el("div", { class: "card feed" },
      el("div", { class: "h2" }, "Waiting for the first sync"),
      el("p", { class: "muted" }, "The child is created on the PC and arrives with the first pull. "
        + (Graph.isSignedIn() ? "Syncing whenever this screen is open." : "Sign in from Settings or the pill above."))));
  } else {
    kids.push(nowPanel(evs, now));
  }
  kids.push(logBar(evs, !!c));

  const recent = evs.slice(-10).reverse();
  kids.push(el("div", { class: "card" },
    el("div", { class: "h2" }, "Recent", el("span", { class: "sub" }, "tap an entry to change it")),
    recent.length ? el("div", { class: "rows" }, ...recent.map(swipeRow)) : el("div", { class: "empty" }, "Nothing logged yet.")));
  fill(host, ...kids);
}

function nowPanel(evs, now) {
  const kids = [];
  const lf = Core.lastOf(evs, "feed"), ld = Core.lastOf(evs, "diaper");
  const feedRunning = lf && Core.isRunning(lf);
  const tile = (cls, label, ev, big, sinceAttr, emptyText) => el("button", {
    class: `tile ${cls}`, type: "button", disabled: !ev, "data-event-id": ev ? ev.event_id : null,
    onclick: () => ev && openEditor({ event: ev }) },
    el("span", { class: "tile-label" }, label),
    el("span", sinceAttr ? { class: "tile-big", "data-since": sinceAttr } : { class: "tile-big" }, big),
    el("span", { class: "tile-sub" }, ev ? `${Core.fmtTime(ev.time)} · ${Core.describe(ev, unit())}${ev.logged_by ? ` · ${ev.logged_by}` : ""}` : emptyText));
  kids.push(el("div", { class: "tiles" },
    tile("tile-feed", "Last feed", lf, lf ? (feedRunning ? "Feeding now" : `${Core.sinceText(now - ms(lf.time))} ago`) : "—",
      lf && !feedRunning ? lf.time : null, "No feed yet"),
    tile("tile-diaper", "Last diaper", ld, ld ? `${Core.sinceText(now - ms(ld.time))} ago` : "—", ld ? ld.time : null, "No diaper yet")));

  // Every running feed or sleep, whichever device started it.
  const runs = running(evs);
  for (const ev of runs) kids.push(runningCard(ev, now));
  const feeds = runs.filter((ev) => ev.type === "feed");
  if (feeds.length >= 2) {
    kids.push(el("div", { class: "actions" },
      el("button", { class: "btn ghost", type: "button", onclick: () => mergeFeeds(feeds) }, "Merge into one"),
      el("span", { class: "muted small" }, "Two feeds are running — keep the earlier start, add the sides together.")));
  }

  // Hints, never alarms (§8.2).
  const gap = Core.usualGapMs(evs, "feed");
  if (gap) {
    let text = `Usually every ${Core.sinceText(gap)}`;
    const next = Core.nextFeedAt(evs);
    if (next) text += ` · next around ${Core.fmtTime(next)}${ms(next) < now ? " (past)" : ""}`;
    kids.push(el("div", { class: "gapline" }, text));
  } else {
    kids.push(el("div", { class: "gapline" }, "Usual gap shows after three feeds."));
  }

  // Today's totals against the pediatrician's targets, when set.
  const t = Core.totals(evs, todayStr(), new Date());
  const tg = targets();
  const total = (count, word, target) => el("span", { class: `total${target && count >= target ? " met" : ""}` },
    el("b", {}, String(count)), ` ${word}`, target ? el("span", { class: "of" }, ` / ${target}`) : null);
  kids.push(el("div", { class: "totals" },
    total(t.feeds, t.feeds === 1 ? "feed" : "feeds", tg.feeds_per_day),
    t.bottle_ml ? el("span", { class: "total" }, el("b", {}, amount(t.bottle_ml)), " bottle") : null,
    t.breast_s ? el("span", { class: "total" }, el("b", {}, String(Math.round(t.breast_s / 60))), " min breast") : null,
    total(t.wet, "wet", tg.wet_per_day),
    total(t.dirty, "dirty", tg.dirty_per_day),
    t.sleeps ? el("span", { class: "total" }, el("b", {}, String(t.sleeps)), ` ${t.sleeps === 1 ? "sleep" : "sleeps"} · `, Core.sinceText(t.sleep_s * 1000)) : null,
    t.pumps ? el("span", { class: "total" }, el("b", {}, String(t.pumps)), ` pumped · ${amount(t.pump_ml)}`) : null));
  return el("div", { class: "card feed" }, ...kids);
}

function runningCard(ev, now) {
  const stale = Core.staleTimer(ev, now);
  const isFeed = ev.type === "feed";
  const timer = ev.data && ev.data.timer;
  const br = (ev.data && ev.data.breast) || {};
  const sub = [];
  if (isFeed) {
    const side = timer && timer.side;
    if (side) sub.push(`on the ${side} since ${Core.fmtTime(timer.side_started)}`);
    else if (br.last_side) sub.push(`last side ${br.last_side}`);
    const l = Math.round((br.left_s || 0) / 60), r = Math.round((br.right_s || 0) / 60);
    if (l || r) sub.push(`L ${l} min · R ${r} min`);
    if (Core.bottleMl(ev)) sub.push(amount(Core.bottleMl(ev)));
  } else if (ev.data && ev.data.where) {
    sub.push(ev.data.where);
  }
  if (ev.logged_by) sub.push(ev.logged_by);
  const open = () => openEditor({ event: ev });
  return el("div", { class: `running running-${ev.type}`, "data-event-id": ev.event_id },
    el("span", { class: "timer", "data-elapsed": ev.time, "data-style": isFeed ? "clock" : "", onclick: open },
      isFeed ? elapsedText(now - ms(ev.time)) : Core.sinceText(now - ms(ev.time))),
    el("div", { class: "running-text", onclick: open },
      el("div", { class: "running-title" }, isFeed ? `Feeding since ${Core.fmtTime(ev.time)}` : `Sleeping since ${Core.fmtTime(ev.time)}`),
      el("div", { class: "running-sub" }, sub.join(" · "))),
    el("div", { class: "running-actions" },
      isFeed ? el("button", { class: "btn ghost", type: "button", onclick: () => switchSide(ev) },
        `Switch to ${timer && timer.side === "left" ? "right" : "left"}`) : null,
      el("button", { class: "btn feed", type: "button", onclick: () => stopNowFor(ev) }, "Stop"),
      el("button", { class: "btn ghost", type: "button", onclick: open }, "Edit")),
    stale ? el("div", { class: "stale" },
      isFeed ? "Running for over an hour — forgot to stop it?" : "Running for over six hours — forgot to stop it?",
      el("button", { class: "btn ghost", type: "button", onclick: () => openEditor({ event: ev, focusEnd: true }) }, "Set end time")) : null);
}

// The log buttons: disabled until a child exists (§3.3). Feed is the big one, and always a new
// bottle feed (§6.2) — a legacy running feed keeps its card above.
function logBar(evs, enabled) {
  const off = !enabled;
  return el("div", { class: "logbar" },
    el("button", { class: "btn feed big wide", type: "button", disabled: off, onclick: feedButton }, "Feed"),
    el("div", { class: "log-row" },
      el("button", { class: "btn wet", type: "button", disabled: off, onclick: () => quickDiaper(true, false) }, "Wet"),
      el("button", { class: "btn dirty", type: "button", disabled: off, onclick: () => quickDiaper(false, true) }, "Dirty"),
      el("button", { class: "btn diaper", type: "button", disabled: off, onclick: () => quickDiaper(true, true) }, "Both")),
    el("div", { class: "log-row" },
      el("button", { class: "btn", type: "button", disabled: off, onclick: sleepButton }, running(evs, "sleep").length ? "Sleeping…" : "Sleep"),
      el("button", { class: "btn", type: "button", disabled: off, onclick: () => openEditor({ type: "pump" }) }, "Pump"),
      el("button", { class: "btn", type: "button", disabled: off, onclick: () => openEditor({ type: "growth" }) }, "Weight"),
      el("button", { class: `btn${app.more ? " ghost" : ""}`, type: "button", disabled: off, onclick: () => { app.more = !app.more; renderNow(); } }, app.more ? "Less" : "More")),
    app.more ? el("div", { class: "log-row" },
      el("button", { class: "btn", type: "button", disabled: off, onclick: () => { app.more = false; openEditor({ type: "health" }); } }, "Health"),
      el("button", { class: "btn", type: "button", disabled: off, onclick: () => { app.more = false; openEditor({ type: "note" }); } }, "Note"),
      el("button", { class: "btn", type: "button", disabled: off, onclick: () => { app.more = false; openCatchUp(); } }, "Catch up")) : null);
}

// One row renderer per §3.2 type: what the second line says. Every row carries data-event-id
// and opens the editor (§8.3).
const ROW_SUB = {
  feed: (ev) => Core.describe(ev, unit()),
  diaper: (ev) => Core.describe(ev, unit()),
  sleep: (ev) => (ev.data.where ? `${Core.describe(ev, unit())} · ${ev.data.where}` : Core.describe(ev, unit())),
  pump: (ev) => (ev.data.minutes != null ? `${Core.describe(ev, unit())} · ${ev.data.minutes} min` : Core.describe(ev, unit())),
  growth: (ev) => Core.describe(ev, unit()),
  health: (ev) => Core.describe(ev, unit()),
  note: (ev) => Core.describe(ev, unit()),
};
function eventRow(ev) {
  const describe = ROW_SUB[ev.type] || ((x) => Core.describe(x, unit()));
  return el("button", { class: `row row-${ev.type}`, type: "button", "data-event-id": ev.event_id,
    onclick: () => openEditor({ event: ev }) },
    el("span", { class: "row-time" }, Core.fmtTime(ev.time), ev.end ? el("small", { class: "muted" }, `–${Core.fmtTime(ev.end)}`) : null),
    el("span", { class: "row-main" },
      el("span", { class: "row-name" }, el("span", { class: "row-type" }, TYPE_LABEL[ev.type] || ev.type), describe(ev)),
      ev.note ? el("span", { class: `row-sub${isCheck(ev) ? " check" : ""}` }, ev.note) : null),
    el("span", { class: "row-by" }, ev.logged_by || ""),
    el("span", { class: "chev" }, "›"));
}

// ---------------------------------------------------------------- swipe actions on a row
/** eventRow wrapped so a sideways drag does what a parent does most at 3 a.m. without opening
    anything: drag left → Delete (the Undo in the toast stands in for a confirm sheet — the swipe
    is the deliberate part); on a paper row that still carries a `Check:` question, drag right →
    Looks right, which drops the question from the note. Pointer events cover a finger and a
    mouse alike; `touch-action: pan-y` on the wrapper leaves vertical scrolling to the browser, so
    only a sideways drag reaches this code. One row is open at a time; a tap anywhere else closes
    it, and the tap that ends a drag never opens the editor underneath. */
const SWIPE_OPEN = 96;                 // the width of one action button, in px
let openSwipe = null;
function swipeRow(ev) {
  const row = eventRow(ev);
  const check = isCheck(ev);
  const wrap = el("div", { class: `swipe${check ? " swipe-check" : ""}`, "data-event-id": ev.event_id },
    check ? el("button", { class: "swipe-act keep", type: "button", onclick: () => markChecked(ev) }, "Looks right") : null,
    el("button", { class: "swipe-act del", type: "button", onclick: () => quickDelete(ev) }, "Delete"),
    row);
  let x0 = 0, y0 = 0, x = 0, mode = null, dragged = false;   // mode: null (undecided) | "h" | "v"
  const setX = (v) => { x = v; if (row.style) row.style.transform = v ? `translateX(${v}px)` : ""; };
  const close = () => { setX(0); wrap.classList.remove("open-left", "open-right"); if (openSwipe === wrap) openSwipe = null; };
  const open = (side) => {
    if (openSwipe && openSwipe !== wrap) openSwipe._close();
    setX(side === "left" ? -SWIPE_OPEN : SWIPE_OPEN);
    wrap.classList.add(side === "left" ? "open-left" : "open-right");
    openSwipe = wrap;
  };
  wrap._close = close;
  row.addEventListener("pointerdown", (p) => {
    if (p.pointerType === "mouse" && p.button !== 0) return;
    x0 = p.clientX; y0 = p.clientY; mode = null; dragged = false;
  });
  row.addEventListener("pointermove", (p) => {
    if (mode === "v" || (!x0 && !y0)) return;
    const mx = p.clientX - x0, my = p.clientY - y0;
    if (mode === null) {
      if (Math.abs(my) > 8 && Math.abs(my) > Math.abs(mx)) { mode = "v"; return; }   // a scroll, not a swipe
      if (Math.abs(mx) <= 8) return;
      mode = "h"; dragged = true;
      wrap.classList.add("dragging");
      if (row.setPointerCapture) try { row.setPointerCapture(p.pointerId); } catch (_) { /* a synthetic pointer */ }
    }
    const base = wrap.classList.contains("open-left") ? -SWIPE_OPEN : wrap.classList.contains("open-right") ? SWIPE_OPEN : 0;
    setX(Math.max(-SWIPE_OPEN, Math.min(check ? SWIPE_OPEN : 0, base + mx)));
  });
  const settle = () => {
    if (mode !== "h") { x0 = y0 = 0; mode = null; return; }
    wrap.classList.remove("dragging");
    if (x <= -SWIPE_OPEN / 2) open("left");
    else if (x >= SWIPE_OPEN / 2 && check) open("right");
    else close();
    x0 = y0 = 0; mode = null;
  };
  row.addEventListener("pointerup", settle);
  row.addEventListener("pointercancel", settle);
  // The click that ends a drag, or a tap on an open row, must not open the editor underneath.
  wrap.addEventListener("click", (c) => {
    const onAction = c.target && c.target.closest && c.target.closest(".swipe-act");
    if (onAction) { close(); return; }
    if (dragged || openSwipe === wrap) {
      if (c.stopPropagation) c.stopPropagation();
      if (c.preventDefault) c.preventDefault();
      dragged = false;
      close();
    }
  }, true);
  return wrap;
}
document.addEventListener("pointerdown", (p) => {
  if (openSwipe && !(openSwipe.contains && openSwipe.contains(p.target))) openSwipe._close();
});

/** Delete from a swipe: no confirm sheet (the swipe was the decision), Undo in the toast instead,
    and the same stale-pull guard as the editor's Delete so a paper row is not tombstoned on top of
    a change from the PC. */
async function quickDelete(ev) {
  if (busy.has(ev.event_id)) return;
  busy.add(ev.event_id);
  try {
    await pullIfStale(null);
    const held = Store.event(ev.event_id) || ev;
    if (held.deleted) return;
    await Store.tombstone(held, "swipe");
    Sync.afterWrite();
    if (app.lastDiaper && app.lastDiaper.event_id === ev.event_id) saveLastDiaper(null);
    renderTab();
    showToast(`Deleted ${(TYPE_LABEL[ev.type] || ev.type).toLowerCase()} ${Core.fmtTime(ev.time)}`,
      [{ label: "Undo", fn: () => restoreEntry(ev.event_id) }]);
  } catch (x) { showToast(errText(x)); } finally { busy.delete(ev.event_id); }
}

/** "Looks right": the paper reading stands, so the question goes and the row leaves Needs check.
    Only the `Check:` part is dropped; a note of the parent's own before it stays. */
const CHECK_TAIL_RE = /(^|\s—\s)Check: [\s\S]*$/;
function withoutCheck(note) { return String(note || "").replace(CHECK_TAIL_RE, "").trim(); }
async function markChecked(ev) {
  if (busy.has(ev.event_id)) return;
  busy.add(ev.event_id);
  try {
    await pullIfStale(null);
    const held = Store.event(ev.event_id) || ev;
    if (held.deleted || !isCheck(held)) return;
    const before = held.note || "";
    await Store.revise(held, { note: withoutCheck(before) });
    Sync.afterWrite();
    renderTab();
    showToast(`Checked · ${Core.fmtTime(ev.time)} stands as read`, [{ label: "Undo", fn: async () => {
      try {
        await Store.revise(Store.event(ev.event_id) || held, { note: before });
        Sync.afterWrite();
        renderTab();
      } catch (x) { showToast(errText(x)); }
    } }]);
  } catch (x) { showToast(errText(x)); } finally { busy.delete(ev.event_id); }
}

// ---------------------------------------------------------------- quick actions
// Always a new bottle feed (§6.2): a bottle has no timer, so there is nothing to resume.
function feedButton() {
  openEditor({ type: "feed" });
}

async function sleepButton() {
  const run = running(events(), "sleep");
  if (run.length) { openEditor({ event: run[0] }); return; }
  const time = nowIso();
  try {
    const rec = await Store.newEvent({ type: "sleep", time, end: null, data: { timer: { running: true } }, note: "" });
    Sync.afterWrite();
    showToast(`Sleeping since ${Core.fmtTime(time)}`, [
      { label: "Undo", fn: () => undoNew(rec) },
      { label: "Edit", fn: () => openEditor({ event: Store.event(rec.event_id) || rec }) }]);
    renderTab();
  } catch (e) { showToast(errText(e)); }
}

// One tap, one diaper — unless the last one from this phone was under two minutes ago, in which
// case it is probably the same diaper and the editor of that one opens instead (§6.2, §7.4).
async function quickDiaper(wet, dirty) {
  const last = app.lastDiaper;
  if (last && Date.now() - last.ms < 2 * MIN) {
    const ev = Store.event(last.event_id);
    if (ev && ev.type === "diaper" && !ev.deleted) { openEditor({ event: ev, sameAs: { wet, dirty } }); return; }
  }
  await writeDiaper(wet, dirty);
}
// A one-tap diaper in flight. The 2-minute rule cannot catch a double tap on the 60 px button:
// app.lastDiaper is only set once the first write has landed, so the second tap would write a
// twin. This flag is what catches it.
let writing = false;
async function writeDiaper(wet, dirty) {
  if (writing) return;
  writing = true;
  const time = nowIso();
  try {
    const rec = await Store.newEvent({ type: "diaper", time, end: null, data: { wet, dirty }, note: "" });
    Sync.afterWrite();
    saveLastDiaper({ event_id: rec.event_id, ms: Date.now() });
    showToast(`${Core.describe(rec, unit())} · ${Core.fmtTime(time)}`, [
      { label: "Undo", fn: () => undoNew(rec) },
      { label: "Edit", fn: () => openEditor({ event: Store.event(rec.event_id) || rec }) }]);
    renderTab();
  } catch (e) { showToast(errText(e)); }
  finally { writing = false; }
}
async function undoNew(rec) {
  try {
    await Store.tombstone(Store.event(rec.event_id) || rec, "undo");
    Sync.afterWrite();
    if (app.lastDiaper && app.lastDiaper.event_id === rec.event_id) saveLastDiaper(null);
    renderTab();
  } catch (e) { showToast(errText(e)); }
}

// The running side's seconds go into its side; total and last side follow; the timer clears.
function foldTimer(data, endMs) {
  const t = data.timer;
  if (t && t.side_started) {
    const br = data.breast;
    const k = t.side === "left" ? "left_s" : "right_s";
    br[k] = (br[k] || 0) + Math.max(0, Math.floor((endMs - ms(t.side_started)) / 1000));
    br.last_side = t.side;
    br.total_s = (br.left_s || 0) + (br.right_s || 0);
    br.approx = false;
  }
  data.timer = null;
  return data;
}

/** Before a Switch/Stop on a feed another device last wrote: flush, pull, and refuse if the pull
    changed it — the other phone may have stopped it already (§7.3). Returns the record to act on. */
async function guardOther(ev) {
  const cur0 = Store.event(ev.event_id) || ev;
  if (cur0.device === settings().device) return cur0;
  const before = `${cur0.revision}/${cur0.created_at}`;
  try { await Sync.run(); } catch { /* the run reports its own failure */ }
  const cur = Store.event(ev.event_id) || cur0;
  if (`${cur.revision}/${cur.created_at}` !== before) {
    throw new Error(`Updated on ${whose(cur)} — look again`);
  }
  return cur;
}

// One write per running card at a time: while the guard's flush-then-pull is on the network a
// second tap on Switch would switch straight back, and one on Stop would write a redundant
// revision. Keyed by entry so a Wet tap meanwhile still goes through.
const busy = new Set();

async function switchSide(ev) {
  if (busy.has(ev.event_id)) return;
  busy.add(ev.event_id);
  try {
    const held = await guardOther(ev);
    const data = foldTimer(clone(held.data), Date.now());
    const was = (held.data.timer && held.data.timer.side) || data.breast.last_side;
    data.timer = { side: was === "left" ? "right" : "left", side_started: nowIso() };
    await Store.revise(held, { data, end: null });
    Sync.afterWrite();
    renderTab();
  } catch (e) { showToast(errText(e)); renderTab(); }
  finally { busy.delete(ev.event_id); }
}

async function stopNowFor(ev) {
  if (busy.has(ev.event_id)) return;
  busy.add(ev.event_id);
  const end = nowIso();
  try {
    const held = await guardOther(ev);
    const data = held.type === "feed" ? foldTimer(clone(held.data), ms(end)) : Object.assign(clone(held.data), { timer: null });
    const rec = await Store.revise(held, { data, end });
    Sync.afterWrite();
    showToast(`${TYPE_LABEL[held.type]} stopped · ${Core.fmtTime(end)}`, [{ label: "Edit", fn: () => openEditor({ event: Store.event(rec.event_id) || rec }) }]);
    renderTab();
  } catch (e) { showToast(errText(e)); renderTab(); }
  finally { busy.delete(ev.event_id); }
}

// Two running feeds become one: the earlier start, the sides added, the later one tombstoned.
async function mergeFeeds(feeds) {
  const sorted = feeds.slice().sort((a, b) => ms(a.time) - ms(b.time));
  const keep = sorted[0], drop = sorted[1];
  const a = clone(keep.data), b = foldTimer(clone(drop.data), Date.now());
  const add = (x, y) => (x == null && y == null ? null : (x || 0) + (y || 0));
  a.breast.left_s = add(a.breast.left_s, b.breast.left_s);
  a.breast.right_s = add(a.breast.right_s, b.breast.right_s);
  if (a.breast.left_s != null || a.breast.right_s != null) {
    a.breast.total_s = (a.breast.left_s || 0) + (a.breast.right_s || 0);
    a.breast.approx = false;
  } else if (b.breast.total_s != null) {
    a.breast.total_s = add(a.breast.total_s, b.breast.total_s);
  }
  a.breast.last_side = b.breast.last_side || a.breast.last_side;
  a.bottles = (a.bottles || []).concat(b.bottles || []);
  if (a.made_ml == null) a.made_ml = b.made_ml;
  if (a.leftover_ml == null) a.leftover_ml = b.leftover_ml;
  const note = [keep.note, drop.note].filter(Boolean).join(" — ");
  try {
    await Store.revise(keep, { data: a, end: null, note });
    await Store.tombstone(drop, `merged into ${keep.event_id}`);
    Sync.afterWrite();
    showToast(`Merged into the ${Core.fmtTime(keep.time)} feed`);
    renderTab();
  } catch (e) { showToast(errText(e)); }
}

async function restoreEntry(id) {
  const rec = Store.event(id);
  if (!rec || !rec.deleted) return;
  try {
    await Store.restore(rec);
    Sync.afterWrite();
    renderTab();
  } catch (e) { showToast(errText(e)); }
}

// ---------------------------------------------------------------- Catch up (§6.2, §7.4)
/* For the paper slips written when no phone was to hand. One screen: a date (default today),
   then a strip that logs one entry per tap and stays put for the next — a time, Feed with the
   quick-amount chips (formula = the last used) or Wet · Dirty · Both. Every tap is already a
   journal file; nothing waits for a "save all". Only the time clears; the date stays. */
function openCatchUp() {
  if (!app.catchup) app.catchup = { date: todayStr(), time: "", rows: [], msg: null, added: null, writing: false };
  app.catchup.msg = null;
  renderCatchUp();
  show("catchup", { push: true });
  focusCatchUpTime();
}
function focusCatchUpTime() {
  const t = document.getElementById("cu-time");
  if (t) t.focus();
}
function renderCatchUp() {
  const host = screens.catchup;
  const cu = app.catchup;
  if (!cu) return;
  const c = Store.child();
  const evs = events();
  const onDay = Core.onDay(evs, cu.date);
  const already = { feed: onDay.filter((ev) => ev.type === "feed").length, diaper: onDay.filter((ev) => ev.type === "diaper").length };
  const rows = cu.rows.map((id) => Store.event(id)).filter((ev) => ev && !ev.deleted);
  const off = !c;
  fill(host,
    el("div", { class: "card feed cu-strip" },
      el("div", { class: "h2" }, "Catch up", el("span", { class: "sub" }, "one tap per paper entry")),
      el("div", { class: "cu-when" },
        el("label", { class: "field" }, el("span", {}, "Date"),
          el("input", { type: "date", id: "cu-date", value: cu.date, "aria-label": "Date",
            onchange: (x) => { if (/^\d{4}-\d{2}-\d{2}$/.test(x.target.value)) { cu.date = x.target.value; cu.msg = null; renderCatchUp(); } } })),
        el("label", { class: "field" }, el("span", {}, "Time"),
          el("input", { type: "time", id: "cu-time", value: cu.time, "aria-label": "Time",
            oninput: (x) => { cu.time = x.target.value; } }))),
      el("div", { class: "muted small" }, `${Core.fmtDay(cu.date)} already has ${already.feed} ${already.feed === 1 ? "feed" : "feeds"} and ${already.diaper} ${already.diaper === 1 ? "diaper" : "diapers"}`),
      el("div", { class: "h3" }, `Feed · ${lastFormula()}`),
      el("div", { class: "chips scroll" },
        ...quickAmounts().map((mlv) => el("button", { class: "chip feed", type: "button", disabled: off, onclick: () => catchUpFeed(mlv) }, amount(mlv)))),
      el("div", { class: "h3" }, "Diaper"),
      el("div", { class: "log-row" },
        el("button", { class: "btn wet", type: "button", disabled: off, onclick: () => catchUpDiaper(true, false) }, "Wet"),
        el("button", { class: "btn dirty", type: "button", disabled: off, onclick: () => catchUpDiaper(false, true) }, "Dirty"),
        el("button", { class: "btn diaper", type: "button", disabled: off, onclick: () => catchUpDiaper(true, true) }, "Both")),
      cu.msg ? el("div", { class: "ed-msg err", id: "cu-msg" }, cu.msg) : null,
      el("div", { class: "cu-added", id: "cu-added" }, cu.added || "")),
    el("div", { class: "card" },
      el("div", { class: "h2" }, "Added", el("span", { class: "sub" }, "tap a row to change it")),
      rows.length ? el("div", { class: "rows" }, ...rows.map(swipeRow)) : el("div", { class: "empty" }, "Nothing added yet.")),
    el("div", { class: "actions" }, el("button", { class: "btn primary wide", type: "button", onclick: back }, "Done")));
}
/** One entry at the strip's date and time. A missing time is refused in page; the same
    born..now+10 min rule as the editor. Returns the record, or null when nothing was written. */
async function catchUpWrite(type, data) {
  const cu = app.catchup;
  if (!cu || cu.writing) return null;
  const m = /^(\d{2}):(\d{2})/.exec(cu.time || "");
  const say = (text) => { cu.msg = text; renderCatchUp(); focusCatchUpTime(); };
  if (!m) { say("Type the time first — the date stays, only the time clears"); return null; }
  const [y, mo, dd] = cu.date.split("-").map(Number);
  const time = Core.isoLocal(new Date(y, mo - 1, dd, Number(m[1]), Number(m[2]), 0));
  const end = type === "feed" ? time : null;      // a bottle typed in after the fact is over (§3.2)
  const err = validateDraft({ type, time, end, data });
  if (err) { say(err); return null; }
  cu.writing = true;
  try {
    const rec = await Store.newEvent({ type, time, end, data, note: "" });
    Sync.afterWrite();
    cu.rows.unshift(rec.event_id);
    cu.time = "";
    cu.msg = null;
    cu.added = `Added ${Core.describe(rec, unit())} · ${Core.fmtTime(time)}`;
    renderCatchUp();
    focusCatchUpTime();
    const mine = cu.added;
    setTimeout(() => { if (app.catchup && app.catchup.added === mine) { app.catchup.added = null; const n = document.getElementById("cu-added"); if (n) n.textContent = ""; } }, 4000);
    return rec;
  } catch (e) { say(errText(e)); return null; }
  finally { cu.writing = false; }
}
const catchUpFeed = (mlv) => catchUpWrite("feed", { bottles: [newPortion(mlv)] });
const catchUpDiaper = (wet, dirty) => catchUpWrite("diaper", { wet, dirty });

// ---------------------------------------------------------------- Day
function renderDay() {
  const host = screens.day;
  const date = app.date || todayStr();
  app.date = date;
  const evs = events();
  const dayEvs = Core.onDay(evs, date);
  const c = Store.child();
  const born = c && c.born;
  const hasPrev = evs.some((ev) => Core.localDate(ev.time) < date);
  const hasNext = evs.some((ev) => Core.localDate(ev.time) > date);
  const go = (n) => { app.date = shiftDay(date, n); renderDay(); };

  const feeds = dayEvs.filter((ev) => ev.type === "feed");
  const diapers = dayEvs.filter((ev) => ev.type === "diaper");
  const others = dayEvs.filter((ev) => ev.type !== "feed" && ev.type !== "diaper");
  const noteLine = (ev) => (ev.note ? el("span", { class: `c-note${isCheck(ev) ? " check" : ""}` }, ev.note) : null);
  const by = (ev) => (ev.logged_by ? el("span", { class: "c-by" }, ev.logged_by) : null);

  const feedCell = (ev) => {
    const br = ev.data.breast || {};
    const run = Core.isRunning(ev);
    const parts = [];
    const s = Core.breastSeconds(ev, new Date());
    if (s || br.left_s != null || br.right_s != null) {
      let breast = `${br.approx ? "~" : ""}${Math.round(s / 60)} min`;
      if (br.left_s != null || br.right_s != null) breast += ` (L ${Math.round((br.left_s || 0) / 60)} / R ${Math.round((br.right_s || 0) / 60)})`;
      parts.push(breast);
    }
    for (const b of ev.data.bottles || []) parts.push(`${amount(b.ml)} ${b.kind === "formula" ? (b.formula || "formula") : "breast milk"}`);
    if (ev.data.made_ml != null || ev.data.leftover_ml != null) {
      parts.push(`made ${ev.data.made_ml != null ? amount(ev.data.made_ml) : "—"} / left ${ev.data.leftover_ml != null ? amount(ev.data.leftover_ml) : "—"}`);
    }
    return el("button", { class: `cell${run ? " running-cell" : ""}`, type: "button", "data-event-id": ev.event_id, onclick: () => openEditor({ event: ev }) },
      el("span", { class: "c-time" }, Core.fmtTime(ev.time), run ? " ▸" : (ev.end ? `–${Core.fmtTime(ev.end)}` : "")),
      parts.join(" · ") || (run ? "feeding" : "feed"), by(ev), noteLine(ev));
  };
  // Read-only glyphs; the dirty one is tinted by stool colour. Toggling happens in the editor.
  const glyph = (on, cls, color) => el("span", { class: `glyph-box ${on ? cls : "off"}`, style: on && color ? `color:${color}` : null }, on ? "☑" : "☐");
  const diaperCell = (ev) => {
    const dd = ev.data;
    const extra = [dd.color, dd.texture, dd.size].filter(Boolean).map((x) => x.replace(/_/g, " "));
    if (dd.rash) extra.push("rash");
    if (dd.blowout) extra.push("blowout");
    return el("button", { class: "cell", type: "button", "data-event-id": ev.event_id, onclick: () => openEditor({ event: ev }) },
      el("span", { class: "c-time" }, Core.fmtTime(ev.time)),
      glyph(dd.wet, "wet"), glyph(dd.dirty, "dirty", STOOL[dd.color] || "var(--dirty)"),
      extra.join(", "), by(ev), noteLine(ev));
  };
  const t = Core.totals(evs, date, new Date());
  const tg = targets();
  const tot = (n, word, target) => el("span", {}, el("b", {}, String(n)), ` ${word}`, target ? ` / ${target}` : "");

  fill(host,
    el("div", { class: "daynav" },
      el("button", { class: "btn ghost", type: "button", disabled: !hasPrev, "aria-label": "Previous day", onclick: () => go(-1) }, "‹"),
      el("div", { class: "when" }, Core.fmtDay(date), el("small", {},
        `${born ? `day ${Core.dayNumber(born, date)}` : ""}${date === todayStr() ? " · today" : ""}`)),
      date !== todayStr() ? el("button", { class: "btn ghost", type: "button", onclick: () => { app.date = todayStr(); renderDay(); } }, "Today") : null,
      el("button", { class: "btn ghost", type: "button", disabled: !hasNext && date >= todayStr(), "aria-label": "Next day", onclick: () => go(1) }, "›")),
    el("div", { class: "strip" },
      tot(t.feeds, t.feeds === 1 ? "feed" : "feeds", tg.feeds_per_day),
      t.bottle_ml ? el("span", {}, el("b", {}, amount(t.bottle_ml)), " bottle") : null,
      t.breast_s ? el("span", {}, el("b", {}, String(Math.round(t.breast_s / 60))), " min breast") : null,
      tot(t.wet, "wet", tg.wet_per_day), tot(t.dirty, "dirty", tg.dirty_per_day),
      t.sleeps ? el("span", {}, el("b", {}, Core.sinceText(t.sleep_s * 1000)), " asleep") : null,
      t.pumps ? el("span", {}, el("b", {}, amount(t.pump_ml)), " pumped") : null),
    el("div", { class: "sheet" },
      el("div", { class: "col-feed" }, el("div", { class: "sheet-col-h" }, "Feeding"),
        feeds.length ? feeds.map(feedCell) : el("div", { class: "empty" }, "No feeds")),
      el("div", { class: "col-diaper" }, el("div", { class: "sheet-col-h" }, "Diapers"),
        diapers.length ? diapers.map(diaperCell) : el("div", { class: "empty" }, "No diapers"))),
    others.length ? el("div", { class: "other-h" },
      el("div", { class: "h3" }, "Other"),
      el("div", { class: "rows" }, ...others.map(swipeRow))) : null);
}

// ---------------------------------------------------------------- Trends (7-day totals, §7.4)
function renderTrends() {
  const host = screens.trends;
  const evs = events();
  const today = todayStr();
  const now = new Date();
  const tg = targets();
  const days = [];
  for (let i = 6; i >= 0; i--) days.push(shiftDay(today, -i));
  const num = (v, target) => el("td", { class: `t-num${target && v < target ? " under" : ""}` }, String(v));
  const rows = days.map((day) => {
    const t = Core.totals(evs, day, now);
    return el("tr", { class: day === today ? "today openable" : "openable",
      onclick: () => { app.date = day; setTab("day"); } },
      el("td", {}, Core.fmtDay(day)),
      num(t.feeds, tg.feeds_per_day),
      el("td", { class: "t-num" }, t.bottle_ml ? amount(t.bottle_ml) : "—"),
      el("td", { class: "t-num" }, t.breast_s ? String(Math.round(t.breast_s / 60)) : "—"),
      num(t.wet, tg.wet_per_day), num(t.dirty, tg.dirty_per_day),
      el("td", { class: "t-num" }, t.sleep_s ? Core.sinceText(t.sleep_s * 1000) : "—"),
      el("td", { class: "t-num" }, t.pump_ml ? amount(t.pump_ml) : "—"));
  });
  const target = (v) => el("td", { class: "t-num" }, v ? `${v}` : "");
  fill(host,
    el("div", { class: "card" },
      el("div", { class: "h2" }, "Last 7 days", el("span", { class: "sub" }, "a row opens that day")),
      el("div", { class: "t-wrap" }, el("table", { class: "t-table" },
        el("thead", {},
          el("tr", {}, ...["Day", "Feeds", "Bottle", "Breast min", "Wet", "Dirty", "Sleep", "Pumped"].map((h) => el("th", {}, h))),
          (tg.feeds_per_day || tg.wet_per_day || tg.dirty_per_day) ? el("tr", { class: "target-row" },
            el("td", {}, "target"), target(tg.feeds_per_day), el("td"), el("td"), target(tg.wet_per_day), target(tg.dirty_per_day), el("td"), el("td")) : null),
        el("tbody", {}, ...rows)))),
    (tg.feeds_per_day || tg.wet_per_day || tg.dirty_per_day) ? null
      : el("div", { class: "muted small" }, "Targets from the pediatrician go under Settings → Child."));
}

// ---------------------------------------------------------------- Settings
function renderSettings({ listsOnly = false } = {}) {
  const host = screens.settings;
  if (!listsOnly || !document.getElementById("settings-form")) {
    fill(host,
      settingsForm(),
      el("div", { class: "card", id: "settings-child" }),
      el("div", { class: "card", id: "settings-sync" }),
      el("div", { class: "card", id: "settings-needs" }),
      el("div", { class: "card", id: "settings-deleted" }));
  }
  renderChildCard();
  renderSyncCard();
  renderNeedsCard();
  renderDeletedCard();
}

// Built once per visit and kept, so a pull never wipes a half-typed field.
function settingsForm() {
  const s = settings();
  const f = {};
  const field = (key, label, input) => { f[key] = input; return el("label", { class: "field" }, el("span", {}, label), input); };
  const mlOrNull = (inp) => (inp.value === "" || !Number.isFinite(Number(inp.value)) ? null : Math.max(0, Math.round(Number(inp.value))));
  const save = () => {
    const custom = f.quick_custom.value.split(/[,\s]+/).filter(Boolean).map(Number).filter((n) => Number.isFinite(n) && n > 0);
    const patch = {
      label: f.label.value.trim() || s.label, units: f.units.value,
      step_ml: mlOrNull(f.step_ml),
      quick_mode: f.quick_mode.value, quick_custom: custom,
      quick_from: mlOrNull(f.quick_from), quick_to: mlOrNull(f.quick_to), quick_step: mlOrNull(f.quick_step),
      night_from: f.night_from.value || "21:00", night_to: f.night_to.value || "07:00",
    };
    let ok = false;
    try { ok = Store.setSettings(patch); } catch (e) { showToast(errText(e)); return; }
    if (!ok) { showToast("Could not save settings — storage is blocked"); return; }
    applyNight();
    renderHeader();
    showToast("Settings saved");
  };
  const mlField = (key, label, value) => field(key, label, el("input", { type: "number", inputmode: "numeric", min: "0", step: "1", value: value == null ? "" : String(value) }));
  const mode = s.quick_mode === "custom" ? "custom" : s.quick_mode === "recent" ? "recent" : "range";
  return el("div", { class: "card", id: "settings-form" },
    el("div", { class: "h2" }, "This phone"),
    field("label", "Who is holding this phone", el("input", { type: "text", value: s.label || "", placeholder: "Dad, Mom…", autocapitalize: "words" })),
    el("div", { class: "two" },
      field("units", "Units", el("select", {}, el("option", { value: "ml", selected: s.units !== "oz" }, "ml"), el("option", { value: "oz", selected: s.units === "oz" }, "oz"))),
      mlField("step_ml", "−/+ step (ml, blank = auto)", s.step_ml)),
    field("quick_mode", "Quick amounts", el("select", {},
      el("option", { value: "range", selected: mode === "range" }, "a range"),
      el("option", { value: "recent", selected: mode === "recent" }, "from recent feeds"),
      el("option", { value: "custom", selected: mode === "custom" }, "custom list"))),
    el("div", { class: "three" },
      mlField("quick_from", "Range from (ml)", s.quick_from),
      mlField("quick_to", "to (ml)", s.quick_to),
      mlField("quick_step", "step (ml)", s.quick_step)),
    field("quick_custom", "Custom amounts (ml, comma separated)", el("input", { type: "text", inputmode: "numeric", value: (s.quick_custom || []).join(", "), placeholder: "30, 60, 90, 120" })),
    el("div", { class: "two" },
      field("night_from", "Night from", el("input", { type: "time", value: s.night_from || "21:00" })),
      field("night_to", "Night to", el("input", { type: "time", value: s.night_to || "07:00" }))),
    el("div", { class: "muted small" }, `Automatic step right now: ${amount(Core.stepMl(recentMls(), unit()))}`),
    el("div", { class: "actions" }, el("button", { class: "btn primary wide", type: "button", onclick: save }, "Save settings")));
}

function renderChildCard() {
  const card = document.getElementById("settings-child");
  if (!card) return;
  const c = Store.child();
  const kids = Store.children();
  if (!c) { fill(card, el("div", { class: "h2" }, "Child"), el("p", { class: "muted" }, "Waiting for the first sync — the child is created on the PC.")); return; }
  // Rebuilt only when the child on screen changes, so typing survives a pull.
  if (card.dataset.child === `${c.child_id}/${c.revision}` && card.children.length) return;
  card.dataset.child = `${c.child_id}/${c.revision}`;
  const t = c.targets || {};
  const f = {};
  const field = (key, label, input) => { f[key] = input; return el("label", { class: "field" }, el("span", {}, label), input); };
  const num = (v) => el("input", { type: "number", inputmode: "numeric", min: "0", step: "1", value: v == null ? "" : String(v) });
  const msg = el("div", { class: "ed-msg err", hidden: true });
  const save = async (btn) => {
    const name = f.name.value.trim(), born = f.born.value;
    const n = (inp) => (inp.value === "" ? null : Number(inp.value));
    const fields = { name, born, born_time: f.born_time.value || null, birth_weight_g: n(f.birth_weight_g),
      targets: { feeds_per_day: n(f.feeds_per_day), wet_per_day: n(f.wet_per_day), dirty_per_day: n(f.dirty_per_day) } };
    btn.disabled = true;
    try {
      await Store.reviseChild(c, fields);
      Sync.afterWrite();
      msg.hidden = true;
      delete card.dataset.child;
      renderHeader();
      renderChildCard();
      showToast(`${name} updated`);
    } catch (e) { msg.hidden = false; msg.textContent = errText(e); }
    btn.disabled = false;
  };
  fill(card,
    el("div", { class: "h2" }, "Child"),
    kids.length >= 2 ? el("label", { class: "field" }, el("span", {}, "Showing"),
      el("select", { onchange: (x) => { Store.setSettings({ child_id: x.target.value || null }); delete card.dataset.child; renderHeader(); renderSettings(); } },
        ...kids.map((k) => el("option", { value: k.child_id, selected: k.child_id === c.child_id }, k.name)))) : null,
    field("name", "Name", el("input", { type: "text", value: c.name || "", autocapitalize: "words" })),
    el("div", { class: "two" },
      field("born", "Born", el("input", { type: "date", value: c.born || "" })),
      field("born_time", "Time of birth", el("input", { type: "time", value: c.born_time || "" }))),
    field("birth_weight_g", "Birth weight (g)", num(c.birth_weight_g)),
    el("div", { class: "h3" }, "Targets (what the pediatrician said)"),
    el("div", { class: "three" },
      field("feeds_per_day", "Feeds / day", num(t.feeds_per_day)),
      field("wet_per_day", "Wet / day", num(t.wet_per_day)),
      field("dirty_per_day", "Dirty / day", num(t.dirty_per_day))),
    msg,
    el("div", { class: "actions" }, el("button", { class: "btn primary wide", type: "button", onclick: (x) => save(x.target) }, "Save child")));
}

function renderSyncCard() {
  const card = document.getElementById("settings-sync");
  if (!card) return;
  const st = Sync.state();
  const m = Store.meta();
  const signedIn = Graph.isSignedIn();
  const who = Graph.who() || m.signed_in_as;
  const failed = Store.failed();
  const conflicts = m.conflicts || [];
  const usage = el("div", { class: "muted small", id: "usage" }, "…");
  Store.usage().then((u) => {
    const mb = u.usage == null ? "" : ` · ${(u.usage / 1048576).toFixed(1)} MB used${u.quota ? ` of ${Math.round(u.quota / 1048576)}` : ""}`;
    usage.textContent = `${u.events} ${u.events === 1 ? "entry" : "entries"} on this phone · ${u.queue} waiting${mb}`;
  }).catch(() => { usage.textContent = ""; });
  // Which shell is actually running — the one fact that settles "did the phone update?".
  const version = el("div", { class: "muted small", id: "app-version" }, "");
  swVersion((v) => { version.textContent = v ? `Phone app ${v}` : ""; });
  const act = async (label, fn) => { try { await fn(); } catch (e) { showToast(errText(e)); } renderSyncCard(); renderPill(); };
  fill(card,
    el("div", { class: "h2" }, "Sync"),
    !Graph.configured() ? notice("warn", "Sign-in is not configured yet: add the Application (client) ID from guide/SETUP.md to config.js and redeploy. "
      + "Logging works without it — entries queue on this phone until there is somewhere to send them.") : null,
    el("div", { class: "state" }, el("span", { class: `dot ${st.online ? "on" : "off"}` }), el("span", {}, st.online ? "Online" : "Offline")),
    el("div", { class: "state" }, el("span", { class: `dot ${signedIn ? "on" : ""}` }),
      el("span", {}, signedIn ? `Signed in as ${who || "…"}` : (who ? `Signed out · was ${who}` : "Not signed in"))),
    el("div", { class: "muted small" }, m.last_sync_at ? `Last sync ${clockOf(m.last_sync_at)}${m.full_sync_at ? ` · full catch-up ${Core.fmtDay(Core.isoLocal(new Date(Date.parse(m.full_sync_at))))}` : ""}` : "Never synced on this phone"),
    m.last_error && m.last_error.message ? el("div", { class: "muted small" }, `Last error ${clockOf(m.last_error.at)} · ${m.last_error.code || ""} ${m.last_error.message}`) : null,
    usage,
    version,
    el("div", { class: "actions" },
      Graph.configured() && !signedIn ? el("button", { class: "btn primary", type: "button", onclick: () => act("sign in", () => Graph.signIn()) }, "Sign in") : null,
      // The full catch-up, not the 45 s pull: the one way to recover a PC file that landed in a
      // day folder after that folder was retired.
      signedIn ? el("button", { class: "btn", type: "button", onclick: () => act("sync", () => Sync.fullSync()) }, "Sync now") : null,
      signedIn ? el("button", { class: "btn ghost", type: "button", onclick: () => act("sign out", () => Graph.signOut()) }, "Sign out") : null),
    // The same line as the pill, under Sync now: onSync updates it in place on every progress
    // event, so the phases and the outcome show here too (§7.3).
    el("div", { class: "muted small", id: "sync-line" }, Sync.statusText()),
    signedIn ? el("div", { class: "muted small" }, "Sync now checks every day folder of the last 120 days.") : null,
    conflicts.length ? el("div", {},
      el("div", { class: "h3" }, `Changed on two devices (${conflicts.length})`),
      el("div", { class: "muted small" }, "This phone and another device both changed these while apart; one version won. Open each and check it."),
      ...conflicts.map((c) => el("button", { class: "qrow openable", type: "button", "data-event-id": c.event_id, onclick: () => openConflict(c.event_id) },
        el("span", { class: "grow" }, conflictText(c), el("div", { class: "muted small" }, clockOf(c.at))),
        el("span", { class: "chev" }, "›"))),
      el("div", { class: "actions" },
        el("button", { class: "linkish", type: "button", onclick: () => act("clear", () => { Store.setMeta({ conflicts: [] }); }) }, "Clear the list"))) : null,
    failed.length ? el("div", {},
      el("div", { class: "h3" }, `Stuck (${failed.length})`),
      ...failed.map((fl) => el("div", { class: "qrow" },
        el("span", { class: "grow" }, `${fl.kind === "child" ? "child" : `${TYPE_LABEL[(fl.body || {}).type] || "entry"} ${(fl.body || {}).time ? Core.fmtDateTime(fl.body.time) : ""}`}`,
          el("div", { class: "muted small" }, `${fl.status || ""} ${fl.code || ""} ${fl.message || ""}`.trim())),
        el("button", { class: "linkish", type: "button", onclick: () => act("retry", () => Store.retryFailed(fl.qid).then(() => Sync.afterWrite())) }, "Retry"),
        el("button", { class: "linkish danger", type: "button", onclick: () => act("discard", () => { Store.discardFailed(fl.qid); }) }, "Discard")))) : null);
}

function renderNeedsCard() {
  const card = document.getElementById("settings-needs");
  if (!card) return;
  const needs = Store.needsCheck();
  fill(card,
    el("div", { class: "h2" }, `Needs check (${needs.length})`, el("span", { class: "sub" }, "hard-to-read paper readings — swipe right if it looks right, left to delete, or tap to correct it")),
    needs.length ? el("div", { class: "rows" }, ...needs.map(swipeRow)) : el("div", { class: "empty" }, "Nothing left to check."));
}

function renderDeletedCard() {
  const card = document.getElementById("settings-deleted");
  if (!card) return;
  const del = Store.deleted();
  fill(card,
    el("div", { class: "h2" }, `Deleted (${del.length})`, el("span", { class: "sub" }, "Restore brings an entry back as it last was")),
    del.length ? el("div", {}, ...del.map((ev) => el("div", { class: "qrow", "data-event-id": ev.event_id },
      el("span", { class: "grow" }, `${TYPE_LABEL[ev.type] || ev.type} · ${Core.fmtDateTime(ev.time)} · ${Core.describe(ev, unit())}`,
        el("div", { class: "muted small" }, `${ev.reason ? `${ev.reason} · ` : ""}by ${ev.edited_by || ev.logged_by || "?"}`)),
      el("button", { class: "linkish", type: "button", onclick: async () => {
        await restoreEntry(ev.event_id);
        const back = Store.event(ev.event_id);
        renderDeletedCard();
        if (back && !back.deleted) openEditor({ event: back });
      } }, "Restore")))) : el("div", { class: "empty" }, "Nothing deleted."));
}

// ---------------------------------------------------------------- the editor
function draftFrom(ev) {
  return { event_id: ev.event_id, child_id: ev.child_id, type: ev.type, time: ev.time, end: ev.end,
    data: clone(ev.data || Core.defaults(ev.type)), note: ev.note || "", logged_by: ev.logged_by || myLabel() };
}

/* opts: {event} for an existing entry, or {type, data?, time?} for a new one. `sameAs` is the
   2-minute diaper rule, `focusEnd` the stale-timer "Set end time", `fields` a restored draft. */
function openEditor(opts) {
  const ev = opts.event || null;
  let draft;
  if (opts.fields) {
    draft = clone(opts.fields);
    draft.event_id = ev ? ev.event_id : null;
    if (!draft.data) draft.data = Core.defaults(draft.type);
  } else if (ev) {
    draft = draftFrom(ev);
    if (opts.sameAs) {
      draft.data.wet = draft.data.wet || opts.sameAs.wet;
      draft.data.dirty = draft.data.dirty || opts.sameAs.dirty;
    }
  } else {
    const c = Store.child();
    draft = { event_id: null, child_id: c ? c.child_id : null, type: opts.type,
      time: opts.time || nowIso(), end: null, data: Object.assign(Core.defaults(opts.type), opts.data || {}),
      note: "", logged_by: myLabel() };
  }
  if (app.editor) { stopDraft(); Store.clearDraft(); }   // replacing one editor with another
  app.editor = { draft, event: ev, msg: null, msgKind: "err", confirming: false, unusualOk: false,
    sameAs: opts.sameAs || null, focusEnd: !!opts.focusEnd, portionsTyped: false,
    whoOther: false, formulaOther: [], restored: !!opts.fields, notice: null, syncing: false, saving: false };
  const already = currentScreen() === "editor";
  renderEditor();
  if (already) renderHeader(); else show("editor", { push: true });
}

function editorTitle() {
  const e = app.editor;
  if (!e) return "";
  const d = e.draft;
  if (!e.event) return NEW_TITLE[d.type] || TYPE_LABEL[d.type];
  const isRunning = TIMED.includes(d.type) && d.end === null && d.type !== "pump" && !!(d.data && d.data.timer);
  return `${TYPE_LABEL[d.type]} · ${Core.fmtDateTime(d.time)}${isRunning ? " · running" : ""}`;
}

function closeEditor() {
  stopDraft();
  Store.clearDraft();
  app.editor = null;
  const prev = app.stack.pop() || app.tab;
  renderScreen(prev);
  show(prev);
}

// -- drafts (§7.4): every input writes bl.draft, debounced 300 ms; cleared on Save/Delete/Cancel.
let draftTimer = null;
function markDirty() {
  const e = app.editor;
  if (!e) return;
  clearTimeout(draftTimer);
  draftTimer = setTimeout(() => {
    if (app.editor !== e) return;
    Store.setDraft({ screen: "editor", event_id: e.draft.event_id, fields: clone(e.draft), saved_at: Core.nowIso() });
  }, 300);
}
function stopDraft() { clearTimeout(draftTimer); draftTimer = null; }
/** On open: a draft under 12 h old reopens its editor with the fields restored. */
function restoreDraft() {
  const d = Store.draft();
  if (!d || d.screen !== "editor" || !d.fields || !d.fields.type) return false;
  const age = Date.now() - Date.parse(d.saved_at || "");
  if (Number.isNaN(age) || age > DRAFT_MAX_MS || !Core.TYPES.includes(d.fields.type)) { Store.clearDraft(); return false; }
  let ev = null;
  if (d.event_id) {
    ev = Store.event(d.event_id);
    if (!ev || ev.deleted) { Store.clearDraft(); return false; }
  }
  openEditor({ event: ev, type: d.fields.type, fields: d.fields });
  return true;
}
// A chip or toggle handler: change the draft, remember it, redraw.
const mut = (fn) => () => { fn(); markDirty(); renderEditor(); };

function setMsg(text, kind = "err") {
  const e = app.editor;
  if (!e) return;
  e.msg = text; e.msgKind = kind;
  renderMsg();
}
function renderMsg() {
  const box = document.getElementById("ed-msg");
  const e = app.editor;
  if (!box || !e) return;
  if (!e.msg) { box.hidden = true; box.replaceChildren(); return; }
  box.hidden = false;
  box.className = `ed-msg ${e.msgKind}`;
  box.replaceChildren(document.createTextNode(e.msg));
  if (e.msgKind === "ask") {
    box.append(el("button", { class: "btn ghost", type: "button",
      onclick: () => { e.unusualOk = true; e.msg = null; saveEditor(); } }, "Save anyway"));
  }
}
function renderSyncLine() {
  const line = document.getElementById("ed-syncing");
  if (line && app.editor) line.hidden = !app.editor.syncing;
}
// Save and Delete go dark while a write is in flight, so a second tap from a sleepy thumb
// cannot write the entry twice; renderEditor draws them that way too if it runs mid-save. Only
// the editor still on screen is touched — the ids are reused by the next one.
function setSaving(e, on) {
  e.saving = on;
  if (app.editor !== e) return;
  for (const id of ["ed-save", "ed-delete"]) {
    const b = document.getElementById(id);
    if (b) b.disabled = on;
  }
}

function renderEditor() {
  const e = app.editor;
  const host = screens.editor;
  if (!e) return;
  const d = e.draft;
  const isNew = !e.event;
  const kids = [];

  if (e.restored) kids.push(notice("info", "Draft restored"));
  if (e.notice) kids.push(notice("info", e.notice));
  kids.push(el("div", { class: "notice info", id: "ed-syncing", hidden: !e.syncing }, "Syncing…"));
  if (e.sameAs && e.event) {
    kids.push(notice("info",
      `Same as the ${Core.fmtTime(e.event.time)} one? Save adds to it · Log another adds a new one`,
      el("button", { class: "btn ghost", type: "button", onclick: () => { const s = e.sameAs; closeEditor(); writeDiaper(s.wet, s.dirty); } }, "Log another")));
  }
  if (e.event && isCheck(e.event)) {
    kids.push(notice("warn", "From the paper sheet, marked for checking — correct it and remove the “Check:” from the note."));
  }

  // -- common: Start, the shift chips, End, Who
  const whenLabel = el("span", { class: "ed-when" }, Core.fmtDateTime(d.time));
  const timeInput = el("input", { type: "datetime-local", value: dtValue(d.time), step: "60", "aria-label": "Start",
    onchange: (x) => { const v = dtParse(x.target.value); if (v) { d.time = v; whenLabel.textContent = Core.fmtDateTime(d.time); } } });
  const shift = (n) => {
    d.time = Core.isoLocal(new Date(ms(d.time) - n * MIN));
    timeInput.value = dtValue(d.time);
    whenLabel.textContent = Core.fmtDateTime(d.time);
    markDirty();
  };
  const common = [
    el("div", { class: "ed-row" },
      el("span", { class: "lbl" }, "Start"), timeInput,
      el("div", { class: "chips" },
        el("button", { class: "chip", type: "button", onclick: () => shift(5) }, "−5"),
        el("button", { class: "chip", type: "button", onclick: () => shift(15) }, "−15"),
        el("button", { class: "chip", type: "button", onclick: () => shift(30) }, "−30 min"),
        whenLabel)),
  ];
  // End is hidden for feeds: a bottle has no useful end (§6.2). The record keeps whatever end
  // it has; a new one gets end = start on Save.
  if (TIMED.includes(d.type) && d.type !== "feed") {
    const endInput = el("input", { type: "datetime-local", value: dtValue(d.end), step: "60", id: "ed-end", "aria-label": "End",
      onchange: (x) => { d.end = x.target.value ? dtParse(x.target.value) : null; } });
    common.push(el("div", { class: "ed-row" },
      el("span", { class: "lbl" }, "End"), endInput,
      el("div", { class: "chips" },
        el("button", { class: "chip", type: "button", onclick: mut(() => { d.end = nowIso(); }) }, "now"),
        d.end !== null ? el("button", { class: "chip", type: "button", onclick: mut(() => { d.end = null; }) }, "clear") : null,
        d.end === null ? el("span", { class: "muted small" }, d.type === "pump" ? "" : (isNew ? "blank = still going" : "running")) : null)));
  }
  const labels = knownLabels();
  if (d.logged_by && !labels.includes(d.logged_by)) labels.push(d.logged_by);
  common.push(el("div", { class: "ed-row" }, el("span", { class: "lbl" }, "Who"),
    el("div", { class: "chips" },
      ...labels.map((l) => el("button", { class: `chip${d.logged_by === l ? " active" : ""}`, type: "button",
        onclick: mut(() => { d.logged_by = l; }) }, l)),
      e.whoOther ? el("input", { type: "text", placeholder: "name", autocapitalize: "words", value: labels.includes(d.logged_by) ? "" : d.logged_by,
        style: "width:8em", oninput: (x) => { d.logged_by = x.target.value; } })
        : el("button", { class: "chip", type: "button", onclick: mut(() => { e.whoOther = true; }) }, "Other…"))));
  kids.push(el("div", { class: "card" }, ...common));

  // -- the type's own controls
  const section = { feed: feedSection, diaper: diaperSection, sleep: sleepSection, pump: pumpSection,
    growth: growthSection, health: healthSection, note: noteSection }[d.type];
  kids.push(el("div", { class: "card" }, ...section(d, e)));

  // -- note, type, child
  const children = Store.children();
  kids.push(el("div", { class: "card" },
    el("label", { class: "field" }, el("span", {}, "Note"),
      el("textarea", { rows: "2", autocapitalize: "sentences", autocorrect: "on", spellcheck: "true",
        oninput: (x) => { d.note = x.target.value; } }, d.note)),
    el("label", { class: "field" }, el("span", {}, "Change type…"),
      el("select", { onchange: (x) => changeType(x.target.value) },
        ...Core.TYPES.map((t) => el("option", { value: t, selected: t === d.type }, TYPE_LABEL[t])))),
    children.length >= 2 ? el("label", { class: "field" }, el("span", {}, "Child"),
      el("select", { onchange: (x) => { d.child_id = x.target.value; } },
        ...children.map((k) => el("option", { value: k.child_id, selected: k.child_id === d.child_id }, k.name)))) : null));

  kids.push(el("div", { class: "ed-msg", id: "ed-msg", hidden: true }));
  if (e.confirming) {
    // In-page, two 48 px buttons, the destructive one outlined and worded (§7.4).
    kids.push(el("div", { class: "confirm-sheet" },
      `Delete ${TYPE_LABEL[d.type].toLowerCase()} ${Core.fmtTime(d.time)}?`,
      el("div", { class: "actions" },
        el("button", { class: "btn tall", type: "button", onclick: () => { e.confirming = false; renderEditor(); } }, "Keep"),
        el("button", { class: "btn danger tall", type: "button", onclick: deleteEntry }, "Delete"))));
  }

  kids.push(el("div", { class: "ed-foot" },
    el("button", { class: `btn wide${d.type === "feed" ? " feed" : " primary"}`, id: "ed-save", type: "button", disabled: e.saving, onclick: saveEditor }, isNew ? "Save" : "Save changes"),
    el("button", { class: "btn ghost wide", type: "button", onclick: closeEditor }, "Cancel"),
    !isNew ? el("button", { class: "btn danger wide", id: "ed-delete", type: "button", disabled: e.saving, onclick: () => { e.confirming = true; renderEditor(); } }, "Delete") : null));

  fill(host, ...kids);
  renderMsg();
  if (e.focusEnd) {
    e.focusEnd = false;
    const endInput = document.getElementById("ed-end");
    if (endInput) endInput.focus();
  }
}

// Keeps time, end, note, who and child; resets data to the new type's defaults (§6.2).
function changeType(type) {
  const e = app.editor, d = e.draft;
  if (type === d.type) return;
  d.type = type;
  d.data = Core.defaults(type);
  if (!TIMED.includes(type)) d.end = null;
  e.unusualOk = false;
  markDirty();
  renderEditor();
  renderHeader();
}

// An amount control: −/+ by the step, typed in the display unit, stored as whole ml. The stored
// value is untouched until the user changes it, so oz mode never nudges a 22 ml feed (§8.1).
function amountControl(get, set, opts = {}) {
  const u = unit();
  const input = el("input", { type: "number", inputmode: u === "oz" ? "decimal" : "numeric", min: "0",
    step: u === "oz" ? "0.25" : "1", value: get() == null ? "" : String(Core.toUnit(get(), u)),
    placeholder: opts.placeholder || "", "aria-label": opts.label || "amount",
    oninput: (x) => { set(x.target.value === "" ? null : Core.fromUnit(x.target.value, u)); } });
  const nudge = (dir) => {
    const cur = get() == null ? 0 : get();
    const v = Math.max(0, cur + dir * stepMl());
    set(v); input.value = String(Core.toUnit(v, u));
    markDirty();
  };
  return el("span", { class: "amt" },
    el("button", { type: "button", "aria-label": "less", onclick: () => nudge(-1) }, "−"),
    input,
    el("button", { type: "button", "aria-label": "more", onclick: () => nudge(1) }, "+"));
}

/* The feed editor is bottle only (§6.2, since 27 Sep 2026): portions with a kind, an amount
   and — for formula — the name chips, then made / leftover. No side timers and no typed
   minutes; a record that still carries breast seconds (the paper rows) shows them as one
   read-only line and keeps them untouched through Save. */
function feedSection(d, e) {
  const br = d.data.breast || {};
  const evs = events();
  const out = [];

  // -- what an older record carries: shown, never edited, never nulled
  if (br.total_s != null || br.left_s != null || br.right_s != null) {
    const s = Core.breastSeconds({ type: "feed", data: d.data, end: d.end }, new Date());
    let text = `Breast ${br.approx ? "~" : ""}${Math.round(s / 60)} min`;
    if (br.left_s != null || br.right_s != null) text += ` (L ${Math.round((br.left_s || 0) / 60)} / R ${Math.round((br.right_s || 0) / 60)})`;
    if (br.last_side) text += ` · last side ${br.last_side}`;
    out.push(el("div", { class: "muted small breast-line" }, text, el("span", {}, " — as recorded; breast feeding is no longer entered")));
  }
  if (d.data.timer) out.push(notice("warn", "This feed still has a timer running — Stop it from its card on Now."));

  // -- bottle portions, each with its formula chips
  out.push(el("div", { class: "h3" }, "Bottle"));
  const portions = el("div", {});
  const choices = formulaChoices();
  const formulaRow = (b, i) => {
    if (b.kind !== "formula") return null;
    const names = choices.slice();
    if (b.formula && !names.includes(b.formula)) names.push(b.formula);   // an older name stays choosable
    const other = e.formulaOther.includes(i);
    const pick = (name) => { b.formula = name; e.formulaOther = e.formulaOther.filter((x) => x !== i); markDirty(); drawPortions(); };
    return el("div", { class: "chips scroll formula" },
      ...names.map((name) => el("button", { class: `chip feed${!other && b.formula === name ? " active" : ""}`, type: "button", onclick: () => pick(name) }, name)),
      other
        ? el("input", { type: "text", class: "formula-other", placeholder: "formula name", autocapitalize: "words", "aria-label": "Formula name",
            value: b.formula && !choices.includes(b.formula) ? b.formula : "",
            oninput: (x) => { b.formula = x.target.value.trim() || null; } })
        : el("button", { class: "chip", type: "button", onclick: () => { b.formula = null; e.formulaOther.push(i); markDirty(); drawPortions(); focusOther(); } }, "Other…"));
  };
  const focusOther = () => { const inp = portions.querySelector("input.formula-other"); if (inp) inp.focus(); };
  const drawPortions = () => {
    portions.replaceChildren(...d.data.bottles.map((b, i) => el("div", { class: "portion-wrap" },
      el("div", { class: "portion" },
        el("button", { class: `toggle${b.kind === "formula" ? " on" : ""}`, type: "button", style: "flex:0 1 auto",
          onclick: () => {
            // Switching kind hides the chips: breast milk has no formula name.
            b.kind = b.kind === "formula" ? "breast_milk" : "formula";
            b.formula = b.kind === "formula" ? lastFormula() : null;
            e.formulaOther = e.formulaOther.filter((x) => x !== i);
            markDirty(); drawPortions();
          } },
          b.kind === "formula" ? "Formula" : "Breast milk"),
        amountControl(() => b.ml, (v) => { b.ml = v == null ? 0 : v; e.portionsTyped = true; }, { label: "portion" }),
        el("span", { class: "unit" }, unit()),
        el("button", { class: "remove", type: "button", "aria-label": "Remove portion",
          onclick: () => { d.data.bottles.splice(i, 1); e.formulaOther = []; e.portionsTyped = true; markDirty(); drawPortions(); } }, "×")),
      formulaRow(b, i))));
  };
  drawPortions();
  out.push(portions);

  // -- the quick amounts: Same as last, then the chips by quick_mode (§8.1)
  const lastBottle = evs.filter((ev) => ev.type === "feed" && Core.bottleMl(ev) > 0 && ev.event_id !== d.event_id).pop();
  const setLast = (mlv) => {
    if (!d.data.bottles.length) d.data.bottles.push(newPortion(mlv));
    else d.data.bottles[d.data.bottles.length - 1].ml = mlv;
    e.portionsTyped = true;
    markDirty();
    drawPortions();
  };
  const chips = el("div", { class: "chips scroll", id: "ed-quick", style: "margin-top:6px" });
  const drawChips = () => fill(chips,
    lastBottle ? el("button", { class: "chip feed", type: "button", onclick: () => setLast(Core.bottleMl(lastBottle)) },
      `Same as last · ${amount(Core.bottleMl(lastBottle))}`) : null,
    ...quickAmounts().map((mlv) => el("button", { class: "chip", type: "button", onclick: () => setLast(mlv) }, amount(mlv))),
    el("button", { class: "chip", type: "button", onclick: () => {
      const last = d.data.bottles.length ? d.data.bottles[d.data.bottles.length - 1].kind : "formula";
      d.data.bottles.push(newPortion(0, last));
      e.portionsTyped = true; markDirty(); drawPortions();
    } }, "Another portion"));
  drawChips();
  out.push(chips);
  if (settings().quick_mode === "range") out.push(rangeControl(drawChips));

  // -- made / leftover: with both set and no portion typed, one formula portion fills itself in
  const autoPortion = () => {
    if (d.data.made_ml == null || d.data.leftover_ml == null || e.portionsTyped) return;
    const mlv = d.data.made_ml - d.data.leftover_ml;
    if (mlv <= 0) return;
    if (!d.data.bottles.length) d.data.bottles.push(newPortion(mlv));
    else if (d.data.bottles.length === 1) d.data.bottles[0].ml = mlv;
    drawPortions();
  };
  out.push(el("div", { class: "portion", style: "margin-top:10px" },
    el("span", { class: "muted small" }, "Made"),
    amountControl(() => d.data.made_ml, (v) => { d.data.made_ml = v; autoPortion(); }, { label: "made" }),
    el("span", { class: "muted small" }, "leftover"),
    amountControl(() => d.data.leftover_ml, (v) => { d.data.leftover_ml = v; autoPortion(); }, { label: "leftover" }),
    el("span", { class: "unit" }, unit())));
  return out;
}

/** The range beside the chips (§8.1): from / to / step in the display unit, stored as ml the
    moment they change, and the chips redrawn at once — so the range moves up the week his
    feeds do without a trip to Settings. */
function rangeControl(redraw) {
  const s = settings();
  const u = unit();
  const box = (key, label) => {
    const input = el("input", { type: "number", inputmode: u === "oz" ? "decimal" : "numeric", min: "0", step: u === "oz" ? "0.25" : "1",
      "aria-label": `Range ${label}`, value: s[key] == null ? "" : String(Core.toUnit(s[key], u)),
      oninput: (x) => {
        const v = x.target.value === "" ? null : Core.fromUnit(x.target.value, u);
        try { Store.setSettings({ [key]: v }); } catch (err) { showToast(errText(err)); return; }
        redraw();
      } });
    return el("label", { class: "field" }, el("span", {}, label), input);
  };
  return el("div", { class: "range" }, box("quick_from", "from"), box("quick_to", "to"), box("quick_step", "step"), el("span", { class: "unit" }, u));
}

// A portion left at 0 — "Another portion" tapped and not yet typed, or an amount cleared — is
// not a bottle. Every write path drops those the same way, so a side tap or Stop now on such a
// draft is not refused by a validator that Save would have satisfied.
const cleanFeed = (data) => { data.bottles = (data.bottles || []).filter((b) => b && b.ml > 0); return data; };

// A timer action writes at once and the editor re-reads the saved record — a Switch is a
// revision, not a draft (§3.2). On another device's feed the flush-then-pull guard runs first.
async function writeFromEditor(patch) {
  const e = app.editor, d = e.draft;
  if (e.saving) return;                       // a second tap while the first write is in flight
  const raw = clone(patch.data || d.data);
  if (d.type === "feed") cleanFeed(raw);
  let data;
  try { data = Core.validate(d.type, raw); } catch (x) { setMsg(x.message); return; }
  const fields = { type: d.type, time: d.time, end: patch.end === undefined ? d.end : patch.end, data, note: d.note, logged_by: d.logged_by };
  if (d.child_id) fields.child_id = d.child_id;
  setSaving(e, true);
  try {
    let held = e.event;
    if (held) held = await guardOther(held);
    const rec = held ? await Store.revise(held, fields) : await Store.newEvent(fields);
    Sync.afterWrite();
    if (app.editor !== e) return;
    e.event = rec;
    e.draft = draftFrom(rec);
    e.msg = null; e.restored = false; e.notice = null;
    stopDraft(); Store.clearDraft();
    e.saving = false;
    renderEditor();
    renderHeader();
  } catch (x) { setSaving(e, false); setMsg(errText(x)); }
}

function diaperSection(d) {
  const dd = d.data;
  const out = [];
  const flag = (key, cls, text) => el("button", { class: `toggle ${cls}${dd[key] ? " on" : ""}`, type: "button",
    onclick: mut(() => { dd[key] = !dd[key]; }) }, text);
  out.push(el("div", { class: "flags" }, flag("wet", "wet", "Wet"), flag("dirty", "dirty", "Dirty")));
  out.push(el("div", { class: "flags", style: "margin-top:8px" }, flag("rash", "", "Rash"), flag("blowout", "", "Blowout")));
  const enumRow = (label, key, values, swatch) => el("div", { class: "ed-row" }, el("span", { class: "lbl" }, label),
    el("div", { class: "chips scroll" }, ...values.map((v) => el("button", { class: `chip diaper${dd[key] === v ? " active" : ""}`, type: "button",
      onclick: mut(() => { dd[key] = dd[key] === v ? null : v; }) },
      swatch ? el("i", { class: "swatch", style: `background:${STOOL[v]}` }) : null, v.replace(/_/g, " ")))));
  out.push(enumRow("Colour", "color", Core.ENUMS.color, true));
  out.push(enumRow("Texture", "texture", Core.ENUMS.texture));
  out.push(enumRow("Size", "size", Core.ENUMS.size));
  return out;
}

function sleepSection(d, e) {
  const out = [];
  const run = d.end === null && e.event;
  if (run) out.push(el("div", { class: "actions" },
    el("span", { class: "timer", "data-elapsed": d.time, style: "font-size:1.4rem;font-weight:600;align-self:center" }, Core.sinceText(Date.now() - ms(d.time))),
    el("button", { class: "btn primary", type: "button", onclick: () => writeFromEditor({ data: Object.assign(clone(d.data), { timer: null }), end: nowIso() }) }, "Stop now")));
  out.push(el("label", { class: "field" }, el("span", {}, "Where"),
    el("input", { type: "text", value: d.data.where || "", placeholder: "bassinet, arms, car seat…", autocapitalize: "none",
      oninput: (x) => { d.data.where = x.target.value || null; } })));
  return out;
}

function pumpSection(d) {
  return [
    el("div", { class: "field" }, el("span", {}, `Left (${unit()})`), amountControl(() => d.data.left_ml, (v) => { d.data.left_ml = v; }, { label: "left" })),
    el("div", { class: "field" }, el("span", {}, `Right (${unit()})`), amountControl(() => d.data.right_ml, (v) => { d.data.right_ml = v; }, { label: "right" })),
    el("label", { class: "field" }, el("span", {}, "Minutes"),
      el("input", { type: "number", inputmode: "numeric", min: "0", step: "1",
        value: d.data.minutes == null ? "" : String(d.data.minutes),
        oninput: (x) => { d.data.minutes = x.target.value === "" ? null : Number(x.target.value); } }))];
}

function growthSection(d) {
  const num = (key, label, step, mode) => el("label", { class: "field" }, el("span", {}, label),
    el("input", { type: "number", inputmode: mode, min: "0", step,
      value: d.data[key] == null ? "" : String(d.data[key]),
      oninput: (x) => { d.data[key] = x.target.value === "" ? null : Number(x.target.value); } }));
  const c = Store.child();
  const birth = c && c.birth_weight_g;
  return [
    num("weight_g", "Weight (g)", "1", "numeric"),
    birth != null && d.data.weight_g != null ? el("div", { class: "muted small", style: "margin:-4px 0 10px" },
      `${d.data.weight_g - birth >= 0 ? "+" : ""}${d.data.weight_g - birth} g from birth`) : null,
    el("div", { class: "two" },
      num("length_cm", "Length (cm)", "0.1", "decimal"),
      num("head_cm", "Head (cm)", "0.1", "decimal"))];
}

function healthSection(d) {
  const meds = knownMedicines();
  const text = (key, label, list) => el("label", { class: "field" }, el("span", {}, label),
    el("input", { type: "text", value: d.data[key] || "", list, autocapitalize: "sentences",
      oninput: (x) => { d.data[key] = x.target.value || null; } }));
  return [
    el("datalist", { id: "ed-meds" }, ...meds.map((m) => el("option", { value: m }))),
    el("div", { class: "chips scroll", style: "margin-bottom:10px" },
      ...meds.map((m) => el("button", { class: `chip${d.data.medicine === m ? " active" : ""}`, type: "button",
        onclick: mut(() => { d.data.medicine = m; }) }, m))),
    text("medicine", "Medicine", "ed-meds"),
    text("dose", "Dose"),
    el("label", { class: "field" }, el("span", {}, "Temp (°C)"),
      el("input", { type: "number", inputmode: "decimal", min: "0", step: "0.1",
        value: d.data.temp_c == null ? "" : String(d.data.temp_c),
        oninput: (x) => { d.data.temp_c = x.target.value === "" ? null : Number(x.target.value); } })),
    text("symptom", "Symptom")];
}

function noteSection(d) {
  return [el("label", { class: "flags", style: "align-items:center;gap:10px;min-height:44px" },
    el("input", { type: "checkbox", checked: d.data.milestone, onchange: (x) => { d.data.milestone = x.target.checked; } }),
    "Milestone")];
}

// The in-page refusals (§6.2): born..now+10 min, End after Start, made over leftover.
function validateDraft(d) {
  const t = ms(d.time);
  if (Number.isNaN(t)) return "Start needs a date and time";
  const c = Store.child();
  if (c && c.born) {
    let bornAt = null;
    if (c.born_time) {
      const [y, mo, dd] = c.born.split("-").map(Number);
      const [h, mi] = c.born_time.split(":").map(Number);
      bornAt = new Date(y, mo - 1, dd, h, mi, 0).getTime();
    }
    if (Core.localDate(d.time) < c.born || (bornAt !== null && t < bornAt)) {
      return `Start is before ${c.name} was born (${Core.fmtDay(c.born)}${c.born_time ? ` ${c.born_time}` : ""})`;
    }
  }
  if (t > Date.now() + 10 * MIN) return "Start can't be more than 10 minutes in the future";
  if (d.end !== null) {
    const en = ms(d.end);
    if (Number.isNaN(en)) return "End needs a date and time, or leave it blank";
    if (en < t) return "End can't be before Start";
  }
  if (d.type === "feed" && d.data.made_ml != null && d.data.leftover_ml != null && d.data.made_ml < d.data.leftover_ml) {
    return "Made can't be less than leftover";
  }
  return null;
}

/** A revise or tombstone pulls first when the last pull is older than a few poll intervals
    (Sync.stalePull); the editor shows "Syncing…" and proceeds when it finishes or fails (§7.3). */
async function pullIfStale(e) {
  if (!Sync.stalePull(Store.meta()) || !Graph.isSignedIn() || navigator.onLine === false) return;
  if (e) { e.syncing = true; renderSyncLine(); }
  try { await Sync.run(); } catch { /* the run reports its own failure */ }
  if (e) { e.syncing = false; renderSyncLine(); }
}

async function saveEditor() {
  const e = app.editor, d = e.draft;
  if (e.saving) return;                       // a second tap while the first write is in flight
  const err = validateDraft(d);
  if (err) { setMsg(err); return; }
  let data = clone(d.data);
  if (d.type === "feed") {
    cleanFeed(data);
    if (d.end !== null && data.timer) data = foldTimer(data, ms(d.end));
    // A feed typed in after the fact has no timer: it is over, so it gets its end (Core.isRunning
    // reads end === null as "still going").
    if (d.end === null && !data.timer) d.end = Core.isoLocal(new Date(ms(d.time) + Core.breastSeconds({ type: "feed", data, end: null }, 0) * 1000));
    if (!e.unusualOk && Core.unusual(Core.bottleMl({ data }), recentMls())) {
      setMsg("That's more than twice his biggest recent feed. Save anyway?", "ask");
      return;
    }
  }
  if (d.type === "sleep") {
    // No end and no timer means "still asleep": keep the sleep running rather than half-written.
    data.timer = d.end === null ? { running: true } : null;
  }
  try { data = Core.validate(d.type, data); } catch (x) { setMsg(x.message); return; }
  const fields = { type: d.type, time: d.time, end: TIMED.includes(d.type) ? d.end : null, data, note: d.note, logged_by: d.logged_by };
  if (d.child_id) fields.child_id = d.child_id;
  setSaving(e, true);
  try {
    let rec;
    if (e.event) {
      await pullIfStale(e);
      rec = await Store.revise(Store.event(e.event.event_id) || e.event, fields);
    } else {
      rec = await Store.newEvent(fields);
    }
    Sync.afterWrite();
    if (!e.event && d.type === "diaper") saveLastDiaper({ event_id: rec.event_id, ms: Date.now() });
    const wasNew = !e.event;
    closeEditor();
    showToast(`${TYPE_LABEL[d.type]} ${wasNew ? "saved" : "updated"} · ${Core.fmtTime(rec.time)}`,
      [{ label: "Edit", fn: () => openEditor({ event: Store.event(rec.event_id) || rec }) }]);
  } catch (x) {
    setSaving(e, false);
    setMsg(errText(x));
  }
}

async function deleteEntry() {
  const e = app.editor;
  const ev = e && e.event;
  if (!ev || e.saving) return;
  setSaving(e, true);
  try {
    await pullIfStale(e);
    await Store.tombstone(Store.event(ev.event_id) || ev, null);
    Sync.afterWrite();
    if (app.lastDiaper && app.lastDiaper.event_id === ev.event_id) saveLastDiaper(null);
    closeEditor();
    showToast("Deleted", [{ label: "Undo", fn: () => restoreEntry(ev.event_id) }]);
  } catch (x) {
    e.saving = false;
    e.confirming = false;
    renderEditor();
    setMsg(errText(x));
  }
}

// ---------------------------------------------------------------- sync events
/** After a pull changes records: the screen underneath re-renders, and an open editor on one of
    them re-reads it with a one-line notice (§7.3). A collision — this phone and another device
    both wrote the same revision, and §3.4 picked one — is said out loud on whatever screen is
    open, not only inside an editor. */
function onSync(kind, detail) {
  renderPill();
  // Settings → Sync carries the pill's line under Sync now; it moves with every phase (§7.3).
  const line = document.getElementById("sync-line");
  if (line) line.textContent = Sync.statusText();
  if (kind !== "applied") return;
  const ids = (detail && detail.ids) || [];
  const conflicts = (detail && detail.conflicts) || [];
  const e = app.editor;
  if (e && e.event && ids.includes(e.event.event_id)) {
    const rec = Store.event(e.event.event_id);
    if (rec && rec !== e.event) {
      // A pull can hand back a byte-identical copy of the record on screen (the phone's own
      // upload under another file name): swap the object, but only a change of substance may
      // touch what is being typed.
      const same = rec.revision === e.event.revision && rec.created_at === e.event.created_at
        && rec.device === e.event.device && rec.deleted === e.event.deleted;
      e.event = rec;
      if (!same) {
        if (!e.saving) e.draft = draftFrom(rec);
        e.notice = rec.deleted ? `Deleted on ${whose(rec)}` : `Updated from ${whose(rec)}`;
        renderEditor();
      }
    }
  }
  if (conflicts.length) showConflicts(conflicts);
  if (ids.some((id) => String(id).startsWith("C-"))) {
    const card = document.getElementById("settings-child");
    if (card) delete card.dataset.child;
  }
  if (currentScreen() === "settings") renderSettings({ listsOnly: true });
  else renderTab();
  renderHeader();
}

// ---------------------------------------------------------------- collisions
/* Sync remembers each one under meta.conflicts as {event_id, at, other}; `other` is the
   downloaded side, whichever way the rule went, because that is who to compare notes with. */
const conflictEntry = (id) => (Store.meta().conflicts || []).find((c) => c.event_id === id) || { event_id: id, other: null };
/** "Feed 02:10 · Updated from the PC" — the editor's own wording, on a toast or a Settings row. */
function conflictText(c) {
  const rec = Store.event(c.event_id);
  const other = c.other || null;
  const line = other && other.deleted ? `Deleted on ${whose(other)}` : `Updated from ${whose(other)}`;
  return rec ? `${TYPE_LABEL[rec.type] || rec.type} ${Core.fmtTime(rec.time)} · ${line}` : line;
}
function openConflict(id) {
  const rec = Store.event(id);
  if (rec && !rec.deleted) openEditor({ event: rec });
  else if (rec) { setTab("settings"); showToast("It is in the Deleted list — Restore brings it back"); }
}
function showConflicts(ids) {
  const first = ids[0];
  const rec = Store.event(first);
  const more = ids.length > 1 ? ` · ${ids.length - 1} more in Settings` : "";
  const action = rec && !rec.deleted
    ? { label: "Edit", fn: () => openEditor({ event: Store.event(first) || rec }) }
    : { label: "Settings", fn: () => setTab("settings") };
  showToast(conflictText(conflictEntry(first)) + more, [action], 10000);
}

// ---------------------------------------------------------------- clocks
// Once a second: only the live clocks change, so only those text nodes are touched.
function tick() {
  const now = Date.now();
  for (const n of document.querySelectorAll("[data-since]")) {
    n.textContent = `${Core.sinceText(now - ms(n.dataset.since))} ago`;
  }
  for (const n of document.querySelectorAll("[data-elapsed]")) {
    n.textContent = n.dataset.style === "clock" ? elapsedText(now - ms(n.dataset.elapsed))
      : Core.sinceText(now - ms(n.dataset.elapsed));
  }
}
// Once a minute: the night boundary, the pill's "N min ago", and the Now hints.
function everyMinute() {
  applyNight();
  renderPill();
  if (currentScreen() === "now") renderNow();
}

// ---------------------------------------------------------------- boot
async function boot() {
  document.getElementById("back").addEventListener("click", back);
  document.getElementById("moon").addEventListener("click", toggleNight);
  document.getElementById("pill").addEventListener("click", pillTap);
  document.querySelectorAll(".tab").forEach((b) => b.addEventListener("click", () => setTab(b.dataset.tab)));

  // When the keyboard opens it covers the lower 40% of the screen; hiding the tab bar keeps Save
  // reachable (§7.5).
  document.addEventListener("focusin", (e) => {
    if (e.target.matches("input, textarea, select")) {
      document.body.classList.add("keyboard");
      setTimeout(() => e.target.scrollIntoView({ block: "center", behavior: "smooth" }), 150);
    }
  });
  document.addEventListener("focusout", () => document.body.classList.remove("keyboard"));
  // Every keystroke and change in the editor lands in bl.draft (debounced in markDirty).
  screens.editor.addEventListener("input", markDirty);
  screens.editor.addEventListener("change", markDirty);

  app.date = todayStr();
  loadLastDiaper();
  app.storage = await Store.open();
  applyNight();
  if (!myLabel().trim()) await askLabel();

  if ("serviceWorker" in navigator) {
    // updateViaCache "none": the worker script itself is fetched past GitHub Pages' ten-minute
    // cache. And a new version announces itself instead of waiting for the visit after next —
    // the "close it twice" ritual is gone.
    navigator.serviceWorker.register("sw.js", { updateViaCache: "none" })
      .then((reg) => { app.sw = reg; reg.update().catch(() => {}); })
      .catch(() => { /* http:// dev, or unsupported */ });
    let hadController = !!navigator.serviceWorker.controller;
    navigator.serviceWorker.addEventListener("controllerchange", () => {
      if (!hadController) { hadController = true; return; }   // the very first install, not an update
      showToast("New version ready", [{ label: "Reload", fn: () => location.reload() }], 120000);
    });
  }

  Sync.onChange(onSync);
  setTab("now");
  restoreDraft();
  updateBadge();
  // The sign-in library comes from a CDN the service worker does not cache, so nothing on
  // screen waits for it (§7.1): resume() settles a redirect sign-in in the background, and only
  // the sync loop starts after it.
  Graph.resume().then(() => { renderPill(); Sync.start(); });

  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState !== "visible") return;
    if (app.sw) app.sw.update().catch(() => {});         // every time it comes to the front
    applyNight();
    renderPill();
    if (currentScreen() !== "editor") renderTab();
    tick();
    resumeIfSignedOut();
  });
  window.addEventListener("online", resumeIfSignedOut);
  setInterval(tick, 1000);
  setInterval(everyMinute, 60000);
}

// A library load that failed at boot (no signal in the nursery) is tried again when the phone
// comes back to the app or to the network, so the cached account syncs without a tap on the
// pill. Sync's own triggers cannot do this: they skip while signed out.
function resumeIfSignedOut() {
  if (!Graph.configured() || Graph.isSignedIn()) return;
  Graph.resume().then((ok) => { if (ok) { renderPill(); Sync.run(); } });
}

boot();
