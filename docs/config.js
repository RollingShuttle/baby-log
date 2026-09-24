/* Baby Log — phone client configuration.

   CLIENT_ID is the Application (client) ID from the Entra app registration in guide/SETUP.md §1.
   It is a public identifier, not a secret: any browser-based Microsoft sign-in ships it in plain
   JavaScript, and it is useless on its own — the registration is locked to the
   Files.ReadWrite.AppFolder scope, to personal accounts, and to its own redirect URIs.

   The committed value is blank on purpose (tests/test_sync.py and tests/test_phone.py enforce it);
   fill it in on deploy. The GitHub Pages URL, with its trailing slash, must be registered as a
   Single-page application redirect URI, or sign-in stops with a redirect_uri mismatch. */
const CONFIG = {
  CLIENT_ID: "",
  AUTHORITY: "https://login.microsoftonline.com/consumers",
  SCOPES: ["Files.ReadWrite.AppFolder"],
  MSAL_SRC: "https://cdn.jsdelivr.net/npm/@azure/msal-browser@4/lib/msal-browser.min.js",
  GRAPH: "https://graph.microsoft.com/v1.0",
  APP: "Baby Log",
};

if (typeof module !== "undefined") module.exports = CONFIG;
