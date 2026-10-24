// Minimal pass-through service worker. It exists so iOS treats the home-screen app as a real
// installed app (own entry in Settings) instead of a Safari bookmark; without it, camera
// permission is not remembered and is asked again on every scan. No caching, no push.
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));
// Only GET is intercepted. Any other method returns without respondWith, so the browser sends
// it itself: WebKit loses the body of a multipart POST (e.g. the backup restore zip) that a
// worker re-issues.
self.addEventListener("fetch", (event) => {
  if (event.request.method !== "GET") return;
  event.respondWith(fetch(event.request));
});
