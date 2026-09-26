/* Baby Log — phone client configuration.

   CLIENT_ID is the Application (client) ID from the Entra app registration in guide/SETUP.md §1.
   It is a public identifier, not a secret: any browser-based Microsoft sign-in ships it in plain
   JavaScript, and it is useless on its own — the registration is locked to the
   Files.ReadWrite.AppFolder scope, to personal accounts, and to its own redirect URIs.

   Filled in 26 Sep 2026 from the owner's "Baby Log" registration (tests/test_sync.py and
   tests/test_phone.py check it looks like a GUID). https://rollingshuttle.github.io/baby-log/ —
   trailing slash included — is registered as its Single-page application redirect URI; changing
   the Pages address means adding the new one there first, or sign-in stops with a
   redirect_uri mismatch. */
const CONFIG = {
  CLIENT_ID: "8abd1f7d-91c4-4622-94ee-546adfa9ec8b",
  AUTHORITY: "https://login.microsoftonline.com/consumers",
  SCOPES: ["Files.ReadWrite.AppFolder"],
  MSAL_SRC: "https://cdn.jsdelivr.net/npm/@azure/msal-browser@4/lib/msal-browser.min.js",
  GRAPH: "https://graph.microsoft.com/v1.0",
  APP: "Baby Log",
};

if (typeof module !== "undefined") module.exports = CONFIG;
