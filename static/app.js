/* Baby Log — the PC window. SPEC.md §6.2, §8.
   One page: Today (the Now panel, the paper-style day sheet, the log buttons), Trends, Growth,
   Health, Reports and Settings, plus one editor dialog for every type of entry. Every calculation
   and every format goes through Core (docs/core.js, served at /core.js) so this screen and the
   phones never disagree about a number. Talks to app.py's JSON API (§6.1) and nothing else. */
"use strict";

const MIN = 60000;
const POLL_MS = 30000;
const TYPE_LABEL = { feed: "Feed", diaper: "Diaper", sleep: "Sleep", pump: "Pump", growth: "Growth", health: "Health", note: "Note" };
const TIMED = ["feed", "sleep", "pump"];          // the types that carry an End
const STOOL = { black: "#2A2A2A", dark_green: "#2F5A36", green: "#4F8A3A", yellow: "#D0A02A", brown: "#85552A", other: "#8A8A8A" };
const SEX = ["", "boy", "girl"];

const state = {
  config: null, settings: null, child: null, children: [],
  now: null,          // /api/now
  date: null,         // the day the sheet shows
  day: null,          // /api/day for that date
  events: [],         // every live event (/api/events), by time
  health: null,       // /api/health
  needs: [], deleted: [],
  view: "today",
  editor: null,       // the open dialog, see openEditor
  lastDiaper: null,   // {event_id, ms}: the last one-click diaper from this PC (the 2-minute rule)
  reports: { paths: [] },
  catchup: { date: null, added: [], records: {} },   // the Catch up screen: its day and what it wrote this session
};

// ---------------------------------------------------------------- small helpers
const pad = (n) => String(n).padStart(2, "0");
const nowIso = () => Core.isoLocal(new Date());
const todayStr = () => Core.localDate(nowIso());
const clone = (v) => JSON.parse(JSON.stringify(v));
const unit = () => (state.settings && state.settings.units) || "ml";
const myLabel = () => (state.settings && state.settings.label) || "";
const amount = (ml) => Core.fmtAmount(ml, unit());

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
// ...and what is typed back becomes a §3.2 string in this PC's zone.
function dtParse(v) {
  const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(v || "");
  if (!m) return null;
  return Core.isoLocal(new Date(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], 0));
}
// A UTC created_at shown as this PC's wall clock.
const clockOf = (iso) => Core.fmtTime(Core.isoLocal(new Date(ms(iso))));
// "12:34" / "1:02:03" for a live feed timer — seconds matter while it runs.
function elapsedText(msv) {
  const s = Math.max(0, Math.floor(msv / 1000));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
  return h ? `${h}:${pad(m)}:${pad(sec)}` : `${m}:${pad(sec)}`;
}
const hourOf = (iso) => Number(String(iso).slice(11, 13)) + Number(String(iso).slice(14, 16)) / 60;
const isCheck = (ev) => /^Check: | — Check: /.test(String(ev.note || ""));   // paper joins "note — Check: …"

function el(tag, props = {}, ...kids) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === "class") n.className = v;
    else if (k === "html") n.innerHTML = v;
    else if (k.startsWith("on") && typeof v === "function") n.addEventListener(k.slice(2), v);
    else if (v !== null && v !== undefined && v !== false) n.setAttribute(k, v);
  }
  for (const kid of kids.flat()) {
    if (kid === null || kid === undefined || kid === false) continue;
    n.append(kid?.nodeType ? kid : document.createTextNode(kid));
  }
  return n;
}
const SVG_NS = "http://www.w3.org/2000/svg";
function svg(tag, props = {}, ...kids) {
  const n = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(props)) {
    if (k.startsWith("on") && typeof v === "function") n.addEventListener(k.slice(2), v);
    else if (v !== null && v !== undefined && v !== false) n.setAttribute(k, v);
  }
  for (const kid of kids.flat()) if (kid) n.append(kid);
  return n;
}

async function api(path, opts) {
  const r = await fetch(path, opts);
  let body = null;
  try { body = await r.json(); } catch { /* non-JSON */ }
  if (!r.ok || (body && body.ok === false)) {
    throw Object.assign(new Error((body && body.error) || r.statusText), { status: r.status, body });
  }
  return body;
}
const jsonOpts = (method, payload) => ({
  method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload || {}),
});
const postJSON = (path, payload) => api(path, jsonOpts("POST", payload));
const deleteJSON = (path, payload) => api(path, jsonOpts("DELETE", payload));

function showStatus(kind, content, keepOpen = false) {
  const s = document.getElementById("status");
  s.className = `statusline ${kind}`;
  s.replaceChildren(content?.nodeType ? content : document.createTextNode(content));
  s.hidden = false;
  if (kind === "ok" && !keepOpen) {
    setTimeout(() => { if (s.className.includes("ok")) s.hidden = true; }, 12000);
  }
}
function hideStatus() { document.getElementById("status").hidden = true; }

// A 6-second toast with Undo / Edit style actions (§6.2). One at a time.
let toastTimer = null;
function showToast(text, actions = [], msv = 6000) {
  const t = document.getElementById("toast");
  t.replaceChildren(el("span", { class: "toast-text" }, text),
    ...actions.map((a) => el("button", { class: "toast-btn", type: "button",
      onclick: () => { hideToast(); a.fn(); } }, a.label)));
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(hideToast, msv);
}
function hideToast() { document.getElementById("toast").hidden = true; }

// The last one-click diaper survives a reload, so the 2-minute rule does too.
function loadLastDiaper() {
  try { state.lastDiaper = JSON.parse(localStorage.getItem("bl.pc.last_diaper")) || null; } catch { state.lastDiaper = null; }
}
function saveLastDiaper(v) {
  state.lastDiaper = v;
  try { localStorage.setItem("bl.pc.last_diaper", JSON.stringify(v)); } catch { /* a convenience only */ }
}

// ---------------------------------------------------------------- derived from the journal
// Bottle totals of the last 10 feeds that had any bottle — what every step and chip grows from.
function recentMls() {
  return state.events.filter((ev) => ev.type === "feed" && Core.bottleMl(ev) > 0).slice(-10).map(Core.bottleMl);
}
function stepMl() {
  const s = state.settings && state.settings.step_ml;
  return s ? Number(s) : Core.stepMl(recentMls(), unit());
}
// The quick-amount chips by quick_mode (§8.1): a range the owner moves up as the feeds grow (the
// default), the chips grown from recent feeds, or a typed list.
function quickAmounts() {
  const s = state.settings || {};
  const mode = s.quick_mode || "range";
  if (mode === "range") return Core.quickRange(s.quick_from, s.quick_to, s.quick_step);
  return Core.quickAmounts(recentMls(), unit(), mode === "custom" ? s.quick_custom : null);
}
// Formula names of the most recent formula portions, newest first, for Core.formulaChoices. Every
// name ever typed is on file in the feeds themselves, so nothing about this lives in settings and
// the phones and the PC agree without configuration (§8.1).
function recentFormulas() {
  const names = [];
  for (let i = state.events.length - 1; i >= 0 && names.length < 40; i--) {
    const ev = state.events[i];
    if (ev.type !== "feed" || !ev.data || !Array.isArray(ev.data.bottles)) continue;
    for (let j = ev.data.bottles.length - 1; j >= 0; j--) {
      const b = ev.data.bottles[j];
      if (b && b.kind === "formula" && typeof b.formula === "string" && b.formula.trim()) names.push(b.formula.trim());
    }
  }
  return names;
}
const formulaChoices = () => Core.formulaChoices(recentFormulas());
const lastFormula = () => formulaChoices()[0] || null;
// Everyone who has logged or edited anything, plus this PC — the Who chips.
function knownLabels() {
  const seen = new Set();
  if (myLabel()) seen.add(myLabel());
  for (const ev of state.events) {
    if (ev.logged_by) seen.add(ev.logged_by);
    if (ev.edited_by) seen.add(ev.edited_by);
  }
  seen.delete("paper");
  return Array.from(seen);
}
function knownMedicines() {
  const seen = new Set(["Vitamin D"]);
  for (const ev of state.events) if (ev.type === "health" && ev.data && ev.data.medicine) seen.add(ev.data.medicine);
  return Array.from(seen);
}
const running = (type) => ((state.now && state.now.running) || []).filter((ev) => !type || ev.type === type);
const targets = () => (state.now && state.now.targets) || (state.child && state.child.targets) || {};
const byId = (id) => state.events.find((ev) => ev.event_id === id) || null;

// ---------------------------------------------------------------- launcher lifecycle
/* Started from the desktop icon there is no console to close, so this window *is* the app. Telling
   the launcher when it goes lets it stop the server rather than leave one running invisibly and
   holding the port. Minimising changes nothing: the heartbeat keeps going, throttled but far
   inside the launcher's patience.

   A reload fires pagehide too, so the launcher waits a few seconds before acting and any heartbeat
   cancels it. Run under `python app.py` these simply 404 and are ignored. */
function watchWindow() {
  // Quitting from the tray leaves this window on screen with nothing behind it, so the page has
  // to notice. Two missed beats is ten seconds: past a hiccup, short enough to still be useful.
  let missed = 0;
  const beat = () => fetch("/api/heartbeat", { method: "POST" })
    .then(() => { missed = 0; })
    .catch(() => { if (++missed >= 2) showStopped(); });
  beat();
  setInterval(beat, 5000);
  const goodbye = () => {
    try { navigator.sendBeacon("/api/goodbye"); } catch { /* closing anyway */ }
  };
  window.addEventListener("pagehide", goodbye);
  window.addEventListener("beforeunload", goodbye);
}

function showStopped() {
  if (document.getElementById("stopped")) return;
  // The launcher finds the live window by this exact title, so a dead one must stop answering
  // to it — otherwise reopening the app would raise this corpse instead of a working window.
  document.title = "Baby Log (closed)";
  document.body.append(el("div", { id: "stopped", class: "stopped" },
    el("div", { class: "stopped-card" },
      el("div", { class: "stopped-title" }, "The app has been closed"),
      el("div", { class: "stopped-note" },
        "You can close this window. Open it again from the Desktop or the Start menu."))));
}

// ---------------------------------------------------------------- boot and refresh
async function boot() {
  for (const b of document.querySelectorAll(".navbtn")) {
    b.addEventListener("click", () => showView(b.dataset.view));
  }
  document.getElementById("child-chooser").addEventListener("change", async (e) => {
    try {
      await postJSON("/api/settings", { child_id: e.target.value || null });
      await loadConfig(); await refreshAll();
    } catch (x) { showStatus("err", x.message); }
  });
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape" || !state.editor) return;
    if (state.editor.confirm) { state.editor.confirm = false; renderEditor(); }
    else closeEditor();
  });
  loadLastDiaper();
  state.date = todayStr();
  state.catchup.date = todayStr();
  try {
    await loadConfig();
  } catch (e) {
    showStatus("err", `Could not load config: ${e.message}`, true);
  }
  await refreshAll();
  showView("today");
  setInterval(refreshAll, POLL_MS);
  setInterval(tick, 1000);
  watchWindow();
}

async function loadConfig() {
  const c = await api("/api/config");
  state.config = c;
  state.settings = c.settings || {};
  state.child = c.child || null;
  state.children = c.children || [];
}

// Everything the screens draw from, in one round: the Now panel, the day sheet, the journal, the
// pill and the Needs-check count. Called every 30 s and after every write (§6.2).
async function refreshAll() {
  const quiet = (p) => p.catch(() => null);
  const [now, day, evs, health, needs] = await Promise.all([
    quiet(api("/api/now")),
    quiet(api(`/api/day?date=${state.date}`)),
    quiet(api(`/api/events?from=2000-01-01&to=${shiftDay(todayStr(), 1)}`)),
    quiet(api("/api/health")),
    quiet(api("/api/needs-check")),
  ]);
  if (now) state.now = now;
  if (day) state.day = day;
  if (evs) state.events = evs.events || [];
  if (health) state.health = health;
  if (needs) state.needs = needs.events || [];
  renderTopbar();
  renderView();
}

async function afterWrite() {
  await refreshAll();
  if (state.view === "settings") await loadDeleted();
}

// ---------------------------------------------------------------- top bar and views
function renderTopbar() {
  const c = state.child;
  document.getElementById("child-name").textContent = c ? c.name : "Baby Log";
  document.getElementById("child-age").textContent = c && c.born ? Core.ageText(c.born, new Date()) : "";
  const chooser = document.getElementById("child-chooser");
  chooser.hidden = state.children.length < 2;
  if (!chooser.hidden) {
    chooser.replaceChildren(...state.children.map((k) =>
      el("option", { value: k.child_id, selected: c && c.child_id === k.child_id }, k.name)));
  }
  const pill = document.getElementById("journal-pill");
  const h = state.health;
  if (h && h.journal) {
    const n = h.journal.events || 0;
    const newest = h.newest_file_at ? ` · newest ${clockOf(h.newest_file_at)}` : "";
    pill.textContent = `${n} ${n === 1 ? "entry" : "entries"}${newest}`;
    pill.className = "pill pill-ok";
    pill.title = `Journal: ${(state.config && state.config.app_folder) || ""}`
      + (h.journal.unreadable && h.journal.unreadable.length ? ` · ${h.journal.unreadable.length} unreadable` : "");
    if (h.journal.unreadable && h.journal.unreadable.length) pill.className = "pill pill-warn";
  } else if (!h) {
    pill.textContent = "journal?";
    pill.className = "pill pill-warn";
  }
  document.getElementById("label-pill").textContent = myLabel();
  const count = document.getElementById("needs-count");
  count.hidden = !state.needs.length;
  count.textContent = String(state.needs.length);
}

function showView(v) {
  state.view = v;
  for (const b of document.querySelectorAll(".navbtn")) b.classList.toggle("active", b.dataset.view === v);
  for (const name of ["today", "catchup", "trends", "growth", "health", "reports", "settings"]) {
    document.getElementById(`view-${name}`).hidden = name !== v;
  }
  hideStatus();
  renderView();
  if (v === "settings") loadDeleted();
}

function renderView() {
  switch (state.view) {
    case "today": renderToday(); break;
    case "catchup": renderCatchup(); break;
    case "trends": renderTrends(); break;
    case "growth": renderGrowth(); break;
    case "health": renderHealth(); break;
    case "reports": renderReports(); break;
    case "settings": renderSettings(); break;
    default: break;
  }
}

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

// ---------------------------------------------------------------- Today
function renderToday() {
  const first = document.getElementById("firstrun");
  const hasChild = !!state.child;
  first.hidden = hasChild;
  document.getElementById("now").hidden = !hasChild;
  document.getElementById("logbar").hidden = !hasChild;
  document.getElementById("daysheet").hidden = !hasChild;
  if (!hasChild) { renderFirstRun(first); return; }
  renderNow();
  renderLogbar();
  renderDaySheet();
}

function renderFirstRun(card) {
  if (card.dataset.built) return;   // keep what is being typed across polls
  card.dataset.built = "1";
  card.replaceChildren(
    el("div", { class: "h2" }, "Who is this log for?"),
    el("p", {}, "Nothing can be logged until the child exists. The phones pick this up on their first sync."),
    childForm(null, () => { delete card.dataset.built; }));
}

function renderNow() {
  const card = document.getElementById("now");
  const n = state.now;
  if (!n) { card.replaceChildren(el("div", { class: "empty" }, "Loading…")); return; }
  const now = Date.now();
  const kids = [];

  // The since-last tiles: each is the entry, so each opens the entry (§8.3).
  const lf = n.last_feed, ld = n.last_diaper;
  const feedRunning = lf && Core.isRunning(lf);
  kids.push(el("div", { class: "tiles" },
    el("button", { class: "tile tile-feed", type: "button", disabled: !lf,
      onclick: () => lf && openEditor({ event: lf }) },
      el("span", { class: "tile-label" }, "Last feed"),
      lf ? el("span", { class: "tile-big", "data-since": feedRunning ? null : lf.time },
        feedRunning ? "Feeding now" : `${Core.sinceText(now - ms(lf.time))} ago`)
        : el("span", { class: "tile-big" }, "—"),
      el("span", { class: "tile-sub" }, lf ? `${Core.fmtTime(lf.time)} · ${Core.describe(lf, unit())}${lf.logged_by ? ` · ${lf.logged_by}` : ""}` : "No feed yet")),
    el("button", { class: "tile tile-diaper", type: "button", disabled: !ld,
      onclick: () => ld && openEditor({ event: ld }) },
      el("span", { class: "tile-label" }, "Last diaper"),
      ld ? el("span", { class: "tile-big", "data-since": ld.time }, `${Core.sinceText(now - ms(ld.time))} ago`)
        : el("span", { class: "tile-big" }, "—"),
      el("span", { class: "tile-sub" }, ld ? `${Core.fmtTime(ld.time)} · ${Core.describe(ld, unit())}${ld.logged_by ? ` · ${ld.logged_by}` : ""}` : "No diaper yet"))));

  // Every running feed or sleep, whichever device started it.
  const runs = running();
  for (const ev of runs) kids.push(runningCard(ev, now));
  const feeds = runs.filter((ev) => ev.type === "feed");
  if (feeds.length >= 2) {
    kids.push(el("div", { class: "row" },
      el("button", { class: "ghost", type: "button", onclick: () => mergeFeeds(feeds) }, "Merge into one"),
      el("span", { class: "muted small" }, "Two feeds are running — keep the earlier start, add the sides together.")));
  }

  // Hints, never alarms (§8.2).
  const gap = n.usual_gap_s;
  if (gap) {
    let text = `Usually every ${Core.sinceText(gap * 1000)}`;
    if (n.next_feed_at) {
      const late = ms(n.next_feed_at) < now;
      text += ` · next around ${Core.fmtTime(n.next_feed_at)}${late ? " (past)" : ""}`;
    }
    kids.push(el("div", { class: "gapline" }, text));
  } else {
    kids.push(el("div", { class: "gapline" }, "Usual gap shows after three feeds."));
  }

  // Today's totals against the pediatrician's targets, when set.
  const t = n.today || Core.totals(state.events, todayStr(), new Date());
  const tg = targets();
  const total = (count, word, target) => {
    const met = target && count >= target;
    return el("span", { class: `total${met ? " met" : ""}` },
      el("b", {}, String(count)), ` ${word}`, target ? el("span", { class: "of" }, ` / ${target}`) : null);
  };
  kids.push(el("div", { class: "totals" },
    total(t.feeds, t.feeds === 1 ? "feed" : "feeds", tg.feeds_per_day),
    t.bottle_ml ? el("span", { class: "total" }, el("b", {}, amount(t.bottle_ml)), " bottle") : null,
    t.breast_s ? el("span", { class: "total" }, el("b", {}, String(Math.round(t.breast_s / 60))), " min breast") : null,
    total(t.wet, "wet", tg.wet_per_day),
    total(t.dirty, "dirty", tg.dirty_per_day),
    t.sleeps ? el("span", { class: "total" }, el("b", {}, String(t.sleeps)), ` ${t.sleeps === 1 ? "sleep" : "sleeps"} · `, Core.sinceText(t.sleep_s * 1000)) : null,
    t.pumps ? el("span", { class: "total" }, el("b", {}, String(t.pumps)), ` pumped · ${amount(t.pump_ml)}`) : null));
  card.replaceChildren(...kids);
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
  return el("div", { class: `running running-${ev.type}`, onclick: () => openEditor({ event: ev }) },
    el("span", { class: "timer", "data-elapsed": ev.time, "data-style": isFeed ? "clock" : "" },
      isFeed ? elapsedText(now - ms(ev.time)) : Core.sinceText(now - ms(ev.time))),
    el("div", {},
      el("div", { class: "running-title" }, isFeed ? `Feeding since ${Core.fmtTime(ev.time)}` : `Sleeping since ${Core.fmtTime(ev.time)}`),
      el("div", { class: "running-sub" }, sub.join(" · "))),
    el("div", { class: "running-actions", onclick: (e) => e.stopPropagation() },
      isFeed ? el("button", { class: "ghost", type: "button", onclick: () => switchSide(ev) },
        `Switch to ${timer && timer.side === "left" ? "right" : "left"}`) : null,
      el("button", { class: "ghost", type: "button", onclick: () => stopNowFor(ev) }, "Stop")),
    stale ? el("div", { class: "stale", onclick: (e) => e.stopPropagation() },
      isFeed ? "Running for over an hour — forgot to stop it?" : "Running for over six hours — forgot to stop it?",
      el("button", { class: "ghost", type: "button", onclick: () => openEditor({ event: ev, focusEnd: true }) }, "Set end time")) : null);
}

function renderLogbar() {
  const bar = document.getElementById("logbar");
  const moreOpen = bar.dataset.more === "1";
  // Feed always opens a new bottle feed (§6.2); a legacy running timer keeps its card on the Now
  // panel, which is where it is stopped.
  bar.replaceChildren(
    el("button", { class: "logbtn feed", type: "button", onclick: () => openEditor({ type: "feed" }) }, "Feed"),
    el("span", { class: "loggroup" },
      el("button", { class: "logbtn diaper wet", type: "button", onclick: () => quickDiaper(true, false) }, "Wet"),
      el("button", { class: "logbtn diaper dirty", type: "button", onclick: () => quickDiaper(false, true) }, "Dirty"),
      el("button", { class: "logbtn diaper", type: "button", onclick: () => quickDiaper(true, true) }, "Both")),
    el("button", { class: "logbtn", type: "button", onclick: sleepButton },
      running("sleep").length ? "Sleeping…" : "Sleep"),
    el("button", { class: "logbtn", type: "button", onclick: () => openEditor({ type: "pump" }) }, "Pump"),
    el("button", { class: "logbtn", type: "button", onclick: () => openEditor({ type: "growth" }) }, "Weight"),
    moreOpen ? el("span", { class: "more-menu" },
      el("button", { class: "logbtn", type: "button", onclick: () => { bar.dataset.more = ""; openEditor({ type: "health" }); } }, "Health"),
      el("button", { class: "logbtn", type: "button", onclick: () => { bar.dataset.more = ""; openEditor({ type: "note" }); } }, "Note"))
      : el("button", { class: "logbtn", type: "button", onclick: () => { bar.dataset.more = "1"; renderLogbar(); } }, "More ▾"),
    el("button", { class: "logbtn catchup", type: "button", title: "Type in the paper slips: one tap per entry, at the time you write",
      onclick: () => showView("catchup") }, "Catch up"));
}

// The paper sheet: feeding on the left, diapers on the right, everything else below (§6.2).
function renderDaySheet() {
  const card = document.getElementById("daysheet");
  const d = state.day;
  const date = state.date;
  const born = state.child && state.child.born;
  const evs = d && d.date === date ? d.events : Core.onDay(state.events, date);
  const go = async (n) => { state.date = shiftDay(state.date, n); await refreshAll(); };
  const goTo = async (day) => { state.date = day; await refreshAll(); };

  const feeds = evs.filter((ev) => ev.type === "feed");
  const diapers = evs.filter((ev) => ev.type === "diaper");
  const others = evs.filter((ev) => ev.type !== "feed" && ev.type !== "diaper");
  const cell = (ev, cls, ...kids) => el("td", { class: `cell ${cls || ""}`, onclick: () => openEditor({ event: ev }) }, ...kids);
  const noteCell = (ev) => cell(ev, `t-note${isCheck(ev) ? " check" : ""}`, ev.note || "");
  const byCell = (ev) => cell(ev, "t-by", ev.logged_by || "");

  const feedRow = (ev) => {
    const br = ev.data.breast || {};
    const run = Core.isRunning(ev);
    let breast = "";
    const s = Core.breastSeconds(ev, new Date());
    if (s || br.left_s != null || br.right_s != null) {
      breast = `${br.approx ? "~" : ""}${Math.round(s / 60)} min`;
      if (br.left_s != null || br.right_s != null) breast += ` (L ${Math.round((br.left_s || 0) / 60)} / R ${Math.round((br.right_s || 0) / 60)})`;
    }
    const bottles = (ev.data.bottles || []).map((b) => `${amount(b.ml)} ${b.kind === "formula" ? (b.formula || "formula") : "breast milk"}`).join(" + ");
    const made = ev.data.made_ml != null || ev.data.leftover_ml != null
      ? `${ev.data.made_ml != null ? amount(ev.data.made_ml) : "—"} / ${ev.data.leftover_ml != null ? amount(ev.data.leftover_ml) : "—"}` : "";
    // A bottle feed's end is its start (the editor has no End for feeds), so only a real span shows.
    const span = ev.end && ms(ev.end) - ms(ev.time) >= MIN ? `–${Core.fmtTime(ev.end)}` : "";
    return el("tr", { class: run ? "running-row" : "" },
      cell(ev, "t-time", Core.fmtTime(ev.time), run ? " ▸" : span),
      cell(ev, "", breast), cell(ev, "", bottles), cell(ev, "", made), byCell(ev), noteCell(ev));
  };
  const glyph = (on, cls, color) => el("span", { class: `glyph ${on ? cls : "off"}`, style: on && color ? `color:${color}` : null }, on ? "☑" : "☐");
  const diaperRow = (ev) => {
    const dd = ev.data;
    const extra = [dd.color, dd.texture, dd.size].filter(Boolean).map((x) => x.replace(/_/g, " "));
    if (dd.rash) extra.push("rash");
    if (dd.blowout) extra.push("blowout");
    return el("tr", {},
      cell(ev, "t-time", Core.fmtTime(ev.time)),
      cell(ev, "", glyph(dd.wet, "wet")),
      cell(ev, "", glyph(dd.dirty, "dirty", STOOL[dd.color] || "var(--dirty)")),
      cell(ev, "", extra.join(", ")), byCell(ev), noteCell(ev));
  };
  const table = (heads, rows, empty) => el("table", {},
    el("thead", {}, el("tr", {}, ...heads.map((h) => el("th", {}, h)))),
    rows.length ? el("tbody", {}, ...rows) : el("tbody", {}, el("tr", {}, el("td", { colspan: String(heads.length), class: "empty" }, empty))));

  card.replaceChildren(...[
    el("div", { class: "sheet-head" },
      el("div", { class: "sheet-title" }, `${Core.fmtDay(date)}${born ? ` · day ${Core.dayNumber(born, date)}` : ""}`),
      el("span", { class: "muted small" }, date === todayStr() ? "today" : ""),
      el("div", { class: "sheet-nav" },
        el("button", { class: "ghost", type: "button", disabled: d && d.date === date && !d.has_prev, onclick: () => go(-1) }, "‹ prev"),
        date !== todayStr() ? el("button", { class: "ghost", type: "button", onclick: () => goTo(todayStr()) }, "Today") : null,
        el("button", { class: "ghost", type: "button", disabled: date >= todayStr() && !(d && d.has_next), onclick: () => go(1) }, "next ›"))),
    el("div", { class: "sheet sheet-cols" },
      el("div", { class: "sheet-col-feed" },
        el("div", { class: "sheet-col-h" }, "Feeding"),
        table(["Time", "Breast", "Bottle", "Made / left", "By", "Note"], feeds.map(feedRow), "No feeds")),
      el("div", { class: "sheet-col-diaper" },
        el("div", { class: "sheet-col-h" }, "Diapers"),
        table(["Time", "Wet", "Dirty", "Colour / texture", "By", "Note"], diapers.map(diaperRow), "No diapers"))),
    others.length ? el("div", { class: "other" },
      el("div", { class: "h3" }, "Other"),
      ...others.map((ev) => el("div", { class: "other-row", onclick: () => openEditor({ event: ev }) },
        el("span", { class: "other-type" }, TYPE_LABEL[ev.type] || ev.type),
        el("span", { class: "other-time" }, Core.fmtTime(ev.time), ev.end ? `–${Core.fmtTime(ev.end)}` : ""),
        el("span", {}, Core.describe(ev, unit())),
        el("span", { class: "t-by muted small" }, ev.logged_by || ""),
        ev.note ? el("span", { class: `other-note${isCheck(ev) ? " check" : ""}` }, ev.note) : null))) : null]
    .filter(Boolean));   // replaceChildren(null) would print the word "null" under the sheet
}

// ---------------------------------------------------------------- quick actions from the log bar
/* One write from the Today screen at a time. The second click of a double-click lands while the
   first click's POST is still in flight and nothing on screen has changed yet: the 2-minute
   diaper rule cannot catch it (the first diaper is not on file), `running()` still says no sleep,
   and a second Switch or Stop writes a redundant revision. Set before the POST, cleared in finally. */
let writing = false;

async function sleepButton() {
  const run = running("sleep");
  if (run.length) { openEditor({ event: run[0] }); return; }
  if (writing) return;
  writing = true;
  const time = nowIso();
  try {
    const r = await postJSON("/api/event", { type: "sleep", time, end: null, data: { timer: { running: true } }, note: "", logged_by: myLabel() });
    showToast(`Sleeping since ${Core.fmtTime(time)}`, [
      { label: "Undo", fn: () => undoNew(r.event) },
      { label: "Edit", fn: () => openEditor({ event: r.event }) }]);
    await afterWrite();
  } catch (e) { showStatus("err", e.message); }
  finally { writing = false; }
}

// One click, one diaper — unless the last one from this PC was under two minutes ago, in which
// case it is probably the same diaper and the editor of that one opens instead (§6.2).
async function quickDiaper(wet, dirty) {
  const last = state.lastDiaper;
  if (last && Date.now() - last.ms < 2 * MIN) {
    const ev = byId(last.event_id);
    if (ev && ev.type === "diaper") { openEditor({ event: ev, sameAs: { wet, dirty } }); return; }
  }
  await writeDiaper(wet, dirty);
}
async function writeDiaper(wet, dirty) {
  if (writing) return;
  writing = true;
  const time = nowIso();
  try {
    const r = await postJSON("/api/event", { type: "diaper", time, end: null, data: { wet, dirty }, note: "", logged_by: myLabel() });
    saveLastDiaper({ event_id: r.event.event_id, ms: Date.now() });
    showToast(`${Core.describe(r.event, unit())} · ${Core.fmtTime(time)}`, [
      { label: "Undo", fn: () => undoNew(r.event) },
      { label: "Edit", fn: () => openEditor({ event: r.event }) }]);
    await afterWrite();
  } catch (e) { showStatus("err", e.message); }
  finally { writing = false; }
}
async function undoNew(ev) {
  try {
    await deleteJSON(`/api/event/${ev.event_id}`, { reason: "undo" });
    if (state.lastDiaper && state.lastDiaper.event_id === ev.event_id) saveLastDiaper(null);
    await afterWrite();
  } catch (e) { showStatus("err", e.message); }
}

// A revision: the client-owned fields of the record with a patch over them (§6.1).
function revise(ev, patch) {
  return postJSON("/api/event", Object.assign({
    event_id: ev.event_id, child_id: ev.child_id, type: ev.type, time: ev.time, end: ev.end,
    data: ev.data, note: ev.note || "",
  }, patch));
}

/* The record on file now. The PC's copy of an entry is a poll old at best, and a phone's revision
   reaches it only when OneDrive delivers the file, so a Switch, Stop or Save that starts from the
   held copy would write over what the phone did meanwhile — §3.4 makes the higher revision win,
   and nothing would say so. Every revision of an existing entry starts from what this returns. */
async function latest(eventId) {
  return (await api(`/api/event/${eventId}`)).event;
}
// True when the record on file is not the one the click was made on and this PC did not write it:
// a phone's revision, or a tombstone from anywhere (a revision over a tombstone would quietly bring
// the entry back). This PC's own newer write is simply the base to go on from.
function movedElsewhere(cur, held) {
  if (cur.deleted && !(held && held.deleted)) return true;
  if (cur.device === "pc") return false;
  return !held || cur.revision !== held.revision || cur.created_at !== held.created_at;
}
// Whose change this was, for the "Updated from …" line — the phone's wording (docs/app.js).
function whose(rec) {
  if (rec.entered_from === "paper") return "the paper sheet";
  if (rec.device === "pc") return "this PC";
  return `${rec.edited_by || rec.logged_by || "the other"}'s phone`;
}
const movedText = (rec) => `${rec.deleted ? "Deleted on" : "Updated from"} ${whose(rec)} — look again`;
// The held copy was stale: show what is on file now — in the open editor, or on the Now panel —
// with a line saying whose change it was, instead of writing over it.
async function lookAgain(rec) {
  const e = state.editor;
  if (e && e.draft.event_id === rec.event_id) {
    openEditor({ event: rec });
    setMsg(movedText(rec), "warn");
  } else {
    showToast(movedText(rec));
  }
  await refreshAll();
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

// Switch and Stop fold the timer of the record on file, not the card's copy; a card that is no
// longer running (stopped from anywhere) has nothing to fold.
async function switchSide(ev) {
  if (writing) return;
  writing = true;
  try {
    const held = await latest(ev.event_id);
    if (movedElsewhere(held, ev) || !Core.isRunning(held)) { await lookAgain(held); return; }
    const data = foldTimer(clone(held.data), Date.now());
    const was = (held.data.timer && held.data.timer.side) || data.breast.last_side;
    data.timer = { side: was === "left" ? "right" : "left", side_started: nowIso() };
    await revise(held, { data, end: null });
    await afterWrite();
  } catch (e) { showStatus("err", e.message); }
  finally { writing = false; }
}

async function stopNowFor(ev) {
  if (writing) return;
  writing = true;
  try {
    const held = await latest(ev.event_id);
    if (movedElsewhere(held, ev) || !Core.isRunning(held)) { await lookAgain(held); return; }
    const end = nowIso();
    const data = held.type === "feed" ? foldTimer(clone(held.data), ms(end)) : Object.assign(clone(held.data), { timer: null });
    const r = await revise(held, { data, end });
    showToast(`${TYPE_LABEL[held.type]} stopped · ${Core.fmtTime(end)}`, [{ label: "Edit", fn: () => openEditor({ event: r.event }) }]);
    await afterWrite();
  } catch (e) { showStatus("err", e.message); }
  finally { writing = false; }
}

// Two running feeds become one: the earlier start, the sides added, the later one tombstoned.
async function mergeFeeds(feeds) {
  if (writing) return;
  writing = true;
  try {
    const fresh = [];
    for (const f of feeds) {
      const cur = await latest(f.event_id);
      if (movedElsewhere(cur, f) || !Core.isRunning(cur)) { await lookAgain(cur); return; }
      fresh.push(cur);
    }
    const sorted = fresh.sort((a, b) => ms(a.time) - ms(b.time));
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
    await revise(keep, { data: a, end: null, note });
    await deleteJSON(`/api/event/${drop.event_id}`, { reason: `merged into ${keep.event_id}` });
    showToast(`Merged into the ${Core.fmtTime(keep.time)} feed`);
    await afterWrite();
  } catch (e) { showStatus("err", e.message); }
  finally { writing = false; }
}

// ---------------------------------------------------------------- the editor
function draftFrom(ev) {
  return { event_id: ev.event_id, child_id: ev.child_id, type: ev.type, time: ev.time, end: ev.end,
    data: clone(ev.data || Core.defaults(ev.type)), note: ev.note || "", logged_by: ev.logged_by || myLabel() };
}

/* opts: {event} for an existing entry, or {type, data?, time?} for a new one. `sameAs` is the
   2-minute diaper rule, `focusEnd` the stale-timer "Set end time". */
function openEditor(opts) {
  const ev = opts.event || null;
  let draft;
  if (ev) {
    draft = draftFrom(ev);
    if (opts.sameAs) {
      draft.data.wet = draft.data.wet || opts.sameAs.wet;
      draft.data.dirty = draft.data.dirty || opts.sameAs.dirty;
    }
  } else {
    draft = { event_id: null, child_id: state.child ? state.child.child_id : null, type: opts.type,
      time: opts.time || nowIso(), end: null, data: Object.assign(Core.defaults(opts.type), opts.data || {}),
      note: "", logged_by: myLabel() };
    // A new feed opens on one empty formula portion, so the formula chips are in view before the
    // first tap; an empty portion is dropped on Save.
    if (draft.type === "feed" && !draft.data.bottles.length) draft.data.bottles.push({ kind: "formula", ml: 0, formula: lastFormula() });
  }
  // A stored portion counts as typed: §8.1 keeps it unless the user touches it, so made / leftover
  // may only fill in a portion this editor created itself.
  const bottles = draft.data.bottles || [];
  // Records written before formula names existed have no `formula` key on their portions;
  // the editor treats that as null (both validators fill the default on Save anyway).
  for (const b of bottles) if (b && b.formula === undefined) b.formula = null;
  state.editor = { draft, event: ev, history: null, msg: null, msgKind: "err", confirm: false,
    unusualOk: false, sameAs: opts.sameAs || null, focusEnd: !!opts.focusEnd,
    portionsTyped: bottles.some((b) => b && b.ml > 0), whoOther: false, formulaOther: {}, saving: false };
  if (ev) {
    api(`/api/event/${ev.event_id}`).then((r) => {
      if (state.editor && state.editor.event === ev) { state.editor.history = r.history || []; renderHistory(); }
    }).catch(() => { /* the history is a nicety */ });
  }
  renderEditor();
}

function closeEditor() {
  state.editor = null;
  document.getElementById("modal").hidden = true;
}

// The buttons that write go grey while a write is in flight, so a second click has nothing to
// hit; toggled in place because a full re-render would drop a half-typed field.
function setBusy(e, on) {
  e.saving = on;
  if (state.editor !== e) return;
  for (const b of document.querySelectorAll("#modal-card [data-busy]")) b.disabled = on;
}

function setMsg(text, kind = "err") {
  const e = state.editor;
  if (!e) return;
  e.msg = text; e.msgKind = kind;
  renderMsg();
}

function renderMsg() {
  const box = document.getElementById("ed-msg");
  const e = state.editor;
  if (!box || !e) return;
  if (!e.msg) { box.hidden = true; box.replaceChildren(); return; }
  box.hidden = false;
  box.className = `ed-msg ${e.msgKind}`;
  box.replaceChildren(document.createTextNode(e.msg));
  if (e.msgKind === "ask") {
    box.append(el("button", { class: "ghost", type: "button",
      onclick: () => { e.unusualOk = true; e.msg = null; saveEditor(); } }, "Save anyway"));
  }
}

function renderHistory() {
  const box = document.getElementById("ed-history");
  const e = state.editor;
  if (!box || !e || !e.history) return;
  box.replaceChildren(el("details", { class: "history" },
    el("summary", {}, `History · ${e.history.length} ${e.history.length === 1 ? "revision" : "revisions"}`),
    el("ul", {}, ...e.history.map((h) => el("li", {},
      `r${h.revision} · ${clockOf(h.created_at)} ${Core.fmtDay(Core.isoLocal(new Date(ms(h.created_at))))} · `
      + `${h.edited_by || h.logged_by || h.device || "?"} (${h.entered_from || h.device || "?"})`
      + `${h.deleted ? ` · deleted${h.reason ? `: ${h.reason}` : ""}` : ""}`)))));
}

function renderEditor() {
  const e = state.editor;
  const modal = document.getElementById("modal");
  const card = document.getElementById("modal-card");
  if (!e) { modal.hidden = true; return; }
  const d = e.draft;
  const isNew = !d.event_id;
  const isRunning = TIMED.includes(d.type) && d.end === null && !isNew && d.type !== "pump"
    && !!(d.data && d.data.timer);
  card.className = `modal-card ed-type-${d.type}`;

  const title = isNew ? `New ${TYPE_LABEL[d.type].toLowerCase()}`
    : `${TYPE_LABEL[d.type]} · ${Core.fmtDateTime(d.time)}${isRunning ? " · running" : ""}`;
  const kids = [
    el("div", { class: "ed-head" },
      el("div", { class: "ed-title", id: "ed-title" }, title),
      el("button", { class: "ed-close", type: "button", "aria-label": "Close", onclick: closeEditor }, "×")),
  ];

  if (e.sameAs) {
    const ev = e.event;
    kids.push(el("div", { class: "ed-hint" },
      `Same as the ${Core.fmtTime(ev.time)} one? Save adds to it · Log another adds a new one`,
      el("button", { class: "ghost", type: "button", onclick: () => { closeEditor(); writeDiaper(e.sameAs.wet, e.sameAs.dirty); } }, "Log another")));
  }
  if (e.event && isCheck(e.event)) {
    kids.push(el("div", { class: "ed-hint" }, "From the paper sheet, marked for checking — correct it and remove the “Check:” from the note."));
  }

  // -- common: Start, the shift chips, End, Who
  const timeInput = el("input", { type: "datetime-local", value: dtValue(d.time), step: "60",
    onchange: (x) => { const v = dtParse(x.target.value); if (v) { d.time = v; whenLabel.textContent = Core.fmtDateTime(d.time); } } });
  const whenLabel = el("span", { class: "ed-when" }, Core.fmtDateTime(d.time));
  const shift = (n) => {
    d.time = Core.isoLocal(new Date(ms(d.time) - n * MIN));
    timeInput.value = dtValue(d.time);
    whenLabel.textContent = Core.fmtDateTime(d.time);
  };
  kids.push(el("div", { class: "ed-row" },
    el("span", { class: "lbl" }, "Start"), timeInput,
    el("span", { class: "chips" },
      el("button", { class: "chip", type: "button", onclick: () => shift(5) }, "−5"),
      el("button", { class: "chip", type: "button", onclick: () => shift(15) }, "−15"),
      el("button", { class: "chip", type: "button", onclick: () => shift(30) }, "−30 min")),
    whenLabel));

  // End is hidden for feeds — a bottle has no useful end (§6.2). The one exception is a feed that
  // still carries a running timer from before 27 Sep 2026: the stale-timer card's "Set end time"
  // lands here and needs the control to stop it.
  if (TIMED.includes(d.type) && (d.type !== "feed" || isRunning)) {
    const endInput = el("input", { type: "datetime-local", value: dtValue(d.end), step: "60", id: "ed-end",
      onchange: (x) => { d.end = x.target.value ? dtParse(x.target.value) : null; } });
    kids.push(el("div", { class: "ed-row" },
      el("span", { class: "lbl" }, "End"), endInput,
      el("button", { class: "chip", type: "button", onclick: () => { d.end = nowIso(); endInput.value = dtValue(d.end); } }, "now"),
      d.end === null ? el("span", { class: "muted small" }, d.type === "pump" ? "" : (isNew ? "blank = still going" : "running")) : null));
  }

  const labels = knownLabels();
  if (d.logged_by && !labels.includes(d.logged_by)) labels.push(d.logged_by);
  const whoRow = el("div", { class: "ed-row" }, el("span", { class: "lbl" }, "Who"),
    el("span", { class: "chips" },
      ...labels.map((l) => el("button", { class: `chip${d.logged_by === l ? " active" : ""}`, type: "button",
        onclick: () => { d.logged_by = l; renderEditor(); } }, l)),
      e.whoOther ? el("input", { type: "text", placeholder: "name", value: labels.includes(d.logged_by) ? "" : d.logged_by,
        oninput: (x) => { d.logged_by = x.target.value; } })
        : el("button", { class: "chip", type: "button", onclick: () => { e.whoOther = true; renderEditor(); } }, "Other…")));
  kids.push(whoRow);

  // -- the type's own controls
  const section = { feed: feedSection, diaper: diaperSection, sleep: sleepSection, pump: pumpSection,
    growth: growthSection, health: healthSection, note: noteSection }[d.type];
  kids.push(el("div", { class: "ed-section" }, ...section(d, e)));

  // -- note, type, child
  kids.push(el("div", { class: "ed-section" },
    el("label", { class: "field wide" }, el("span", {}, "Note"),
      el("textarea", { rows: "2", oninput: (x) => { d.note = x.target.value; } }, d.note)),
    el("div", { class: "ed-row" },
      el("label", { class: "field" }, el("span", {}, "Change type…"),
        el("select", { onchange: (x) => changeType(x.target.value) },
          ...Core.TYPES.map((t) => el("option", { value: t, selected: t === d.type }, TYPE_LABEL[t])))),
      state.children.length >= 2 ? el("label", { class: "field" }, el("span", {}, "Child"),
        el("select", { onchange: (x) => { d.child_id = x.target.value; } },
          ...state.children.map((k) => el("option", { value: k.child_id, selected: k.child_id === d.child_id }, k.name)))) : null)));

  kids.push(el("div", { class: "ed-msg", id: "ed-msg", hidden: true }));
  if (e.confirm) {
    kids.push(el("div", { class: "ed-confirm" },
      `Delete ${TYPE_LABEL[d.type].toLowerCase()} ${Core.fmtTime(d.time)}?`,
      el("button", { class: "ghost", type: "button", onclick: () => { e.confirm = false; renderEditor(); } }, "Keep"),
      el("button", { class: "ghost danger", type: "button", "data-busy": "1", disabled: e.saving, onclick: deleteEntry }, "Delete")));
  }

  kids.push(el("div", { class: "ed-foot" },
    !isNew ? el("button", { class: "ghost danger", type: "button", "data-busy": "1", disabled: e.saving, onclick: () => { e.confirm = true; renderEditor(); } }, "Delete") : null,
    el("span", { class: "spacer" }),
    el("button", { class: "ghost", type: "button", onclick: closeEditor }, "Cancel"),
    el("button", { class: `primary${d.type === "feed" ? " feed" : ""}`, type: "button", "data-busy": "1", disabled: e.saving, onclick: saveEditor }, "Save")));
  kids.push(el("div", { id: "ed-history" }));

  card.replaceChildren(...kids);
  modal.hidden = false;
  renderMsg();
  renderHistory();
  if (e.focusEnd) {
    e.focusEnd = false;
    const endInput = document.getElementById("ed-end");
    if (endInput) endInput.focus();
  }
}

function changeType(type) {
  const e = state.editor, d = e.draft;
  if (type === d.type) return;
  d.type = type;
  d.data = Core.defaults(type);
  if (!TIMED.includes(type)) d.end = null;
  e.unusualOk = false;
  e.portionsTyped = false;   // the defaults hold no portion for made / leftover to keep off
  renderEditor();
}

// An amount control: −/+ by the step, typed in the display unit, stored as whole ml. The stored
// value is untouched until the user changes it, so oz mode never nudges a 22 ml feed (§8.1).
function amountControl(get, set, opts = {}) {
  const u = unit();
  const input = el("input", { type: "number", inputmode: u === "oz" ? "decimal" : "numeric", min: "0",
    step: u === "oz" ? "0.25" : "1", value: get() == null ? "" : String(Core.toUnit(get(), u)),
    placeholder: opts.placeholder || "",
    oninput: (x) => { set(x.target.value === "" ? null : Core.fromUnit(x.target.value, u)); } });
  const nudge = (dir) => {
    const cur = get() == null ? 0 : get();
    const v = Math.max(0, cur + dir * stepMl());
    set(v); input.value = String(Core.toUnit(v, u));
  };
  const box = el("span", { class: "amt" },
    el("button", { type: "button", "aria-label": "less", onclick: () => nudge(-1) }, "−"),
    input,
    el("button", { type: "button", "aria-label": "more", onclick: () => nudge(1) }, "+"));
  box.refresh = () => { input.value = get() == null ? "" : String(Core.toUnit(get(), u)); };
  return box;
}

// The range control beside the quick chips (§8.1): from / to / step in ml, saved to settings the
// moment a field changes so the range moves up the week his feeds do. `onSaved` redraws the chips.
function rangeControl(onSaved) {
  const cur = (key) => { const v = (state.settings || {})[key]; return v == null ? "" : String(v); };
  const num = (key, label) => {
    const input = el("input", { type: "number", inputmode: "numeric", min: "1", step: "1", "aria-label": `range ${label}`, value: cur(key) });
    input.addEventListener("change", async () => {
      const v = input.value === "" ? null : Number(input.value);
      if (v !== null && !(Number.isFinite(v) && v >= 1)) { input.value = cur(key); return; }
      try {
        const r = await postJSON("/api/settings", { [key]: v });
        state.settings = r.settings || Object.assign({}, state.settings, { [key]: v });
        syncSettingsRange();
        onSaved();
      } catch (x) { showStatus("err", x.message); }
    });
    return el("label", { class: "range-field" }, el("span", {}, label), input);
  };
  return el("span", { class: "range-ctl", title: "The quick amounts: every step from the first to the last, in ml" },
    el("span", { class: "muted small" }, "range"), num("quick_from", "from"), num("quick_to", "to"), num("quick_step", "by"),
    el("span", { class: "muted small" }, "ml"));
}

// The quick-amount chips: Same as last, then the amounts of §8.1, in the display unit.
function quickChips(onPick, excludeId) {
  const lastBottle = state.events.filter((ev) => ev.type === "feed" && Core.bottleMl(ev) > 0 && ev.event_id !== excludeId).pop();
  return [
    lastBottle ? el("button", { class: "chip feed", type: "button", onclick: () => onPick(Core.bottleMl(lastBottle)) },
      `Same as last · ${amount(Core.bottleMl(lastBottle))}`) : null,
    ...quickAmounts().map((mlv) => el("button", { class: "chip", type: "button", onclick: () => onPick(mlv) }, amount(mlv))),
  ];
}

function feedSection(d, e) {
  const br = d.data.breast || {};
  const out = [];

  // -- breast minutes from the paper sheet (or the timer era): read-only, never edited or cleared
  const breastS = br.total_s != null ? br.total_s : (br.left_s != null || br.right_s != null ? (br.left_s || 0) + (br.right_s || 0) : null);
  if (breastS != null && breastS > 0) {
    const sides = br.left_s != null || br.right_s != null ? ` (L ${Math.round((br.left_s || 0) / 60)} / R ${Math.round((br.right_s || 0) / 60)})` : "";
    const from = e.event && e.event.entered_from === "paper" ? ", from the paper sheet" : "";
    out.push(el("div", { class: "breast-line muted small" }, `${br.approx ? "~" : ""}${Math.round(breastS / 60)} min breast${sides}${from}`));
  }

  // -- bottle portions, each with its kind, its amount and (for formula) the formula chips
  out.push(el("div", { class: "h3" }, "Bottle"));
  const portions = el("div", {});
  const choices = formulaChoices();
  const formulaRow = (b, i) => {
    const names = choices.slice();
    if (b.formula && !names.includes(b.formula)) names.unshift(b.formula);
    const other = !!e.formulaOther[i];
    return el("div", { class: "chips formula-chips" },
      ...names.map((name) => el("button", { class: `chip feed${!other && b.formula === name ? " active" : ""}`, type: "button",
        onclick: () => { b.formula = name; delete e.formulaOther[i]; drawPortions(); } }, name)),
      other ? el("input", { type: "text", class: "formula-other", placeholder: "formula name", value: names.includes(b.formula) ? "" : (b.formula || ""),
        oninput: (x) => { b.formula = x.target.value.trim() || null; } })
        : el("button", { class: "chip", type: "button", onclick: () => { e.formulaOther[i] = true; drawPortions(); focusOther(i); } }, "Other…"));
  };
  const focusOther = (i) => {
    const box = portions.querySelectorAll(".portion-box")[i];
    const input = box && box.querySelector(".formula-other");
    if (input) input.focus();
  };
  const drawPortions = () => {
    portions.replaceChildren(...d.data.bottles.map((b, i) => {
      const ctl = amountControl(() => b.ml, (v) => { b.ml = v == null ? 0 : v; e.portionsTyped = true; });
      return el("div", { class: "portion-box" },
        el("div", { class: "portion" },
          el("button", { class: `toggle${b.kind === "formula" ? " on" : ""}`, type: "button",
            onclick: () => {
              // Breast milk has no formula name; back on formula the newest name is preselected.
              b.kind = b.kind === "formula" ? "breast_milk" : "formula";
              b.formula = b.kind === "formula" ? (b.formula || choices[0] || null) : null;
              delete e.formulaOther[i];
              drawPortions();
            } },
            b.kind === "formula" ? "Formula" : "Breast milk"),
          ctl, el("span", { class: "unit" }, unit()),
          el("button", { class: "remove", type: "button", "aria-label": "Remove portion",
            onclick: () => { d.data.bottles.splice(i, 1); delete e.formulaOther[i]; e.portionsTyped = true; drawPortions(); } }, "×")),
        b.kind === "formula" ? formulaRow(b, i) : null);
    }));
  };
  drawPortions();
  out.push(portions);
  const newPortion = (mlv) => ({ kind: "formula", ml: mlv, formula: choices[0] || null });
  const setLast = (mlv) => {
    if (!d.data.bottles.length) d.data.bottles.push(newPortion(mlv));
    else d.data.bottles[d.data.bottles.length - 1].ml = mlv;
    e.portionsTyped = true;
    drawPortions();
  };
  const chips = el("span", { class: "chips" });
  const drawChips = () => chips.replaceChildren(...quickChips(setLast, d.event_id).filter(Boolean));
  drawChips();
  const rangeMode = ((state.settings || {}).quick_mode || "range") === "range";
  out.push(el("div", { class: "quick-row" }, chips, rangeMode ? rangeControl(drawChips) : null,
    el("button", { class: "chip", type: "button", onclick: () => {
      const last = d.data.bottles[d.data.bottles.length - 1];
      d.data.bottles.push(last ? { kind: last.kind, ml: 0, formula: last.kind === "formula" ? last.formula : null } : newPortion(0));
      e.portionsTyped = true; drawPortions();
    } }, "Another portion")));

  // -- made / leftover: with both set and no portion typed, one formula portion fills itself in
  const autoPortion = () => {
    if (d.data.made_ml == null || d.data.leftover_ml == null || e.portionsTyped) return;
    const ml = d.data.made_ml - d.data.leftover_ml;
    if (ml <= 0) return;
    if (!d.data.bottles.length) d.data.bottles.push(newPortion(ml));
    else if (d.data.bottles.length === 1) d.data.bottles[0].ml = ml;
    drawPortions();
  };
  out.push(el("div", { class: "portion", style: "margin-top:10px" },
    el("span", { class: "muted small" }, "Made"),
    amountControl(() => d.data.made_ml, (v) => { d.data.made_ml = v; autoPortion(); }),
    el("span", { class: "muted small" }, "leftover"),
    amountControl(() => d.data.leftover_ml, (v) => { d.data.leftover_ml = v; autoPortion(); }),
    el("span", { class: "unit" }, unit())));
  return out;
}

// A timer action writes at once and the editor re-reads the saved record — a Switch is a
// revision, not a draft (§3.2).
async function writeFromEditor(patch) {
  const e = state.editor, d = e.draft;
  if (e.saving) return;   // the second click of a double-click: the first is still writing
  let data;
  try { data = Core.validate(d.type, patch.data || d.data); } catch (x) { setMsg(x.message); return; }
  const body = { child_id: d.child_id, type: d.type, time: d.time, end: patch.end === undefined ? d.end : patch.end,
    data, note: d.note, logged_by: d.logged_by };
  if (d.event_id) body.event_id = d.event_id;
  setBusy(e, true);
  try {
    if (d.event_id) {
      const cur = await latest(d.event_id);
      if (movedElsewhere(cur, e.event)) { await lookAgain(cur); return; }
    }
    const r = await postJSON("/api/event", body);
    e.event = r.event;
    e.draft = draftFrom(r.event);
    e.msg = null;
    renderEditor();
    api(`/api/event/${r.event.event_id}`).then((h) => {
      if (state.editor === e) { e.history = h.history || []; renderHistory(); }
    }).catch(() => {});
    await afterWrite();
  } catch (x) { setMsg(x.message); }
  finally { setBusy(e, false); }
}

function diaperSection(d) {
  const dd = d.data;
  const out = [];
  const flag = (key, cls, text) => el("button", { class: `toggle ${cls}${dd[key] ? " on" : ""}`, type: "button",
    onclick: () => { dd[key] = !dd[key]; renderEditor(); } }, text);
  out.push(el("div", { class: "row", style: "margin-top:0" }, flag("wet", "wet", "Wet"), flag("dirty", "dirty", "Dirty"),
    flag("rash", "", "Rash"), flag("blowout", "", "Blowout")));
  const enumRow = (label, key, values, swatch) => el("div", { class: "ed-row" }, el("span", { class: "lbl" }, label),
    el("span", { class: "chips" }, ...values.map((v) => el("button", { class: `chip diaper${dd[key] === v ? " active" : ""}`, type: "button",
      onclick: () => { dd[key] = dd[key] === v ? null : v; renderEditor(); } },
      swatch ? el("i", { class: "swatch", style: `background:${STOOL[v]}` }) : null, v.replace(/_/g, " ")))));
  out.push(enumRow("Colour", "color", Core.ENUMS.color, true));
  out.push(enumRow("Texture", "texture", Core.ENUMS.texture));
  out.push(enumRow("Size", "size", Core.ENUMS.size));
  return out;
}

function sleepSection(d, e) {
  const out = [];
  const run = d.end === null && d.event_id;
  if (run) out.push(el("div", { class: "row", style: "margin-top:0" },
    el("span", { class: "timer", "data-elapsed": d.time }, Core.sinceText(Date.now() - ms(d.time))),
    el("button", { class: "primary", type: "button", "data-busy": "1", disabled: e.saving,
      onclick: () => writeFromEditor({ data: Object.assign(clone(d.data), { timer: null }), end: nowIso() }) }, "Stop now")));
  out.push(el("label", { class: "field" }, el("span", {}, "Where"),
    el("input", { type: "text", value: d.data.where || "", placeholder: "bassinet, arms, car seat…",
      oninput: (x) => { d.data.where = x.target.value || null; } })));
  return out;
}

function pumpSection(d) {
  const num = (key, label, opts) => el("label", { class: "field narrow" }, el("span", {}, label),
    el("input", Object.assign({ type: "number", inputmode: "numeric", min: "0", step: "1",
      value: d.data[key] == null ? "" : String(d.data[key]),
      oninput: (x) => { d.data[key] = x.target.value === "" ? null : Number(x.target.value); } }, opts || {})));
  return [el("div", { class: "form" },
    el("div", { class: "field" }, el("span", {}, `Left (${unit()})`), amountControl(() => d.data.left_ml, (v) => { d.data.left_ml = v; })),
    el("div", { class: "field" }, el("span", {}, `Right (${unit()})`), amountControl(() => d.data.right_ml, (v) => { d.data.right_ml = v; })),
    num("minutes", "Minutes"))];
}

function growthSection(d) {
  const num = (key, label, step, mode) => el("label", { class: "field narrow" }, el("span", {}, label),
    el("input", { type: "number", inputmode: mode, min: "0", step,
      value: d.data[key] == null ? "" : String(d.data[key]),
      oninput: (x) => { d.data[key] = x.target.value === "" ? null : Number(x.target.value); } }));
  return [el("div", { class: "form" },
    num("weight_g", "Weight (g)", "1", "numeric"),
    num("length_cm", "Length (cm)", "0.1", "decimal"),
    num("head_cm", "Head (cm)", "0.1", "decimal"))];
}

function healthSection(d) {
  const text = (key, label, list) => el("label", { class: "field" }, el("span", {}, label),
    el("input", { type: "text", value: d.data[key] || "", list,
      oninput: (x) => { d.data[key] = x.target.value || null; } }));
  return [
    el("datalist", { id: "ed-meds" }, ...knownMedicines().map((m) => el("option", { value: m }))),
    el("div", { class: "chips", style: "margin-bottom:10px" },
      ...knownMedicines().map((m) => el("button", { class: `chip${d.data.medicine === m ? " active" : ""}`, type: "button",
        onclick: () => { d.data.medicine = m; renderEditor(); } }, m))),
    el("div", { class: "form" },
      text("medicine", "Medicine", "ed-meds"),
      text("dose", "Dose"),
      el("label", { class: "field narrow" }, el("span", {}, "Temp (°C)"),
        el("input", { type: "number", inputmode: "decimal", min: "0", step: "0.1",
          value: d.data.temp_c == null ? "" : String(d.data.temp_c),
          oninput: (x) => { d.data.temp_c = x.target.value === "" ? null : Number(x.target.value); } })),
      text("symptom", "Symptom"))];
}

function noteSection(d) {
  return [el("label", { class: "row", style: "margin-top:0; gap:8px" },
    el("input", { type: "checkbox", checked: d.data.milestone, onchange: (x) => { d.data.milestone = x.target.checked; } }),
    "Milestone")];
}

// The in-page refusals (§6.2): born..now+10 min, End after Start, made over leftover.
function validateDraft(d) {
  const t = ms(d.time);
  if (Number.isNaN(t)) return "Start needs a date and time";
  const c = state.child;
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

async function saveEditor() {
  const e = state.editor, d = e.draft;
  if (e.saving) return;   // the second click of a double-click: the first is still writing
  const err = validateDraft(d);
  if (err) { setMsg(err); return; }
  let data = clone(d.data);
  if (d.type === "feed") {
    data.bottles = data.bottles.filter((b) => b.ml > 0);
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
  const body = { child_id: d.child_id, type: d.type, time: d.time, end: TIMED.includes(d.type) ? d.end : null,
    data, note: d.note, logged_by: d.logged_by };
  if (d.event_id) body.event_id = d.event_id;
  setBusy(e, true);
  try {
    if (d.event_id) {
      const cur = await latest(d.event_id);
      if (movedElsewhere(cur, e.event)) { await lookAgain(cur); return; }
    }
    const r = await postJSON("/api/event", body);
    closeEditor();
    if (!d.event_id && d.type === "diaper") saveLastDiaper({ event_id: r.event.event_id, ms: Date.now() });
    showToast(`${TYPE_LABEL[d.type]} ${d.event_id ? "updated" : "saved"} · ${Core.fmtTime(d.time)}`,
      [{ label: "Edit", fn: () => openEditor({ event: r.event }) }]);
    await afterWrite();
  } catch (x) { setMsg(x.message); }
  finally { setBusy(e, false); }
}

async function deleteEntry() {
  const e = state.editor, d = e.draft;
  if (e.saving) return;
  setBusy(e, true);
  try {
    await deleteJSON(`/api/event/${d.event_id}`, {});
    closeEditor();
    state.catchup.added = state.catchup.added.filter((id) => id !== d.event_id);
    showToast("Deleted · ", [{ label: "Undo", fn: () => restoreEntry(d.event_id) }]);
    await afterWrite();
  } catch (x) { setMsg(x.message); }
  finally { setBusy(e, false); }
}

async function restoreEntry(id) {
  try {
    await postJSON(`/api/event/${id}/restore`, {});
    if (state.catchup.records[id] && !state.catchup.added.includes(id)) state.catchup.added.unshift(id);
    await afterWrite();
  } catch (x) { showStatus("err", x.message); }
}

// ---------------------------------------------------------------- Catch up
/* The paper slips written when no phone was to hand (§6.2): one date, then a strip that logs one
   entry per tap and stays put for the next. Every tap is already a journal file — nothing waits
   for a "save all". Built once and kept, so the 30 s poll never wipes the date or a half-typed
   time; only the chips and the list under the strip are redrawn. */
function renderCatchup() {
  const view = document.getElementById("view-catchup");
  const cu = state.catchup;
  if (!view.dataset.built) {
    view.dataset.built = "1";
    const dateInput = el("input", { type: "date", id: "cu-date", value: cu.date, max: todayStr(),
      onchange: (x) => { if (/^\d{4}-\d{2}-\d{2}$/.test(x.target.value)) cu.date = x.target.value; renderCatchup(); } });
    const timeInput = el("input", { type: "time", id: "cu-time", step: "60", "aria-label": "Time",
      onkeydown: (x) => { if (x.key === "Enter") { x.preventDefault(); document.getElementById("cu-feed-first")?.focus(); } } });
    const otherAmount = el("input", { type: "number", inputmode: unit() === "oz" ? "decimal" : "numeric", min: "0", step: unit() === "oz" ? "0.25" : "1",
      id: "cu-other", placeholder: unit(), "aria-label": `Other amount (${unit()})`,
      onkeydown: (x) => { if (x.key === "Enter") { x.preventDefault(); addOther(); } } });
    const addOther = () => {
      const v = otherAmount.value === "" ? null : Core.fromUnit(otherAmount.value, unit());
      if (!v || v <= 0) { catchupMsg("Type an amount first", "err"); return; }
      catchupFeed(v).then((ok) => { if (ok) otherAmount.value = ""; });
    };
    view.replaceChildren(
      el("section", { class: "card catchup" },
        el("div", { class: "h2" }, "Catch up",
          el("span", { class: "sub" }, "type in the paper slips — one tap per entry, each saved at once"),
          el("button", { class: "primary", type: "button", style: "margin-left:auto", onclick: () => showView("today") }, "Done")),
        el("div", { class: "cu-strip" },
          el("label", { class: "field" }, el("span", {}, "Day"), dateInput),
          el("label", { class: "field narrow" }, el("span", {}, "Time"), timeInput),
          el("div", { class: "cu-group cu-feed" },
            el("span", { class: "cu-group-h" }, "Feed"),
            el("span", { class: "chips", id: "cu-feed-chips" }),
            el("span", { class: "cu-other" }, otherAmount,
              el("button", { class: "chip", type: "button", onclick: addOther }, "Add"))),
          el("div", { class: "cu-group cu-diaper" },
            el("span", { class: "cu-group-h" }, "Diaper"),
            el("span", { class: "loggroup" },
              el("button", { class: "logbtn diaper wet", type: "button", onclick: () => catchupDiaper(true, false) }, "Wet"),
              el("button", { class: "logbtn diaper dirty", type: "button", onclick: () => catchupDiaper(false, true) }, "Dirty"),
              el("button", { class: "logbtn diaper", type: "button", onclick: () => catchupDiaper(true, true) }, "Both")))),
        el("div", { class: "ed-msg", id: "cu-msg", hidden: true }),
        el("div", { class: "cu-formula muted small", id: "cu-formula" }),
        el("div", { id: "cu-list" })));
  }
  // The chips follow the settings (the range control in the feed editor moves them), the formula
  // line follows the newest name on file, and the list follows the journal.
  const chips = document.getElementById("cu-feed-chips");
  chips.replaceChildren(...quickAmounts().map((mlv, i) => el("button", { class: "chip feed", type: "button", id: i === 0 ? "cu-feed-first" : null,
    onclick: () => catchupFeed(mlv) }, amount(mlv))));
  if (!chips.children.length) chips.append(el("span", { class: "muted small" }, "No quick amounts — set the range in Settings, or type one:"));
  const lf = lastFormula();
  document.getElementById("cu-formula").textContent = lf ? `Feeds are saved as ${lf} — change it on any feed's editor.` : "";
  const list = document.getElementById("cu-list");
  const rows = cu.added.map((id) => byId(id) || cu.records[id]).filter(Boolean);
  list.replaceChildren(el("div", { class: "h3" }, `Added this session (${rows.length})`),
    ...rows.map((ev) => el("div", { class: "list-row openable", onclick: () => openEditor({ event: ev }) },
      el("span", { class: "num" }, Core.fmtDateTime(ev.time)),
      el("span", {}, `${TYPE_LABEL[ev.type] || ev.type} · ${Core.describe(ev, unit())}`),
      el("span", { class: "muted small grow" }, ev.note || ""),
      el("span", { class: "muted small" }, "edit"))));
  list.hidden = !rows.length;
}

function catchupMsg(text, kind) {
  const box = document.getElementById("cu-msg");
  if (!box) return;
  box.hidden = !text;
  box.className = `ed-msg ${kind || "ok"}`;
  box.textContent = text || "";
}

// The strip's date + time as a §3.2 string, or null (with the refusal shown) when the time is
// missing or the moment is impossible.
function catchupTime() {
  const cu = state.catchup;
  const t = (document.getElementById("cu-time") || {}).value || "";
  const m = /^(\d{2}):(\d{2})/.exec(t);
  if (!m) { catchupMsg("Type the time first (HH:MM)", "err"); return null; }
  const [y, mo, d] = cu.date.split("-").map(Number);
  const iso = Core.isoLocal(new Date(y, mo - 1, d, Number(m[1]), Number(m[2]), 0));
  const err = validateDraft({ time: iso, end: null, type: "diaper", data: {} });
  if (err) { catchupMsg(err, "err"); return null; }
  return iso;
}

// One tap, one journal file; then only the time clears and takes the focus for the next slip.
async function catchupWrite(bodyAt, said) {
  if (writing) return false;
  const time = catchupTime();
  if (!time) return false;
  writing = true;
  try {
    const r = await postJSON("/api/event", Object.assign({ time, note: "", logged_by: myLabel() }, bodyAt(time)));
    const cu = state.catchup;
    cu.added.unshift(r.event.event_id);
    cu.records[r.event.event_id] = r.event;
    catchupMsg(`Added ${said} · ${Core.fmtTime(time)}`, "ok");
    const timeInput = document.getElementById("cu-time");
    if (timeInput) { timeInput.value = ""; timeInput.focus(); }
    await afterWrite();
    return true;
  } catch (e) { catchupMsg(e.message, "err"); return false; }
  finally { writing = false; }
}

function catchupFeed(mlv) {
  const name = lastFormula();
  // A bottle feed typed in after the fact is over the moment it is written, so its end is its
  // start — the same rule the editor's Save applies (Core.isRunning must not read it as going).
  return catchupWrite((time) => ({ type: "feed", end: time, data: { bottles: [{ kind: "formula", ml: mlv, formula: name }] } }), `feed ${amount(mlv)}`);
}

function catchupDiaper(wet, dirty) {
  return catchupWrite(() => ({ type: "diaper", end: null, data: { wet, dirty } }), wet && dirty ? "wet + dirty" : (wet ? "wet" : "dirty"));
}

// ---------------------------------------------------------------- Trends
function renderTrends() {
  const view = document.getElementById("view-trends");
  const today = todayStr();
  const now = new Date();
  const tg = targets();
  const days = [];
  for (let i = 13; i >= 0; i--) days.push(shiftDay(today, -i));
  const num = (v, target) => el("td", { class: `t-num${target && v < target ? " under" : ""}` }, String(v));
  const rows = days.map((day) => {
    const t = Core.totals(state.events, day, now);
    return el("tr", { class: day === today ? "today openable" : "openable",
      onclick: () => { state.date = day; showView("today"); refreshAll(); } },
      el("td", {}, Core.fmtDay(day)),
      num(t.feeds, tg.feeds_per_day), el("td", { class: "t-num" }, t.bottle_ml ? amount(t.bottle_ml) : "—"),
      el("td", { class: "t-num" }, t.breast_s ? String(Math.round(t.breast_s / 60)) : "—"),
      num(t.wet, tg.wet_per_day), num(t.dirty, tg.dirty_per_day),
      el("td", { class: "t-num" }, String(t.sleeps)), el("td", { class: "t-num" }, t.sleep_s ? Core.sinceText(t.sleep_s * 1000) : "—"),
      el("td", { class: "t-num" }, String(t.pumps)), el("td", { class: "t-num" }, t.pump_ml ? amount(t.pump_ml) : "—"));
  });
  const target = (v) => el("td", { class: "t-num" }, v ? `target ${v}` : "");
  view.replaceChildren(
    el("section", { class: "card" },
      el("div", { class: "h2" }, "Last 14 days", el("span", { class: "sub" }, "a row opens that day")),
      el("div", { class: "t-scroll" }, el("table", { class: "t-table" },
        el("thead", {}, el("tr", {}, ...["Day", "Feeds", "Bottle", "Breast min", "Wet", "Dirty", "Sleeps", "Sleep", "Pumps", "Pumped"].map((h) => el("th", {}, h))),
          (tg.feeds_per_day || tg.wet_per_day || tg.dirty_per_day) ? el("tr", { class: "target-row" },
            el("td", {}, ""), target(tg.feeds_per_day), el("td"), el("td"), target(tg.wet_per_day), target(tg.dirty_per_day), el("td"), el("td"), el("td"), el("td")) : null),
        el("tbody", {}, ...rows)))),
    el("section", { class: "card" },
      el("div", { class: "h2" }, "24-hour rhythm", el("span", { class: "sub" }, "last 7 days · feeds as bars by start time and breast length · wet and dirty as dots · night shaded")),
      rhythmChart(days.slice(-7)),
      el("div", { class: "legend" },
        el("span", {}, el("i", { style: "background:var(--feed)" }), "breast feed (length)"),
        el("span", {}, el("i", { style: "background:#E4A374" }), "bottle only"),
        el("span", {}, el("i", { style: "background:var(--wet); border-radius:50%" }), "wet"),
        el("span", {}, el("i", { style: "background:var(--dirty); border-radius:50%" }), "dirty"),
        el("span", {}, el("i", { style: "background:var(--night); border:1px solid var(--line)" }), `night ${(state.settings || {}).night_from || "21:00"}–${(state.settings || {}).night_to || "07:00"}`))));
}

// Hand-drawn SVG: one row per day, midnight to midnight.
function rhythmChart(days) {
  const W = 800, L = 70, R = 14, T = 24, RH = 40, B = 6;
  const PW = W - L - R;
  const H = T + days.length * RH + B;
  const x = (h) => L + (h / 24) * PW;
  const s = (state.settings || {});
  const toH = (hm) => { const m = /^(\d{1,2}):(\d{2})$/.exec(hm || ""); return m ? Number(m[1]) + Number(m[2]) / 60 : null; };
  const nf = toH(s.night_from), nt = toH(s.night_to);
  const nightSpans = nf === null || nt === null ? [] : nf <= nt ? [[nf, nt]] : [[nf, 24], [0, nt]];
  const now = new Date();
  const kids = [];
  for (let h = 0; h <= 24; h += 3) {
    kids.push(svg("line", { class: "rh-grid", x1: x(h), y1: T - 4, x2: x(h), y2: H - B }));
    kids.push(svg("text", { class: "rh-hour", x: x(h), y: T - 10, "text-anchor": "middle" }, document.createTextNode(`${pad(h % 24)}:00`)));
  }
  days.forEach((day, i) => {
    const y0 = T + i * RH;
    for (const [a, b] of nightSpans) kids.push(svg("rect", { class: "rh-night", x: x(a), y: y0, width: x(b) - x(a), height: RH }));
    kids.push(svg("line", { class: "rh-grid", x1: L, y1: y0 + RH, x2: W - R, y2: y0 + RH }));
    kids.push(svg("text", { class: "rh-day", x: L - 8, y: y0 + RH / 2 + 4, "text-anchor": "end" }, document.createTextNode(Core.fmtDay(day))));
    for (const ev of Core.onDay(state.events, day)) {
      const h = hourOf(ev.time);
      const open = () => openEditor({ event: ev });
      const title = (t) => svg("title", {}, document.createTextNode(t));
      if (ev.type === "feed") {
        const sec = Core.breastSeconds(ev, now);
        const w = Math.max(3, (sec / 3600) * (PW / 24));
        kids.push(svg("rect", { class: `rh-feed${sec ? "" : " bottle-only"}`, x: x(h), y: y0 + 6, width: Math.min(w, x(24) - x(h)), height: 16, rx: 2, onclick: open },
          title(`${Core.fmtTime(ev.time)} · ${Core.describe(ev, unit())}`)));
      } else if (ev.type === "diaper") {
        const dd = ev.data;
        if (dd.wet) kids.push(svg("circle", { class: "rh-wet", cx: x(h), cy: y0 + 30, r: 3.5, onclick: open }, title(`${Core.fmtTime(ev.time)} · ${Core.describe(ev, unit())}`)));
        if (dd.dirty) kids.push(svg("circle", { class: "rh-dirty", cx: x(h) + (dd.wet ? 6 : 0), cy: y0 + 30, r: 3.5, onclick: open }, title(`${Core.fmtTime(ev.time)} · ${Core.describe(ev, unit())}`)));
      }
    }
  });
  return svg("svg", { class: "rhythm", viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "24-hour rhythm chart" }, ...kids);
}

// ---------------------------------------------------------------- Growth
function renderGrowth() {
  const view = document.getElementById("view-growth");
  const evs = state.events.filter((ev) => ev.type === "growth");
  const birth = state.child && state.child.birth_weight_g;
  const firstWeight = evs.find((ev) => ev.data.weight_g != null);
  const base = birth != null ? birth : (firstWeight ? firstWeight.data.weight_g : null);
  // Core.describe's rounding, so 3425 g reads 3.43 kg here as on every other screen and in the
  // sheet (toFixed rounds the binary 3.425 down to 3.42).
  const kg = (g) => `${Math.round(g / 10) / 100} kg`;
  let prev = null;
  const rows = evs.map((ev) => {
    const w = ev.data.weight_g;
    const cells = [
      el("td", {}, Core.fmtDateTime(ev.time)),
      el("td", { class: "t-num" }, w != null ? kg(w) : "—",
        w != null && base != null ? el("span", { class: `delta${w - base >= 0 ? " up" : ""}` }, `${w - base >= 0 ? "+" : ""}${w - base} g from birth`) : null,
        w != null && prev != null ? el("span", { class: "delta" }, `${w - prev >= 0 ? "+" : ""}${w - prev} g since last`) : null),
      el("td", { class: "t-num" }, ev.data.length_cm != null ? `${ev.data.length_cm} cm` : "—"),
      el("td", { class: "t-num" }, ev.data.head_cm != null ? `${ev.data.head_cm} cm` : "—"),
      el("td", { class: "muted" }, ev.logged_by || ""),
      el("td", { class: "muted" }, ev.note || ""),
    ];
    if (w != null) prev = w;
    return el("tr", { class: "openable", onclick: () => openEditor({ event: ev }) }, ...cells);
  });
  view.replaceChildren(el("section", { class: "card" },
    el("div", { class: "h2" }, "Growth",
      el("span", { class: "sub" }, birth != null ? `birth weight ${kg(birth)}` : "birth weight not set — Settings → Child"),
      el("button", { class: "ghost", type: "button", style: "margin-left:auto", onclick: () => openEditor({ type: "growth" }) }, "Add weight")),
    rows.length ? el("div", { class: "t-scroll" }, el("table", { class: "t-table" },
      el("thead", {}, el("tr", {}, ...["When", "Weight", "Length", "Head", "By", "Note"].map((h) => el("th", {}, h)))),
      el("tbody", {}, ...rows))) : el("div", { class: "empty" }, "No weights yet.")));
}

// ---------------------------------------------------------------- Health
function renderHealth() {
  const view = document.getElementById("view-health");
  const evs = state.events.filter((ev) => ev.type === "health");
  const now = Date.now();
  const meds = new Map();
  for (const ev of evs) if (ev.data.medicine) meds.set(ev.data.medicine, ev);   // ascending, so the last wins
  const rows = evs.slice().reverse().map((ev) => el("tr", { class: "openable", onclick: () => openEditor({ event: ev }) },
    el("td", {}, Core.fmtDateTime(ev.time)),
    el("td", {}, Core.describe(ev, unit())),
    el("td", { class: "t-num" }, ev.data.temp_c != null ? `${ev.data.temp_c} °C` : ""),
    el("td", { class: "muted" }, ev.logged_by || ""),
    el("td", { class: "muted" }, ev.note || "")));
  view.replaceChildren(el("section", { class: "card" },
    el("div", { class: "h2" }, "Health",
      el("button", { class: "ghost", type: "button", style: "margin-left:auto", onclick: () => openEditor({ type: "health" }) }, "Add")),
    meds.size ? el("div", { class: "meds" }, ...Array.from(meds.values()).map((ev) => el("div", { class: "med", onclick: () => openEditor({ event: ev }) },
      el("div", { class: "med-name" }, ev.data.medicine),
      el("div", { class: "med-last" }, `last given ${Core.sinceText(now - ms(ev.time))} ago${ev.data.dose ? ` · ${ev.data.dose}` : ""}`),
      el("div", { class: "muted small" }, Core.fmtDateTime(ev.time))))) : null,
    rows.length ? el("div", { class: "t-scroll" }, el("table", { class: "t-table" },
      el("thead", {}, el("tr", {}, ...["When", "What", "Temp", "By", "Note"].map((h) => el("th", {}, h)))),
      el("tbody", {}, ...rows))) : el("div", { class: "empty" }, "Nothing logged yet.")));
}

// ---------------------------------------------------------------- Reports
function renderReports() {
  const view = document.getElementById("view-reports");
  if (view.dataset.built) { renderReportPaths(); return; }   // keep the typed dates across polls
  view.dataset.built = "1";
  const today = todayStr();
  const dayInput = el("input", { type: "date", value: state.date || today });
  const fromInput = el("input", { type: "date", value: shiftDay(today, -6) });
  const toInput = el("input", { type: "date", value: today });
  const run = async (btn, label, fn) => {
    btn.disabled = true; btn.textContent = `${label}…`;
    try {
      const r = await fn();
      state.reports.paths.unshift({ at: Core.fmtTime(nowIso()), label, path: r.path });
      state.reports.paths = state.reports.paths.slice(0, 8);
      renderReportPaths();
    } catch (e) { showStatus("err", e.message); }
    btn.disabled = false; btn.textContent = label;
  };
  const saveBtn = el("button", { class: "ghost", type: "button",
    onclick: () => run(saveBtn, "Save day sheet", () => postJSON(`/api/daysheet/${dayInput.value}`, {})) }, "Save day sheet");
  const rebuildBtn = el("button", { class: "ghost", type: "button",
    onclick: () => run(rebuildBtn, "Rebuild Baby Log.xlsx", () => postJSON("/api/rollup", {})) }, "Rebuild Baby Log.xlsx");
  // The app runs in an Edge --app window, so a plain window.open gives a printable tab.
  view.replaceChildren(
    el("section", { class: "card" },
      el("div", { class: "h2" }, "Day sheet"),
      el("div", { class: "form" },
        el("label", { class: "field" }, el("span", {}, "Day"), dayInput),
        el("button", { class: "primary", type: "button", onclick: () => window.open(`/print/day/${dayInput.value}`, "_blank") }, "Print day sheet"),
        saveBtn),
      el("div", { class: "paths" }, "Save writes ", el("span", { class: "path" }, "Day sheets/<date>.html"), " into Yisen File.")),
    el("section", { class: "card" },
      el("div", { class: "h2" }, "Date range"),
      el("div", { class: "form" },
        el("label", { class: "field" }, el("span", {}, "From"), fromInput),
        el("label", { class: "field" }, el("span", {}, "To"), toInput),
        el("button", { class: "primary", type: "button",
          onclick: () => window.open(`/print/range?from=${fromInput.value}&to=${toInput.value}`, "_blank") }, "Print daily totals"))),
    el("section", { class: "card" },
      el("div", { class: "h2" }, "Baby Log.xlsx"),
      el("div", { class: "form" }, rebuildBtn,
        el("span", { class: "muted small" }, "It also rebuilds itself 20 s after any change and when the phones' entries arrive.")),
      el("div", { class: "paths" }, "Folder: ", el("span", { class: "path" }, (state.config && state.config.output_folder) || "—")),
      el("div", { class: "paths" }, "Journal: ", el("span", { class: "path" }, (state.config && state.config.app_folder) || "—"))),
    el("section", { class: "card", id: "report-paths" }));
  renderReportPaths();
}

function renderReportPaths() {
  const box = document.getElementById("report-paths");
  if (!box) return;
  const p = state.reports.paths;
  box.hidden = !p.length;
  box.replaceChildren(el("div", { class: "h2" }, "Written"),
    ...p.map((r) => el("div", { class: "list-row" }, el("span", { class: "muted small" }, r.at), el("span", {}, r.label), el("span", { class: "path grow" }, r.path))));
}

// ---------------------------------------------------------------- Settings
async function loadDeleted() {
  try {
    const r = await api("/api/deleted");
    state.deleted = r.events || [];
  } catch { state.deleted = []; }
  if (state.view === "settings") renderSettings();
}

function renderSettings() {
  const view = document.getElementById("view-settings");
  const s = state.settings || {};
  const first = !view.dataset.built;
  view.dataset.built = "1";

  // The forms are built once and kept, so a poll never wipes a half-typed field; the lists
  // below them are redrawn on every render.
  if (first) {
    const f = {};
    const field = (key, label, input) => { f[key] = input; return el("label", { class: "field" }, el("span", {}, label), input); };
    const settingsCard = el("section", { class: "card" },
      el("div", { class: "h2" }, "This PC"),
      el("div", { class: "form" },
        field("label", "Label (who logs from here)", el("input", { type: "text", value: s.label || "", placeholder: "Dad, Mom…" })),
        field("units", "Units", el("select", {}, el("option", { value: "ml", selected: s.units !== "oz" }, "ml"), el("option", { value: "oz", selected: s.units === "oz" }, "oz"))),
        field("step_ml", "−/+ step (ml, blank = automatic)", el("input", { type: "number", min: "1", step: "1", value: s.step_ml == null ? "" : String(s.step_ml) })),
        field("quick_mode", "Quick amounts", el("select", { onchange: () => showQuickFields() },
          el("option", { value: "range", selected: (s.quick_mode || "range") === "range" }, "a range"),
          el("option", { value: "recent", selected: s.quick_mode === "recent" }, "from recent feeds"),
          el("option", { value: "custom", selected: s.quick_mode === "custom" }, "custom list"))),
        field("quick_from", "Range from (ml)", el("input", { type: "number", id: "set-quick-from", inputmode: "numeric", min: "1", step: "1", value: s.quick_from == null ? "" : String(s.quick_from) })),
        field("quick_to", "to (ml)", el("input", { type: "number", id: "set-quick-to", inputmode: "numeric", min: "1", step: "1", value: s.quick_to == null ? "" : String(s.quick_to) })),
        field("quick_step", "by (ml)", el("input", { type: "number", id: "set-quick-step", inputmode: "numeric", min: "1", step: "1", value: s.quick_step == null ? "" : String(s.quick_step) })),
        field("quick_custom", "Custom amounts (ml, comma separated)", el("input", { type: "text", value: (s.quick_custom || []).join(", "), placeholder: "30, 60, 90, 120" })),
        field("night_from", "Night from", el("input", { type: "time", value: s.night_from || "21:00" })),
        field("night_to", "Night to", el("input", { type: "time", value: s.night_to || "07:00" }))),
      el("div", { class: "row" },
        el("button", { class: "primary", type: "button", onclick: async (x) => {
          const custom = f.quick_custom.value.split(/[,\s]+/).filter(Boolean).map(Number).filter((n) => Number.isFinite(n) && n > 0);
          const nOrNull = (inp) => (inp.value === "" ? null : Number(inp.value));
          const body = { label: f.label.value.trim(), units: f.units.value, step_ml: nOrNull(f.step_ml),
            quick_mode: f.quick_mode.value, quick_custom: custom,
            quick_from: nOrNull(f.quick_from), quick_to: nOrNull(f.quick_to), quick_step: nOrNull(f.quick_step),
            night_from: f.night_from.value || "21:00", night_to: f.night_to.value || "07:00" };
          x.target.disabled = true;
          try {
            await postJSON("/api/settings", body);
            await loadConfig();
            showStatus("ok", "Settings saved.");
            renderTopbar();
          } catch (e) { showStatus("err", e.message); }
          x.target.disabled = false;
        } }, "Save settings"),
        el("span", { class: "muted small" }, `Automatic step right now: ${amount(Core.stepMl(recentMls(), unit()))}`)));
    // Only the chosen mode's fields show: the range's three, or the custom list.
    const showQuickFields = () => {
      const mode = f.quick_mode.value;
      for (const k of ["quick_from", "quick_to", "quick_step"]) f[k].parentElement.hidden = mode !== "range";
      f.quick_custom.parentElement.hidden = mode !== "custom";
    };
    showQuickFields();
    view.replaceChildren(settingsCard,
      el("section", { class: "card", id: "settings-child" }),
      el("section", { class: "card", id: "settings-needs" }),
      el("section", { class: "card", id: "settings-deleted" }));
  }

  const childCard = document.getElementById("settings-child");
  if (!childCard.dataset.built || childCard.dataset.child !== String(state.child && state.child.child_id)) {
    childCard.dataset.built = "1";
    childCard.dataset.child = String(state.child && state.child.child_id);
    childCard.replaceChildren(el("div", { class: "h2" }, "Child"), childForm(state.child, null));
  }

  const needs = document.getElementById("settings-needs");
  needs.replaceChildren(el("div", { class: "h2" }, `Needs check (${state.needs.length})`,
    el("span", { class: "sub" }, "readings from the paper sheet that were hard to read — open, correct, and drop the “Check:” from the note")),
    state.needs.length ? el("div", {}, ...state.needs.map((ev) => el("div", { class: "list-row openable", onclick: () => openEditor({ event: ev }) },
      el("span", { class: "num" }, Core.fmtDateTime(ev.time)), el("span", {}, Core.describe(ev, unit())),
      el("span", { class: "muted small grow" }, ev.note || "")))) : el("div", { class: "empty" }, "Nothing left to check."));

  const del = document.getElementById("settings-deleted");
  del.replaceChildren(el("div", { class: "h2" }, `Deleted (${state.deleted.length})`, el("span", { class: "sub" }, "Restore brings an entry back as it last was")),
    state.deleted.length ? el("div", {}, ...state.deleted.map((ev) => el("div", { class: "list-row" },
      el("span", { class: "num" }, Core.fmtDateTime(ev.time)), el("span", {}, `${TYPE_LABEL[ev.type] || ev.type} · ${Core.describe(ev, unit())}`),
      el("span", { class: "muted small grow" }, `${ev.reason ? `${ev.reason} · ` : ""}by ${ev.edited_by || ev.logged_by || "?"}`),
      el("button", { class: "ghost", type: "button", onclick: () => restoreEntry(ev.event_id) }, "Restore")))) : el("div", { class: "empty" }, "Nothing deleted."));
}

// The feed editor's range control saved a bound: the Settings form, built once and kept, must
// show the same numbers or its next Save would put the old ones back.
function syncSettingsRange() {
  const s = state.settings || {};
  for (const [id, key] of [["set-quick-from", "quick_from"], ["set-quick-to", "quick_to"], ["set-quick-step", "quick_step"]]) {
    const input = document.getElementById(id);
    if (input) input.value = s[key] == null ? "" : String(s[key]);
  }
}

// The child form: creates on first run, revises from Settings (§3.3).
function childForm(child, onSaved) {
  const c = child || {};
  const t = c.targets || {};
  const f = {};
  const field = (key, label, input, cls = "") => { f[key] = input; return el("label", { class: `field ${cls}` }, el("span", {}, label), input); };
  const num = (v) => el("input", { type: "number", min: "0", step: "1", value: v == null ? "" : String(v) });
  const msg = el("div", { class: "ed-msg err", hidden: true });
  return el("div", {},
    el("div", { class: "form" },
      field("name", "Name", el("input", { type: "text", value: c.name || "" })),
      field("born", "Born", el("input", { type: "date", value: c.born || "" })),
      field("born_time", "Time of birth", el("input", { type: "time", value: c.born_time || "" })),
      field("sex", "Sex", el("select", {}, ...SEX.map((v) => el("option", { value: v, selected: (c.sex || "") === v }, v || "—")))),
      field("birth_weight_g", "Birth weight (g)", num(c.birth_weight_g), "narrow")),
    el("div", { class: "h3" }, "Targets (what the pediatrician said)"),
    el("div", { class: "form" },
      field("feeds_per_day", "Feeds / day", num(t.feeds_per_day), "narrow"),
      field("wet_per_day", "Wet / day", num(t.wet_per_day), "narrow"),
      field("dirty_per_day", "Dirty / day", num(t.dirty_per_day), "narrow")),
    msg,
    el("div", { class: "row" },
      el("button", { class: "primary", type: "button", onclick: async (x) => {
        const name = f.name.value.trim(), born = f.born.value;
        if (!name) { msg.hidden = false; msg.textContent = "A name is needed"; return; }
        if (!/^\d{4}-\d{2}-\d{2}$/.test(born)) { msg.hidden = false; msg.textContent = "A birth date is needed"; return; }
        const n = (inp) => (inp.value === "" ? null : Number(inp.value));
        const body = { name, born, born_time: f.born_time.value || null, sex: f.sex.value || null, birth_weight_g: n(f.birth_weight_g),
          targets: { feeds_per_day: n(f.feeds_per_day), wet_per_day: n(f.wet_per_day), dirty_per_day: n(f.dirty_per_day) } };
        if (c.child_id) body.child_id = c.child_id;
        x.target.disabled = true;
        try {
          await postJSON("/api/children", body);
          msg.hidden = true;
          await loadConfig();
          showStatus("ok", c.child_id ? `${name} updated.` : `${name} added.`);
          if (onSaved) onSaved();
          await refreshAll();
        } catch (e) { msg.hidden = false; msg.textContent = e.message; }
        x.target.disabled = false;
      } }, child ? "Save child" : "Add child")));
}

document.addEventListener("DOMContentLoaded", boot);
