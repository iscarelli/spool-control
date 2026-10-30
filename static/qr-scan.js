/* In-page QR scanner (navbar button → #qrScanModal).
 *
 * Why: scanning labels with the phone's camera app opens a NEW browser tab per scan.
 * This scans inside the current page and shows the spool INSIDE the modal. It never
 * navigates between scans: on iPhone the camera grant lives only for the page load
 * (WebKit bug 215884), so one getUserMedia per modal opening, stream kept between scans.
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
  var decoder = null;   // kept between scans (stream stays open)
  var token = 0;        // invalidates stale summary/save fetches
  var current = null;   // spool id shown in the result panel
  var ignoreId = null, ignoreUntil = 0;   // same-QR debounce after "scan next"
  var DEBOUNCE_MS = 2000;
  var $ = function (id) { return document.getElementById(id); };
  var resultEl = $('qrScanResult'), weighForm = $('qrWeighForm'), weighInput = $('qrWeighInput');
  var resMsg = $('qrResMsg');

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
    token++;
    decoder = null;
    if (timer) { clearTimeout(timer); timer = null; }
    if (stream) {
      stream.getTracks().forEach(function (t) { t.stop(); });
      stream = null;
    }
    try { video.pause(); } catch (e) { /* ignore */ }
    video.srcObject = null;
  }

  function pauseDecoding() {
    running = false;
    if (timer) { clearTimeout(timer); timer = null; }
  }

  function setMsg(text, kind) {
    resMsg.textContent = text || '';
    resMsg.className = 'small mt-2' + (kind ? ' text-' + kind : '');
  }

  function swatchBg(hex, hex2) {
    var ok = /^#[0-9a-f]{3}([0-9a-f]{3})?$/i;
    if (!hex || !ok.test(hex)) return '#6c757d';
    if (hex2 && ok.test(hex2)) return 'linear-gradient(135deg,' + hex + ' 50%,' + hex2 + ' 50%)';
    return hex;
  }

  function fillSummary(d) {
    current = d.id;
    $('qrResSwatch').style.background = swatchBg(d.color_hex, d.color_hex2);
    $('qrResTitle').textContent = d.color_name || d.family || d.material;
    $('qrResSub').textContent = [d.material, d.brand].filter(Boolean).join(' · ') +
      (d.family && d.family !== d.material ? ' / ' + d.family : '');
    $('qrResCode').textContent = d.code;
    $('qrResGrams').textContent = d.remaining_g === null ? '—' : d.remaining_g + ' g';
    $('qrResPct').textContent = d.pct === null ? '' : d.pct + '% ' + d.text.remaining;
    $('qrResLast').textContent = d.last_weighed || d.text.never;
    $('qrOpenBtn').setAttribute('href', d.detail_url);
  }

  function showResult(d) {
    fillSummary(d);
    setMsg('', null);
    var weigh = canWeigh && getTarget() === 'weigh';
    weighForm.classList.toggle('d-none', !weigh);
    weighInput.value = '';
    resultEl.classList.remove('d-none');
    setStatus('', false);
    if (weigh) { try { weighInput.focus(); } catch (e) { /* ignore */ } }
  }

  function resume() {
    if (!stream || !decoder) return;
    resultEl.classList.add('d-none');
    setStatus(msg('msgHint'), false);
    ignoreId = current; ignoreUntil = Date.now() + DEBOUNCE_MS;
    current = null;
    token++;
    running = true;
    loop(decoder, session);
  }

  function handleText(text) {
    var id = parseSpoolId(text);
    if (!id) { setStatus(msg('msgUnrecognized'), true); return 'bad'; }
    if (id === ignoreId && Date.now() < ignoreUntil) return 'ignored';
    if (navigator.vibrate) { try { navigator.vibrate(50); } catch (e) { /* ignore */ } }
    pauseDecoding();
    var my = ++token;
    fetch('/spools/' + id + '/summary.json', { credentials: 'same-origin', headers: { Accept: 'application/json' } })
      .then(function (r) { if (!r.ok) throw new Error('http ' + r.status); return r.json(); })
      .then(function (d) { if (my === token) showResult(d); })
      .catch(function () {
        if (my !== token) return;
        setStatus(msg('msgLoadFailed'), true);
        ignoreId = id; ignoreUntil = Date.now() + DEBOUNCE_MS;
        running = true; loop(decoder, session);
      });
    return 'ok';
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
      if (mySession !== session || !running) return;
      if (text) {
        var r = handleText(text);
        if (r === 'ok') return;
        again(r === 'bad' ? 800 : 200);   // unrecognized: don't hammer the same code
        return;
      }
      again(200);
    }, function () { again(200); });
  }

  // One getUserMedia per modal opening (also used to re-acquire after the OS killed the track).
  function openStream(mySession, reacquire) {
    return navigator.mediaDevices.getUserMedia({
      video: { facingMode: { ideal: 'environment' } }, audio: false
    }).then(function (s) {
      if (mySession !== session) { s.getTracks().forEach(function (t) { t.stop(); }); return; }
      stream = s;
      video.srcObject = s;
      var p = video.play();
      if (p && p.catch) p.catch(function () { /* muted + playsinline normally autoplays */ });
      var ready = decoder ? Promise.resolve(decoder) : makeDecoder();
      return ready.then(function (decode) {
        if (mySession !== session) return;
        decoder = decode;
        // Re-acquired while a result is on screen: stay paused until "scan next".
        if (reacquire && current !== null) return;
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

  function start() {
    syncRadios();
    resultEl.classList.add('d-none');
    current = null; ignoreId = null;
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia || !window.isSecureContext) {
      setStatus(msg('msgNoCamera'), true);
      return;
    }
    setStatus(msg('msgStarting'), false);
    openStream(++session, false);
  }

  // Screen lock / app switch: keep the stream. On return, re-acquire only if the track died.
  document.addEventListener('visibilitychange', function () {
    if (document.visibilityState !== 'visible' || !modal.classList.contains('show') || !stream) return;
    var tr = stream.getVideoTracks()[0];
    if (!tr || tr.readyState === 'ended') {
      pauseDecoding();
      stream = null;
      openStream(session, true);
    } else {
      try { video.play(); } catch (e) { /* ignore */ }
      if (current === null && !running && decoder) { running = true; loop(decoder, session); }
    }
  });

  weighForm.addEventListener('submit', function (e) {
    e.preventDefault();
    if (current === null) return;
    var raw = weighInput.value.trim().replace(',', '.');
    if (!raw || isNaN(Number(raw))) { setMsg(msg('msgInvalid'), 'danger'); return; }
    var my = ++token, id = current;
    $('qrWeighSave').disabled = true;
    fetch('/spools/' + id + '/weigh.json', {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({ gross_weight_g: Number(raw) })
    }).then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
      .then(function (res) {
        if (my !== token) return;
        $('qrWeighSave').disabled = false;
        if (res.ok && res.j.ok) {
          fillSummary(res.j.summary);
          weighInput.value = '';
          setMsg(msg('msgSaved'), 'success');
        } else {
          setMsg((res.j && res.j.error) || msg('msgSaveFailed'), 'danger');
        }
      })
      .catch(function () {
        if (my !== token) return;
        $('qrWeighSave').disabled = false;
        setMsg(msg('msgSaveFailed'), 'danger');
      });
  });

  $('qrNextBtn').addEventListener('click', resume);

  modal.addEventListener('shown.bs.modal', start);
  modal.addEventListener('hidden.bs.modal', function () {
    stopCamera(); setStatus('', false); resultEl.classList.add('d-none'); current = null;
  });
  // Leaving via back/bfcache: make sure the camera light goes off.
  window.addEventListener('pagehide', stopCamera);
})();
