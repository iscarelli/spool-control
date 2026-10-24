/* In-page QR scanner (navbar button → #qrScanModal).
 *
 * Why: scanning labels with the phone's camera app opens a NEW browser tab per scan.
 * This scans inside the current page and shows the result (and the weighing form)
 * INSIDE the modal. It never navigates between scans, and keeps ONE MediaStream per
 * page load: on iOS the camera grant is tied to the open document, so a page load or
 * a second getUserMedia asks for permission again (see docs/ARMADILHAS.md).
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
  var cameraBox = document.getElementById('qrScanCamera');
  var resultBox = document.getElementById('qrScanResult');
  var manual = document.getElementById('qrScanManual');
  var weighForm = document.getElementById('qrWeighForm');
  var weighInput = document.getElementById('qrWeighInput');
  var weighMsg = document.getElementById('qrWeighMsg');
  var radios = modal.querySelectorAll('input[name="qrScanTarget"]');
  var canWeigh = modal.dataset.canWeigh === '1';
  var RESUME_IGNORE_MS = 2000;   // label still in front of the camera must not re-trigger

  var stream = null;          // ONE per page load; only 'pagehide' (or an ended track) drops it
  var streamPromise = null;   // getUserMedia in flight (avoid a 2nd request on quick reopen)
  var timer = null;
  var running = false;
  var jsqrPromise = null;
  var decoderPromise = null;
  var session = 0;            // invalidates stale async work after close/reopen/result
  var lookupSeq = 0;          // invalidates stale summary/weigh fetches
  var current = null;         // spool shown in the result panel
  var ignoreId = null, ignoreUntil = 0;

  function $(id) { return document.getElementById(id); }
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
      if (current) renderWeighForm();
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

  /* ---- camera lifetime ---- */

  // Pause decoding and detach the video, but KEEP the stream (and its permission).
  function pauseDecoding() {
    running = false;
    session++;
    if (timer) { clearTimeout(timer); timer = null; }
    try { video.pause(); } catch (e) { /* ignore */ }
    video.srcObject = null;
  }

  // Really release the camera (page going away).
  function releaseStream() {
    pauseDecoding();
    var s = stream;
    stream = null;
    streamPromise = null;
    if (s) s.getTracks().forEach(function (t) { t.stop(); });
  }

  function streamAlive() {
    if (!stream) return false;
    var tracks = stream.getVideoTracks();
    return tracks.length > 0 && tracks[0].readyState === 'live';
  }

  // The ONLY getUserMedia call. Reuses a live stream; a dead one is dropped first.
  function acquireStream() {
    if (streamAlive()) return Promise.resolve(stream);
    stream = null;
    if (!streamPromise) {
      streamPromise = navigator.mediaDevices.getUserMedia({
        video: { facingMode: 'environment' }, audio: false
      }).then(function (s) {
        stream = s;
        streamPromise = null;
        return s;
      }, function (err) { streamPromise = null; throw err; });
    }
    return streamPromise;
  }

  // Resolves to a function that decodes the current video frame -> Promise<text|null>.
  function makeDecoder() {
    if (decoderPromise) return decoderPromise;
    decoderPromise = (function () {
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
    })();
    decoderPromise.catch(function () { decoderPromise = null; });
    return decoderPromise;
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
        var id = parseSpoolId(text);
        if (id && id === ignoreId && Date.now() < ignoreUntil) { again(300); return; }
        if (!id) { setStatus(msg('msgUnrecognized'), true); again(800); return; }
        if (navigator.vibrate) { try { navigator.vibrate(50); } catch (e) { /* ignore */ } }
        showResult(id);
        return;
      }
      again(200);
    }, function () { again(200); });
  }

  // Attach the (existing or new) stream to the video and start decoding.
  function startScanning() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia || !window.isSecureContext) {
      setStatus(msg('msgNoCamera'), true);
      return;
    }
    setStatus(msg('msgStarting'), false);
    var mySession = ++session;
    acquireStream().then(function (s) {
      if (mySession !== session) return;   // stale: the stream stays for the next opening
      video.srcObject = s;
      var p = video.play();
      if (p && p.catch) p.catch(function () { /* muted + playsinline normally autoplays */ });
      return makeDecoder().then(function (decode) {
        if (mySession !== session) return;
        running = true;
        setStatus(msg('msgHint'), false);
        loop(decode, mySession);
      }, function () {
        if (mySession !== session) return;
        setStatus(msg('msgNoDecoder'), true);
      });
    }, function (err) {
      if (mySession !== session) return;
      var denied = err && (err.name === 'NotAllowedError' || err.name === 'SecurityError');
      setStatus(msg(denied ? 'msgDenied' : 'msgCameraError'), true);
    });
  }

  /* ---- result panel (no navigation) ---- */

  function showCameraView() {
    resultBox.classList.add('d-none');
    cameraBox.classList.remove('d-none');
  }

  function renderGrams(d) {
    $('qrResGrams').textContent = d.remaining_g + 'g';
    var extra = d.weighed ? (d.nominal_g > 0 ? ' · ' + d.pct + '% ' + msg('msgRemaining') : '')
                          : ' · ' + msg('msgUnweighed');
    $('qrResNominal').textContent = msg('msgNominal').replace('{n}', d.nominal_g) + extra;
  }

  function renderWeighForm() {
    var show = !!(canWeigh && getTarget() === 'weigh' && current);
    weighForm.classList.toggle('d-none', !show);
    if (show) {
      weighInput.value = '';
      try { weighInput.focus(); } catch (e) { /* ignore */ }
    }
  }

  function renderResult(d) {
    current = d;
    var sw = $('qrResSwatch');
    sw.classList.toggle('sc-swatch-translucent', !!d.translucent);
    sw.classList.toggle('sc-swatch-dual', !!d.color_hex2);
    sw.style.setProperty('--sw-color', d.color_hex || '#e0e0e0');
    if (d.color_hex2) sw.style.setProperty('--sw-color2', d.color_hex2);
    else sw.style.removeProperty('--sw-color2');
    $('qrResName').textContent = [d.material, d.brand].filter(Boolean).join(' · ');
    $('qrResColor').textContent = [d.family, d.color_name].filter(Boolean).join(' · ');
    $('qrResCode').textContent = d.code;
    var fin = $('qrResFinished');
    fin.textContent = msg('msgFinished');
    fin.classList.toggle('d-none', d.active);
    renderGrams(d);
    $('qrResWeighed').textContent = d.last_weighed_at ? msg('msgWeighedOn') + ' ' + d.last_weighed_at : '';
    $('qrScanOpen').setAttribute('href', destination(d.id, 'detail'));
    weighMsg.textContent = '';
    weighMsg.className = 'small mt-2';
  }

  function jsonResult(r) {
    return r.json().catch(function () { return {}; }).then(function (d) {
      return { status: r.status, d: d };
    });
  }

  function showResult(id) {
    pauseDecoding();
    var seq = ++lookupSeq;
    ignoreId = id;
    fetch('/spools/' + id + '/summary.json', {
      headers: { 'Accept': 'application/json' }, credentials: 'same-origin'
    }).then(jsonResult).then(function (res) {
      if (seq !== lookupSeq) return;
      if (res.status === 200 && res.d && res.d.ok) {
        cameraBox.classList.add('d-none');
        resultBox.classList.remove('d-none');
        renderResult(res.d);
        renderWeighForm();
      } else {
        // Stay on the camera view and keep scanning.
        setStatus(msg(res.status === 404 ? 'msgNotFound' : 'msgLookupFailed'), true);
        resumeScanning(true);
      }
    }, function () {
      if (seq !== lookupSeq) return;
      setStatus(msg('msgLookupFailed'), true);
      resumeScanning(true);
    });
  }

  // "Ler próximo": same stream, no new getUserMedia.
  function resumeScanning(keepStatus) {
    ++lookupSeq;
    current = null;
    ignoreUntil = Date.now() + RESUME_IGNORE_MS;
    var text = statusEl.textContent, err = statusEl.classList.contains('text-danger');
    showCameraView();
    startScanning();
    if (keepStatus === true) setStatus(text, err);
  }

  weighForm.addEventListener('submit', function (e) {
    e.preventDefault();
    if (!current) return;
    var raw = weighInput.value.trim().replace(',', '.');
    var gross = parseFloat(raw);
    if (!raw || !isFinite(gross) || gross <= 0) { weighInput.focus(); return; }
    var btn = $('qrWeighSave');
    btn.disabled = true;
    var seq = lookupSeq;
    fetch('/spools/' + current.id + '/weigh.json', {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
      body: JSON.stringify({ gross_weight_g: gross })
    }).then(jsonResult).then(function (res) {
      btn.disabled = false;
      if (seq !== lookupSeq) return;
      if (res.status === 200 && res.d && res.d.ok) {
        renderResult(res.d);
        weighForm.classList.add('d-none');
        weighMsg.textContent = msg('msgSaved');
        weighMsg.className = 'small mt-2 text-success';
      } else {
        weighMsg.textContent = (res.d && res.d.error && res.status === 422) ? res.d.error : msg('msgSaveFailed');
        weighMsg.className = 'small mt-2 text-danger';
        weighInput.focus();
      }
    }, function () {
      btn.disabled = false;
      weighMsg.textContent = msg('msgSaveFailed');
      weighMsg.className = 'small mt-2 text-danger';
    });
  });

  $('qrScanNext').addEventListener('click', function () { resumeScanning(false); });

  /* ---- typed fallback (no camera / denied) ---- */

  function lookupTyped() {
    var raw = manual.value.trim();
    var id = /^\d+$/.test(raw) ? String(parseInt(raw, 10)) : parseSpoolId(raw);
    if (!id || id === '0') { setStatus(msg('msgUnrecognized'), true); return; }
    manual.value = '';
    showResult(id);
  }
  manual.addEventListener('keydown', function (e) {
    if (e.key === 'Enter') { e.preventDefault(); lookupTyped(); }
  });
  $('qrScanManualGo').addEventListener('click', lookupTyped);

  /* ---- lifecycle ---- */

  modal.addEventListener('shown.bs.modal', function () {
    syncRadios();
    ++lookupSeq;
    current = null;
    ignoreUntil = 0;
    showCameraView();
    startScanning();
  });
  // Closing the modal pauses decoding but keeps the stream alive: iOS ties the grant
  // to the document, and stopping the tracks then asking again prompts again.
  modal.addEventListener('hidden.bs.modal', function () {
    ++lookupSeq;
    pauseDecoding();
    setStatus('', false);
  });
  // iOS may kill the track on screen lock: drop a dead stream so the next opening asks again.
  document.addEventListener('visibilitychange', function () {
    if (document.visibilityState !== 'visible') return;
    if (stream && !streamAlive()) {
      stream = null;
      if (modal.classList.contains('show') && !current) startScanning();
    }
  });
  // Leaving the page (incl. bfcache): the only place the camera light goes off.
  window.addEventListener('pagehide', releaseStream);
})();
