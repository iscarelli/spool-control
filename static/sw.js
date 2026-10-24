// Minimal pass-through service worker. It exists so iOS treats the home-screen app as a real
// installed app (own entry in Settings) instead of a Safari bookmark; without it, camera
// permission is not remembered and is asked again on every scan. No caching. Push and
// notificationclick are at the end of the file.
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));
// Only GET is intercepted. Any other method returns without respondWith, so the browser sends
// it itself: WebKit loses the body of a multipart POST (e.g. the backup restore zip) that a
// worker re-issues.
self.addEventListener("fetch", (event) => {
  if (event.request.method !== "GET") return;
  event.respondWith(fetch(event.request));
});

// Push. An unreadable payload still shows something: a push the page cannot display makes some
// browsers revoke the subscription (userVisibleOnly).
self.addEventListener("push", (event) => {
  let title = "Spool";
  const options = { icon: "/static/icons/android-chrome-192x192.png" };
  try {
    const data = event.data ? event.data.json() : {};
    if (data && typeof data.title === "string" && data.title) title = data.title;
    if (data && typeof data.body === "string") options.body = data.body;
    if (data && typeof data.url === "string") options.data = { url: data.url };
  } catch (e) { /* generic notification below */ }
  event.waitUntil(self.registration.showNotification(title, options));
});

// Tap: only a URL of this origin is followed (anything else lands on the root). An open window of
// the app is navigated and focused; otherwise a new window opens.
self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  let target = self.location.origin + "/";
  const url = event.notification.data && event.notification.data.url;
  if (typeof url === "string") {
    try {
      const u = new URL(url, self.location.origin);
      if (u.origin === self.location.origin) target = u.href;
    } catch (e) { /* keep the root */ }
  }
  event.waitUntil(self.clients.matchAll({ type: "window", includeUncontrolled: true }).then(async (list) => {
    for (const c of list) {
      if (!c.url.startsWith(self.location.origin)) continue;
      try {
        const nav = "navigate" in c ? await c.navigate(target) : null;
        if (nav) return nav.focus();
        if ("focus" in c) await c.focus();
      } catch (e) { /* fall through to a new window */ }
    }
    return self.clients.openWindow(target);
  }));
});
