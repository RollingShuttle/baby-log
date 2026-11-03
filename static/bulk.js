/* Baby Log — the bulk-entry shorthand parser for the PC's Catch up screen (SPEC.md §6.2).

   A month of paper slips, twenty-odd lines a day, typed as one line per entry:

       11/02                  a day header: 11/02 · 11-02 · 11.2 · 2026-11-02 · 11月2日 · 2日
       0130 70 enfamil        01:30, a 70 ml formula feed of Enfamil
       345 w                  03:45, a wet diaper
       下午1:30 80 # slow     13:30, 80 ml of the last formula, note "slow"
       9:10pm wd              21:10, wet + dirty

   Pure functions, no DOM, no storage, and nothing from Core beyond what the caller passes in
   (opts.isoLocal), so the file runs standalone under Node for tests/test_bulk.py. Nothing here
   throws on bad input: every line becomes a row, and a line the parser cannot read is a row with
   `error` set, so the preview can show the slip beside the complaint and the save can skip it.
   Must run in Edge and Node 14/16 — so no ??=, no .at(), no optional chaining. */
"use strict";

const Bulk = (() => {
  const pad = (n) => String(n).padStart(2, "0");
  const OZ_ML = 29.5735;
  const MIN = 60000;

  // Day headers. The year forms accept 年/月/日 as well as - / . so a slip copied from a
  // Chinese calendar reads; the 日 after the day is optional everywhere it could appear.
  const FULL_DATE = /^(\d{4})[-/.年](\d{1,2})[-/.月](\d{1,2})日?$/;
  const MONTH_DAY = /^(\d{1,2})[-/.月](\d{1,2})日?$/;
  const DAY_ONLY = /^(\d{1,2})日$/;

  // The time at the head of an entry: an optional Chinese half-day word, the digits (3 or 4
  // without a colon, or h:mm), an optional am/pm, then whitespace or the end of the line — the
  // boundary is what stops "1300 70" from being read as 13:00 + "70" and "130070" as anything.
  const TIME_RE = /^(上午|早上|早晨|凌晨|下午|中午|傍晚|晚上)?\s*(\d{1,2}:\d{2}|\d{3,4})\s*(am|pm|a\.m\.|p\.m\.)?(?=\s|$)/i;
  const AM_WORDS = ["上午", "早上", "早晨", "凌晨"];
  const PM_WORDS = ["下午", "中午", "傍晚", "晚上"];

  // A feed: an optional 奶, the ml (whole or decimal), an optional ml/毫升, then the formula name.
  const FEED_RE = /^(?:奶\s*)?(\d+(?:\.\d+)?)\s*(?:ml|毫升)?(?:\s+(.*))?$/i;
  const DIAPERS = {
    w: "wet", wet: "wet", "尿": "wet", "小便": "wet", "尿尿": "wet",
    d: "dirty", dirty: "dirty", p: "dirty", poo: "dirty", poop: "dirty",
    "屎": "dirty", "便": "dirty", "大便": "dirty", "便便": "dirty",
    wd: "both", dw: "both", both: "both", "尿屎": "both", "屎尿": "both", "都有": "both",
  };

  // The same shape Core.isoLocal writes, for a caller that passes no isoLocal (tests, a REPL).
  function isoLocalFallback(d) {
    const off = -d.getTimezoneOffset();
    const a = Math.abs(off);
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
      + `T${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
      + `${off < 0 ? "-" : "+"}${pad(Math.floor(a / 60))}:${pad(a % 60)}`;
  }
  const dateStr = (y, m, d) => `${y}-${pad(m)}-${pad(d)}`;
  const daysIn = (y, m) => new Date(Date.UTC(y, m, 0)).getUTCDate();
  const localDateOf = (d) => dateStr(d.getFullYear(), d.getMonth() + 1, d.getDate());

  // A header line → {date, month} or {error}, or null when the line is not a date at all.
  // `ctx` carries the month the previous header set (for "2日") and today's date for the year
  // rule: the current year unless that would be in the future, then the year before — the slips
  // are always about days already lived, so "12/02" typed on 3 Nov means last December.
  function parseHeader(text, ctx) {
    let m = FULL_DATE.exec(text);
    let y, mo, d, fixedYear = false;
    if (m) { y = Number(m[1]); mo = Number(m[2]); d = Number(m[3]); fixedYear = true; }
    else if ((m = MONTH_DAY.exec(text))) { mo = Number(m[1]); d = Number(m[2]); }
    else if ((m = DAY_ONLY.exec(text))) { mo = ctx.month; d = Number(m[1]); }
    else return null;
    // Without a year, 2000 (a leap year) stands in so 29 Feb is judged once the year is known.
    if (mo < 1 || mo > 12 || d < 1 || d > daysIn(fixedYear ? y : 2000, mo)) {
      return { error: `not a real date: ${text}` };
    }
    if (!fixedYear) {
      y = Number(ctx.today.slice(0, 4));
      if (dateStr(y, mo, d) > ctx.today) y -= 1;
      if (d > daysIn(y, mo)) return { error: `not a real date: ${text}` };
    }
    return { date: dateStr(y, mo, d), month: mo };
  }

  // The time at the head of an entry → {hhmm, rest} or {error}. 12-hour only when an am/pm
  // word is present; 凌晨/晚上 12:xx is midnight-side in Chinese usage, so both map hour 12
  // to 0, while an English "12:30 pm" stays noon.
  function parseTime(text) {
    const m = TIME_RE.exec(text);
    if (!m) return { error: "unreadable time" };
    const word = m[1] || "";
    const digits = m[2];
    const suffix = (m[3] || "").toLowerCase().replace(/\./g, "");
    let h, mi;
    if (digits.indexOf(":") >= 0) {
      const parts = digits.split(":");
      h = Number(parts[0]); mi = Number(parts[1]);
    } else {
      h = Number(digits.slice(0, digits.length - 2));
      mi = Number(digits.slice(-2));
    }
    const am = suffix === "am" || AM_WORDS.indexOf(word) >= 0;
    const pm = suffix === "pm" || PM_WORDS.indexOf(word) >= 0;
    if (am && pm) return { error: "unreadable time" };
    if (am) {
      if (h > 12) return { error: "unreadable time" };
      if (h === 12) h = 0;
    } else if (pm) {
      if (h < 12) h += 12;
      else if (h === 12 && word === "晚上") h = 0;
    }
    if (h > 23 || mi > 59) return { error: "unreadable time" };
    return { hhmm: `${pad(h)}:${pad(mi)}`, rest: text.slice(m[0].length).trim() };
  }

  // A typed formula name spelt the way it is already on file ("enfamil" → "Enfamil"), so a
  // month typed in lower case does not become a second chip beside the real one; a name never
  // seen before gets its initials capitalised.
  function canonical(typed, known) {
    const low = typed.toLowerCase();
    for (const k of known || []) if (typeof k === "string" && k.toLowerCase() === low) return k;
    return typed.replace(/(^|\s)(\S)/g, (m0, sp, ch) => sp + ch.toUpperCase());
  }

  // What happened: a feed in ml with an optional formula name, or one of the diaper words.
  // Returns {type, data, typed?} or {error}.
  function parseWhat(text, lastFormula, known) {
    const key = text.toLowerCase();
    if (Object.prototype.hasOwnProperty.call(DIAPERS, key)) {
      const which = DIAPERS[key];
      return { type: "diaper", data: { wet: which !== "dirty", dirty: which !== "wet" } };
    }
    if (!text) return { error: "nothing after the time" };
    const m = FEED_RE.exec(text);
    if (!m) return { error: `unreadable entry: ${text}` };
    const ml = Math.round(Number(m[1]));
    if (!Number.isFinite(ml) || ml <= 0) return { error: "amount must be more than 0 ml" };
    const typed = canonical((m[2] || "").replace(/\s+/g, " ").trim(), known);
    const formula = typed || lastFormula || null;
    return { type: "feed", data: { bottles: [{ kind: "formula", ml, formula }] }, typed };
  }

  function blankRow(line, text) {
    return { line, kind: "ignore", date: null, hhmm: null, type: null, data: null, note: "",
      time: null, text, error: null };
  }

  /* parse(text, opts) → {rows, counts, days}.
     opts: now (Date), born ("YYYY-MM-DD" | null), lastFormula (string | null),
     isoLocal (Date → the §3.2 iso string). A formula typed on one line carries to the lines
     below it, the way a slip reads — the owner writes the brand once when it changes. */
  function parse(text, opts) {
    const o = opts || {};
    const now = o.now instanceof Date ? o.now : new Date();
    const isoLocal = typeof o.isoLocal === "function" ? o.isoLocal : isoLocalFallback;
    const born = typeof o.born === "string" && o.born ? o.born : null;
    const today = localDateOf(now);
    const latest = now.getTime() + 10 * MIN;
    const ctx = { today, month: now.getMonth() + 1, date: null };
    let lastFormula = typeof o.lastFormula === "string" && o.lastFormula ? o.lastFormula : null;
    const known = Array.isArray(o.formulas) ? o.formulas.slice() : [];
    if (lastFormula) known.push(lastFormula);
    const rows = [];
    const counts = { feeds: 0, wet: 0, dirty: 0, both: 0, errors: 0, entries: 0 };
    const days = new Set();
    const lines = String(text == null ? "" : text).split(/\r?\n/);

    lines.forEach((raw, i) => {
      const row = blankRow(i + 1, raw);
      rows.push(row);
      const hash = raw.indexOf("#");
      const body = (hash < 0 ? raw : raw.slice(0, hash)).trim();
      const note = hash < 0 ? "" : raw.slice(hash + 1).trim();
      if (!body) return;   // blank, or a comment line

      const fail = (why) => { row.kind = "error"; row.error = why; counts.errors += 1; };

      // A header sets the date for everything below it; a bad one unsets it, so the lines below
      // complain too rather than land on the previous day unnoticed.
      const header = parseHeader(body, ctx);
      if (header) {
        row.kind = "header";
        if (header.error) { ctx.date = null; fail(header.error); return; }
        ctx.month = header.month;
        if (born && header.date < born) {
          ctx.date = null;
          fail(`${header.date} is before the child's birth (${born})`);
          return;
        }
        ctx.date = header.date;
        row.date = header.date;
        return;
      }

      row.kind = "entry";
      row.note = note;
      row.date = ctx.date;
      const t = parseTime(body);
      if (t.error) { fail(t.error); return; }
      row.hhmm = t.hhmm;
      if (!ctx.date) { fail("no date above this line"); return; }
      const what = parseWhat(t.rest, lastFormula, known);
      if (what.error) { fail(what.error); return; }
      const d = new Date(Number(ctx.date.slice(0, 4)), Number(ctx.date.slice(5, 7)) - 1,
        Number(ctx.date.slice(8, 10)), Number(t.hhmm.slice(0, 2)), Number(t.hhmm.slice(3, 5)));
      if (d.getTime() > latest) { fail("later than now"); return; }
      row.type = what.type;
      row.data = what.data;
      row.time = isoLocal(d);
      if (what.type === "feed") {
        counts.feeds += 1;
        if (what.typed) { lastFormula = what.typed; if (!known.includes(what.typed)) known.push(what.typed); }
      } else if (what.data.wet && what.data.dirty) counts.both += 1;
      else if (what.data.wet) counts.wet += 1;
      else counts.dirty += 1;
      counts.entries += 1;
      days.add(ctx.date);
    });
    return { rows, counts, days: Array.from(days).sort() };
  }

  // "22 ml" / "0.75 oz", the same rounding Core.fmtAmount uses so the preview and the day sheet
  // agree on what a quarter ounce is.
  function fmtAmount(ml, unit) {
    if (unit === "oz") {
      const q = Math.round((ml / OZ_ML) * 4) / 4;
      return `${q === 0 && ml > 0 ? Math.round((ml / OZ_ML) * 100) / 100 : q} oz`;
    }
    return `${Math.round(ml)} ml`;
  }

  // One line of preview text for a row: what will be saved, or the date for a header, else "".
  function describe(row, unit) {
    if (!row) return "";
    if (row.kind === "header") return row.date || "";
    if (row.kind !== "entry" || !row.data) return "";
    if (row.type === "feed") {
      let ml = 0, formula = null;
      for (const b of row.data.bottles || []) { ml += Number(b.ml) || 0; if (b.formula && !formula) formula = b.formula; }
      return `${fmtAmount(ml, unit)} formula${formula ? ` · ${formula}` : ""}`;
    }
    const d = row.data;
    return d.wet && d.dirty ? "Wet + dirty" : d.wet ? "Wet" : d.dirty ? "Dirty" : "Diaper";
  }

  return { parse, describe, parseHeader, parseTime, parseWhat, fmtAmount };
})();

if (typeof module !== "undefined") module.exports = Bulk;
