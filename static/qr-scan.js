/* In-page QR scanner (navbar button → #qrScanModal).
 *
 * Why: scanning labels with the phone's camera app opens a NEW browser tab per scan.
 * This scans inside the current page and navigates in the SAME tab.
 *
 * Decoding: native BarcodeDetector when present (Chrome/Android); otherwise jsQR
 * (vendored same-origin, loaded lazily — iOS Safari has no BarcodeDetector).
 * No inline handlers (blocked by the nonce CSP); listeners are bound here.
 */
(function () {
  'use strict';

  var PREF_KEY = 'sc.scanTarget';          // 'weigh' | 'detail' (per device)
  var SPOOL_PATH = /^\/spools\/(\d+)\/?$/;

  /* Pure: decoded text -> spool id (string) or null. Accepts a URL on ANY host
   * (labels may have been printed with another base URL) or a bare path; only the
   * pathname is used — we never navigate to the external URL itself. */
  function parseSpoolId(text) {
    if (typeof text !== 'string') return null;
    var path;
    try { path = new URL(text.trim(), 'http://placeholder.invalid').pathname; }
    catch (e) { return null; }
    var m = SPOOL_PATH.exec(path);
    return m ? m[1] : null;
  }

  function destination(id, target) {
    return '/spools/' + id + (target === 'weigh' ? '/weigh' : '');
  }

  var api = { parseSpoolId: parseSpoolId, destination: destination };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (typeof window !== 'undefined') window.ScQrScan = api;

  if (typeof document === 'undefined') return;
  var modal = document.getElementById('qrScanModal');
  if (!modal) return;

  var video = document.getElementById('qrScanVideo');
  var canvas = document.getElementById('qrScanCanvas');
  var statusEl = document.getElementById('qrScanStatus');
  var radios = modal.querySelectorAll('input[name="qrScanTarget"]');
  var canWeigh = modal.dataset.canWeigh === '1';

  var stream = null;
  var timer = null;
  var running = false;
  var jsqrPromise = null;
  var session = 0;      // invalidates stale async work after close/reopen

  function msg(key) { return modal.dataset[key] || ''; }
  function setStatus(text, isError) {
    statusEl.textContent = text;
    statusEl.classList.toggle('text-danger', !!isError);
    statusEl.classList.toggle('text-body-secondary', !isError);
  }

  function getTarget() {
    var v = null;
    try { v = localStorage.getItem(PREF_KEY); } catch (e) { /* storage blocked */ }
    return (v === 'weigh' && canWeigh) ? 'weigh' : 'detail';
  }
  function syncRadios() {
    var t = getTarget();
    radios.forEach(function (r) { r.checked = (r.value === t); });
  }
  radios.forEach(function (r) {
    r.addEventListener('change', function () {
      if (!r.checked) return;
      try { localStorage.setItem(PREF_KEY, r.value); } catch (e) { /* ignore */ }
    });
  });

  function loadJsQR() {
    if (window.jsQR) return Promise.resolve(window.jsQR);
    if (!jsqrPromise) {
      jsqrPromise = new Promise(function (resolve, reject) {
        var s = document.createElement('script');
        s.src = modal.dataset.jsqrSrc;
        s.onload = function () { window.jsQR ? resolve(window.jsQR) : reject(new Error('jsQR missing')); };
        s.onerror = function () { jsqrPromise = null; reject(new Error('jsQR load failed')); };
        document.head.appendChild(s);
      });
    }
    return jsqrPromise;
  }

  function stopCamera() {
    running = false;
    session++;
    if (timer) { clearTimeout(timer); timer = null; }
    if (stream) {
      stream.getTracks().forEach(function (t) { t.stop(); });
      stream = null;
    }
    try { video.pause(); } catch (e) { /* ignore */ }
    video.srcObject = null;
  }

  function handleText(text) {
    var id = parseSpoolId(text);
    if (!id) { setStatus(msg('msgUnrecognized'), true); return false; }
    if (navigator.vibrate) { try { navigator.vibrate(50); } catch (e) { /* ignore */ } }
    var dest = destination(id, getTarget());
    stopCamera();
    window.location.assign(dest);
    return true;
  }

  // Resolves to a function that decodes the current video frame -> Promise<text|null>.
  function makeDecoder() {
    if ('BarcodeDetector' in window) {
      try {
        var detector = new window.BarcodeDetector({ formats: ['qr_code'] });
        return Promise.resolve(function () {
          return detector.detect(video).then(function (codes) {
            return codes.length ? codes[0].rawValue : null;
          });
        });
      } catch (e) { /* fall through to jsQR */ }
    }
    return loadJsQR().then(function (jsQR) {
      var ctx = canvas.getContext('2d', { willReadFrequently: true });
      return function () {
        var w = video.videoWidth, h = video.videoHeight;
        if (!w || !h) return Promise.resolve(null);
        // Downscale: decoding cost grows with pixels; a label QR is large in frame.
        var scale = Math.min(1, 640 / Math.max(w, h));
        canvas.width = Math.round(w * scale);
        canvas.height = Math.round(h * scale);
        ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
        var img = ctx.getImageData(0, 0, canvas.width, canvas.height);
        var res = jsQR(img.data, img.width, img.height, { inversionAttempts: 'dontInvert' });
        return Promise.resolve(res ? res.data : null);
      };
    });
  }

  function loop(decode, mySession) {
    if (!running || mySession !== session) return;
    var again = function (delay) {
      if (running && mySession === session) {
        timer = setTimeout(function () { loop(decode, mySession); }, delay);
      }
    };
    if (video.readyState < 2) { again(200); return; }
    decode().then(function (text) {
      if (mySession !== session) return;
      if (text) {
        if (handleText(text)) return;
        again(800);          // unrecognized: keep scanning, but don't hammer the same code
        return;
      }
      again(200);
    }, function () { again(200); });
  }

  function start() {
    syncRadios();
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia || !window.isSecureContext) {
      setStatus(msg('msgNoCamera'), true);
      return;
    }
    setStatus(msg('msgStarting'), false);
    var mySession = ++session;
    navigator.mediaDevices.getUserMedia({
      video: { facingMode: { ideal: 'environment' } }, audio: false
    }).then(function (s) {
      if (mySession !== session) { s.getTracks().forEach(function (t) { t.stop(); }); return; }
      stream = s;
      video.srcObject = s;
      var p = video.play();
      if (p && p.catch) p.catch(function () { /* muted + playsinline normally autoplays */ });
      return makeDecoder().then(function (decode) {
        if (mySession !== session) return;
        running = true;
        setStatus(msg('msgHint'), false);
        loop(decode, mySession);
      }, function () {
        setStatus(msg('msgNoDecoder'), true);
        stopCamera();
      });
    }, function (err) {
      if (mySession !== session) return;
      var denied = err && (err.name === 'NotAllowedError' || err.name === 'SecurityError');
      setStatus(msg(denied ? 'msgDenied' : 'msgCameraError'), true);
    });
  }

  modal.addEventListener('shown.bs.modal', start);
  modal.addEventListener('hidden.bs.modal', function () { stopCamera(); setStatus('', false); });
  // Leaving via back/bfcache: make sure the camera light goes off.
  window.addEventListener('pagehide', stopCamera);
})();
