/* A nursery at 3 a.m. may have no signal. The shell is cached so the app opens and logs a feed
   with no connection at all (SPEC.md §7.5). Journal files are never cached — they are read through
   Graph and held in IndexedDB. Uploads are never cached — they go through the queue.
   Bump VERSION on every change to docs/, or the old shell is served until the visit after next. */
const VERSION = "v7";
const SHELL = "shell-" + VERSION;
const SHELL_FILES = [
  "./", "./index.html", "./style.css", "./config.js",
  "./core.js", "./graph.js", "./store.js", "./sync.js", "./app.js",
  "./manifest.webmanifest", "./icon-180.png",
];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(SHELL).then((c) => c.addAll(SHELL_FILES)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys()
    .then((keys) => Promise.all(keys.filter((k) => k !== SHELL).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET") return;                 // never cache a write
  if (url.origin !== self.location.origin) return;        // Graph, the download host and the CDN go straight out

  e.respondWith(
    caches.match(e.request).then((hit) => {
      const live = fetch(e.request).then((res) => {
        if (res && res.ok) {
          const copy = res.clone();
          caches.open(SHELL).then((c) => c.put(e.request, copy));
        }
        return res;
      }).catch(() => hit);
      return hit || live;                                 // cache first, refresh behind
    })
  );
});
