/* Baby Log — OneDrive transport (SPEC.md §7.1).

   MSAL in the browser, authorization-code flow with PKCE, and exactly one scope:
   Files.ReadWrite.AppFolder. That scope is the enforcement, not app discipline — it grants access
   to OneDrive/Apps/Baby Log/ and nothing else in the drive, so `Baby Log.xlsx` in Yisen File is
   not merely off-limits to this app, it is invisible to it.

   Sign-in uses redirect rather than a popup: installed to the home screen there is no browser
   chrome, and popups in a standalone web app are unreliable at best.

   MSAL is loaded on demand. The app shell must open and log a feed with no network at all, so
   nothing here is on the critical path until you actually sign in.

   Every call ends in one of three ways the caller can act on: `retryable` (the network, 408, 429,
   5xx — try later; 429/503 also park every Graph call until Retry-After has passed), `signed_out`
   (401/403 — stop background sync until someone taps Sign in) or `permanent` (any other 4xx — the
   caller decides). The classification and the backoff arithmetic live here, next to the calls
   that use them; sync.js re-exports them so tests/test_sync.py can run them under Node. */
"use strict";

/** Thrown by token({interactive: false}) — the background calls — instead of redirecting. */
class SignedOutError extends Error {
  constructor(message) {
    super(message || "signed out");
    this.name = "SignedOutError";
    this.kind = "signed_out";
    this.status = 401;
    this.code = "signedOut";
  }
}

/** A failed Graph call: the HTTP status, Graph's own error code and message, and the kind. */
class GraphError extends Error {
  constructor(fields) {
    super(fields.message || `Graph ${fields.status || "request"} failed`);
    this.name = "GraphError";
    this.status = fields.status || 0;
    this.code = fields.code || null;
    this.kind = fields.kind || "retryable";
    this.retryAfter = fields.retryAfter == null ? null : fields.retryAfter;
  }
}

const Graph = (() => {
  let msal = null;
  let client = null;
  let account = null;
  let loading = null;
  let signedOut = false;   // mirrors meta.signed_out; set by a silent failure, cleared by a working token
  let attempt = 0;         // consecutive 429/503 answers, for the doubling backoff

  const configured = () => !!(CONFIG.CLIENT_ID && CONFIG.CLIENT_ID.trim());

  // Store is loaded before this file, but only referenced at call time so the transport also
  // loads headless (tests) and before the store has opened.
  const meta = () => (typeof Store !== "undefined" ? Store.meta() : {});
  const setMeta = (patch) => { if (typeof Store !== "undefined") Store.setMeta(patch); };

  function loadScript(src) {
    return new Promise((resolve, reject) => {
      const s = document.createElement("script");
      s.src = src;
      s.onload = resolve;
      s.onerror = () => reject(new Error("could not load the Microsoft sign-in library"));
      document.head.append(s);
    });
  }

  async function ensure() {
    if (client) return client;
    if (!configured()) throw new Error("not configured");
    if (!loading) {
      loading = (async () => {
        if (!window.msal) await loadScript(CONFIG.MSAL_SRC);
        msal = window.msal;
        client = new msal.PublicClientApplication({
          auth: {
            clientId: CONFIG.CLIENT_ID,
            authority: CONFIG.AUTHORITY,
            redirectUri: location.href.split("#")[0].split("?")[0],
          },
          cache: { cacheLocation: "localStorage" },
        });
        await client.initialize();
        const result = await client.handleRedirectPromise();
        if (result?.account) client.setActiveAccount(result.account);
        account = client.getActiveAccount() || client.getAllAccounts()[0] || null;
        if (account) client.setActiveAccount(account);
        // An account in the cache is worth one silent try per app open, even if the last run
        // ended signed out: the next token() call decides again.
        if (account) markSignedIn();
        return client;
      })();
    }
    return loading;
  }

  function markSignedIn() {
    signedOut = false;
    attempt = 0;
    setMeta({ signed_out: false, signed_in_as: account ? account.username || null : null });
  }
  function markSignedOut() {
    signedOut = true;
    setMeta({ signed_out: true });
  }

  /** Safe to call on boot: resolves to false when not configured or not signed in. */
  async function resume() {
    if (!configured()) return false;
    try {
      await ensure();
      return !!account;
    } catch { return false; }
  }

  /** The one interactive path: a tap on the pill or Settings → Sign in, never a background call. */
  async function signIn() {
    await ensure();
    // Refresh tokens for browser apps are capped at 24 hours and Safari blocks the hidden-iframe
    // renewal, so this reappears about once a day. It never blocks logging — only syncing.
    await client.loginRedirect({ scopes: CONFIG.SCOPES });
  }

  async function signOut() {
    if (!client) return;
    setMeta({ signed_out: true, signed_in_as: null });
    await client.logoutRedirect({ account });
  }

  // MSAL's own error taxonomy: interaction_required and friends mean the session is really gone;
  // a failed network round-trip to the token endpoint does not, and must not read as signed out.
  const NETWORKISH = /network|timeout|endpoints_resolution|post_request_failed|monitor_window/i;
  function needsInteraction(e) {
    if (!e) return true;
    if (e.name === "InteractionRequiredAuthError") return true;
    return !NETWORKISH.test(String(e.errorCode || e.message || ""));
  }

  /** An access token. Background calls pass nothing (or {interactive: false}) and get a
      SignedOutError on silent failure — never a redirect, which would tear down an open editor.
      Only signIn() and an explicit {interactive: true} may leave the page. */
  async function token(opts = {}) {
    await ensure();
    if (!account) {
      markSignedOut();
      throw new SignedOutError("not signed in");
    }
    try {
      const r = await client.acquireTokenSilent({ scopes: CONFIG.SCOPES, account });
      if (signedOut) markSignedIn();
      return r.accessToken;
    } catch (e) {
      if (opts.interactive) {
        await client.acquireTokenRedirect({ scopes: CONFIG.SCOPES, account });
        throw new SignedOutError("sign-in required");
      }
      if (needsInteraction(e)) {
        markSignedOut();
        throw new SignedOutError(e && (e.errorMessage || e.message) || "sign-in required");
      }
      throw new GraphError({ status: 0, code: e.errorCode || e.name || "network",
                             message: e.message || "could not reach the sign-in service", kind: "retryable" });
    }
  }

  // -- failure rules (pure; sync.js re-exports them for the Node tests) ------------------------

  /** retryable / signed_out / permanent for an HTTP status (0 = the network). `body` is the
      parsed Graph error, kept in the signature so a code-based rule has somewhere to go. */
  function classify(status, body) {   // eslint-disable-line no-unused-vars
    const s = Number(status) || 0;
    if (s === 401 || s === 403) return "signed_out";
    if (s === 0 || s === 408 || s === 429 || s >= 500) return "retryable";
    if (s >= 400) return "permanent";
    return "retryable";               // a 1xx/3xx the browser let through: nothing to act on, try again
  }

  /** How long to park Graph: Retry-After (seconds, or an HTTP date) when the header is exposed,
      otherwise 10 s doubling per consecutive answer and capped at five minutes. */
  function backoffMs(retryAfter, attemptNo = 0) {
    if (retryAfter != null && String(retryAfter).trim() !== "") {
      const s = Number(retryAfter);
      if (Number.isFinite(s) && s >= 0) return Math.max(1000, s * 1000);
      const at = Date.parse(retryAfter);
      if (!Number.isNaN(at)) return Math.max(1000, at - Date.now());
    }
    return Math.min(300000, 10000 * Math.pow(2, Math.max(0, Number(attemptNo) || 0)));
  }

  /** Milliseconds since the epoch until which every Graph call is suspended, or 0. */
  function backoffUntil() {
    const at = Date.parse(meta().backoff_until || "");
    return Number.isNaN(at) || at <= Date.now() ? 0 : at;
  }

  // -- the calls --------------------------------------------------------------------------------

  const enc = (path) => path.split("/").map(encodeURIComponent).join("/");
  const url = (path) => `${CONFIG.GRAPH}/me/drive/special/approot:/${enc(path)}:/content`;
  const childrenUrl = (path) => path
    ? `${CONFIG.GRAPH}/me/drive/special/approot:/${enc(path)}:/children`
    : `${CONFIG.GRAPH}/me/drive/special/approot/children`;
  const LIST_QUERY = "?$select=id,name,size,eTag,file,folder,@microsoft.graph.downloadUrl&$top=500";

  /** One fetch with the failure rules applied. Honours the backoff before touching the network. */
  async function request(target, init, what) {
    const until = backoffUntil();
    if (until) {
      throw new GraphError({ status: 0, code: "backoff", kind: "retryable",
                             message: `waiting ${Math.ceil((until - Date.now()) / 1000)} s after OneDrive asked us to slow down` });
    }
    let r;
    try {
      r = await fetch(target, init);
    } catch (e) {
      throw new GraphError({ status: 0, code: "network", kind: "retryable",
                             message: (e && e.message) || `network error ${what}` });
    }
    if (r.ok) { attempt = 0; return r; }
    throw await failure(r, what);
  }

  async function failure(r, what) {
    let body = null;
    try { body = await r.json(); } catch { /* not every error carries a body */ }
    const err = (body && body.error) || {};
    const kind = classify(r.status, body);
    let retryAfter = null;
    if (r.status === 429 || r.status === 503) {
      // Retry-After is only readable when Graph exposes it to CORS; otherwise the doubling applies.
      retryAfter = r.headers.get("Retry-After");
      const ms = backoffMs(retryAfter, attempt);
      attempt += 1;
      setMeta({ backoff_until: new Date(Date.now() + ms).toISOString() });
    }
    if (kind === "signed_out") markSignedOut();
    return new GraphError({
      status: r.status, kind, retryAfter,
      code: err.code || String(r.status),
      message: err.message ? `${err.message} (${r.status} ${what})` : `${r.status} ${what}`,
    });
  }

  /** The file's text via :/content with the bearer token, or null when nothing is there. */
  async function getContent(path) {
    const t = await token();
    try {
      const r = await request(url(path), { headers: { Authorization: `Bearer ${t}` } }, `reading ${path}`);
      return r.text();
    } catch (e) {
      if (e.status === 404) return null;               // nothing written there yet
      throw e;
    }
  }

  async function getJSON(path) {
    const text = await getContent(path);
    return text === null ? null : JSON.parse(text);
  }

  /** A listed file's bytes. The download URL is pre-authenticated, so the fetch carries no
      headers at all: an Authorization header would force a CORS preflight that the download host
      refuses. The URL is never stored — it expires within the hour. Falls back to :/content. */
  async function getText(downloadUrl, path) {
    if (downloadUrl) {
      try {
        const r = await fetch(downloadUrl);
        if (r.ok) return await r.text();
      } catch { /* fall through to the authenticated read */ }
    }
    if (!path) throw new GraphError({ status: 0, code: "download", kind: "retryable", message: "download failed" });
    return getContent(path);
  }

  /** [{name, size, eTag, isFolder, downloadUrl}] for a folder under the app root, following
      @odata.nextLink as Graph hands it out (it already carries the query). 404 → []. */
  async function listFolder(path) {
    const t = await token();
    let next = childrenUrl(path) + LIST_QUERY;
    const out = [];
    while (next) {
      let r;
      try {
        r = await request(next, { headers: { Authorization: `Bearer ${t}` } }, `listing ${path}`);
      } catch (e) {
        if (e.status === 404) return [];
        throw e;
      }
      const j = await r.json();
      for (const it of j.value || []) {
        out.push({
          name: it.name, size: it.size, eTag: it.eTag,
          isFolder: !!it.folder,
          downloadUrl: it["@microsoft.graph.downloadUrl"] || null,
        });
      }
      next = j["@odata.nextLink"] || null;
    }
    return out;
  }

  /** Create one folder under the app root; an existing one (409) is fine. */
  async function createFolder(dir) {
    const t = await token();
    const i = dir.lastIndexOf("/");
    const parent = i < 0 ? "" : dir.slice(0, i);
    const name = dir.slice(i + 1);
    try {
      await request(childrenUrl(parent), {
        method: "POST",
        headers: { Authorization: `Bearer ${t}`, "Content-Type": "application/json" },
        body: JSON.stringify({ name, folder: {}, "@microsoft.graph.conflictBehavior": "fail" }),
      }, `creating ${dir}`);
    } catch (e) {
      if (e.status !== 409) throw e;
    }
  }

  /** Idempotent by design: a retry after a dropped connection writes the same bytes to the same
      path, so a failed upload can always simply be repeated (SPEC.md §1.2). A 404 means the day
      folder is not there yet: create it and try once more. */
  async function putJSON(path, body) {
    const t = await token();
    const init = {
      method: "PUT",
      headers: { Authorization: `Bearer ${t}`, "Content-Type": "application/json" },
      // _file and friends are reader bookkeeping and never go into the journal.
      body: JSON.stringify(body, (k, v) => (k.startsWith("_") ? undefined : v)),
    };
    try {
      return await (await request(url(path), init, `writing ${path}`)).json();
    } catch (e) {
      if (e.status !== 404 || path.indexOf("/") < 0) throw e;
      await createFolder(path.slice(0, path.lastIndexOf("/")));
      return (await request(url(path), init, `writing ${path}`)).json();
    }
  }

  return {
    SignedOutError,
    GraphError,
    configured,
    resume,
    signIn,
    signOut,
    token,
    getJSON,
    getText,
    putJSON,
    listFolder,
    createFolder,
    classify,
    backoffMs,
    backoffUntil,
    isSignedIn: () => !!account && !signedOut,
    who: () => account?.username || null,
  };
})();

if (typeof module !== "undefined") module.exports = Graph;
