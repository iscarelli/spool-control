/* Detects a page that is older than the server (tab restored from bfcache or
   from the phone's tab history) and reloads it, or shows a banner when the
   user is editing. Decision logic is a pure function so it can be tested. */
(function () {
  var RELOAD_GAP_MS = 5 * 60 * 1000;
  var CHECK_GAP_MS = 60 * 1000;

  /* -> 'reload' | 'banner' | 'nothing' */
  function decide(pageVersion, serverVersion, isEditing, lastReloadTs, now) {
    if (!pageVersion || !serverVersion || pageVersion === serverVersion) return 'nothing';
    if (isEditing) return 'banner';
    if (lastReloadTs && now - lastReloadTs < RELOAD_GAP_MS) return 'banner';
    return 'reload';
  }

  var api = { decide: decide };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (typeof document === 'undefined' || !document.body) return;

  var pageVersion = document.body.dataset.appVersion;
  if (!pageVersion) return;

  var dirty = false, lastCheck = 0;
  document.addEventListener('input', function () { dirty = true; }, true);

  function isEditing() {
    var a = document.activeElement;
    var focused = a && /^(INPUT|TEXTAREA|SELECT)$/.test(a.tagName);
    return dirty || !!focused;
  }

  function check(force) {
    var now = Date.now();
    if (!force && now - lastCheck < CHECK_GAP_MS) return;
    lastCheck = now;
    fetch('/health', { cache: 'no-store' })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        var last = 0;
        try { last = parseInt(sessionStorage.getItem('sc-version-reload') || '0', 10); } catch (e) {}
        var act = decide(pageVersion, d && d.version, isEditing(), last, Date.now());
        if (act === 'reload') {
          try { sessionStorage.setItem('sc-version-reload', String(Date.now())); } catch (e) {}
          location.reload();
        } else if (act === 'banner') {
          var b = document.getElementById('scUpdateBanner');
          if (b) b.hidden = false;
        }
      })
      .catch(function () { /* offline / restarting: stay silent */ });
  }

  window.addEventListener('pageshow', function (e) { if (e.persisted) check(true); });
  document.addEventListener('visibilitychange', function () {
    if (document.visibilityState === 'visible') check(false);
  });
  var btn = document.getElementById('scUpdateReload');
  if (btn) btn.addEventListener('click', function () { location.reload(); });
})();
