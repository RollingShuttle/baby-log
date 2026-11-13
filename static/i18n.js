/* The PC page in English or Simplified Chinese.

   The page is built in English. This swaps every text and label that matches an entry of
   i18n/strings.json (the same table the iPhone app reads), including entries with {placeholders},
   and keeps doing so as the page redraws, through a MutationObserver. That way no line of app.js
   has to change for a label to be translated, and a label missing from the table simply stays in
   English. The choice is per PC: localStorage "bl.pc.lang" is "", "en" or "zh-Hans"; "" follows
   Windows' language. */
(function (root) {
  "use strict";
  const KEY = "bl.pc.lang";
  const ATTRS = ["placeholder", "title", "aria-label"];
  const SKIP = { SCRIPT: 1, STYLE: 1, TEXTAREA: 1 };

  function choice() {
    try { return root.localStorage ? root.localStorage.getItem(KEY) || "" : ""; } catch (e) { return ""; }
  }
  function setChoice(v) {
    try { root.localStorage.setItem(KEY, v); } catch (e) { /* private window: stays English */ }
  }
  /** "en" or "zh-Hans": the stored choice, else the system language. */
  function resolved(systemLang) {
    const c = choice();
    if (c) return c;
    const nav = systemLang != null ? systemLang : (root.navigator && root.navigator.language) || "";
    return String(nav).toLowerCase().indexOf("zh") === 0 ? "zh-Hans" : "en";
  }

  const escapeRe = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

  /** A translate(text) for one table: exact strings first, then the templates, longest first so
      the most specific one wins. Surrounding whitespace is kept; a value filling a placeholder is
      translated too ("{type} saved" with "Feed"). */
  function make(table) {
    const exact = new Map();
    const templates = [];
    for (const key of Object.keys(table || {})) {
      const e = table[key];
      if (!e || typeof e.en !== "string" || typeof e["zh-Hans"] !== "string") continue;
      const en = e.en.trim();
      const zh = e["zh-Hans"];
      if (!en || en === zh) continue;
      if (/\{[a-zA-Z]+\}/.test(en)) {
        // A template must carry words of its own, or "{a}" would match every text on the page.
        if (en.replace(/\{[a-zA-Z]+\}/g, "").replace(/[^A-Za-z]/g, "").length < 2) continue;
        const names = [];
        const body = escapeRe(en).replace(/\\\{([a-zA-Z]+)\\\}/g, (m, n) => { names.push(n); return "(.+?)"; });
        templates.push({ re: new RegExp("^" + body + "$"), names, zh, len: en.length });
      } else if (!exact.has(en)) {
        exact.set(en, zh);
      }
    }
    templates.sort((a, b) => b.len - a.len);

    function translate(text) {
      if (typeof text !== "string") return text;
      const lead = /^\s*/.exec(text)[0];
      const rest = text.slice(lead.length);
      const trail = /\s*$/.exec(rest)[0];
      const core = rest.slice(0, rest.length - trail.length);
      if (!core || !/[A-Za-z]/.test(core)) return text;
      if (exact.has(core)) return lead + exact.get(core) + trail;
      for (const t of templates) {
        const m = t.re.exec(core);
        if (!m) continue;
        let out = t.zh;
        t.names.forEach((n, i) => { out = out.split("{" + n + "}").join(translate(m[i + 1])); });
        return lead + out + trail;
      }
      return text;
    }
    return translate;
  }

  function translateAttrs(translate, node) {
    for (const a of ATTRS) {
      const v = node.getAttribute && node.getAttribute(a);
      if (v) {
        const t = translate(v);
        if (t !== v) node.setAttribute(a, t);
      }
    }
  }
  /** Translate a node and everything under it; a textarea (typed text) is left alone. */
  function apply(translate, node) {
    if (!node) return;
    if (node.nodeType === 3) {
      const p = node.parentNode;
      if (p && SKIP[p.nodeName]) return;
      const t = translate(node.nodeValue);
      if (t !== node.nodeValue) node.nodeValue = t;
      return;
    }
    if (node.nodeType !== 1 || SKIP[node.nodeName]) return;
    translateAttrs(translate, node);
    for (const c of Array.from(node.childNodes)) apply(translate, c);
  }

  async function start() {
    const lang = resolved();
    const doc = root.document;
    doc.documentElement.lang = lang === "zh-Hans" ? "zh-Hans" : "en";
    if (lang !== "zh-Hans") return;
    // Hidden until translated, so the English does not flash; shown regardless after 2 s.
    doc.documentElement.style.visibility = "hidden";
    const show = () => { doc.documentElement.style.visibility = ""; };
    const fallback = setTimeout(show, 2000);
    let table;
    try {
      const r = await fetch("/i18n/strings.json", { cache: "no-cache" });
      table = (await r.json()).strings;
    } catch (e) {
      clearTimeout(fallback);
      show();
      return;
    }
    const translate = make(table);
    apply(translate, doc.body);
    doc.title = translate(doc.title);
    new MutationObserver((muts) => {
      for (const m of muts) {
        if (m.type === "childList") m.addedNodes.forEach((n) => apply(translate, n));
        else if (m.type === "characterData") apply(translate, m.target);
        else if (m.type === "attributes") translateAttrs(translate, m.target);
      }
    }).observe(doc.body, { subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: ATTRS });
    clearTimeout(fallback);
    show();
  }

  const api = { make, resolved, choice, setChoice, start };
  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  } else {
    root.I18n = api;
    if (root.document) start();
  }
})(typeof window !== "undefined" ? window : globalThis);
