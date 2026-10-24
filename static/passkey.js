/* Passkeys (WebAuthn) as the SECOND login factor — Face ID / Touch ID.
 *
 * Two entry points, both bound here because the CSP forbids inline handlers:
 *   - #passkeyLogin  (templates/login_2fa.html)  -> sign in with an existing passkey
 *   - #passkeyAdd    (templates/account/2fa.html) -> register a new passkey
 * Texts and the CSRF token arrive via data-* (static JS does not go through Jinja).
 * login_2fa.html does not load csrf.js, so the token is sent explicitly.
 */
(function () {
  'use strict';
  if (typeof document === 'undefined') return;

  function b64uToBuf(s) {
    s = s.replace(/-/g, '+').replace(/_/g, '/');
    while (s.length % 4) s += '=';
    var bin = atob(s), buf = new Uint8Array(bin.length);
    for (var i = 0; i < bin.length; i++) buf[i] = bin.charCodeAt(i);
    return buf.buffer;
  }
  function bufToB64u(buf) {
    var bytes = new Uint8Array(buf), bin = '';
    for (var i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
    return btoa(bin).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  }

  function post(url, body, csrf) {
    return fetch(url, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf, 'X-Requested-With': 'XMLHttpRequest' },
      body: JSON.stringify(body || {})
    }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (j) {
        if (!r.ok) { var e = new Error(j.error || 'error'); e.server = true; throw e; }
        return j;
      });
    });
  }

  function showMsg(el, text, kind) {
    if (!el) return;
    el.textContent = text || '';
    el.className = 'small mt-2 ' + (kind === 'error' ? 'text-danger' : 'text-muted');
    el.hidden = !text;
  }

  function mapCreate(opts) {
    opts.challenge = b64uToBuf(opts.challenge);
    opts.user.id = b64uToBuf(opts.user.id);
    (opts.excludeCredentials || []).forEach(function (c) { c.id = b64uToBuf(c.id); });
    return opts;
  }
  function mapGet(opts) {
    opts.challenge = b64uToBuf(opts.challenge);
    (opts.allowCredentials || []).forEach(function (c) { c.id = b64uToBuf(c.id); });
    return opts;
  }

  function run(btn, msgEl, work) {
    var d = btn.dataset;
    btn.disabled = true;
    showMsg(msgEl, '', '');
    work().catch(function (e) {
      // User dismissed the system prompt: neutral message, not an error.
      if (e && (e.name === 'NotAllowedError' || e.name === 'AbortError')) {
        showMsg(msgEl, d.msgCancelled, 'info');
      } else if (e && e.name === 'InvalidStateError') {
        showMsg(msgEl, d.msgExists, 'error');
      } else if (e && e.server) {
        showMsg(msgEl, e.message, 'error');
      } else {
        showMsg(msgEl, d.msgFailed, 'error');
      }
    }).then(function () { btn.disabled = false; });
  }

  var supported = !!(window.PublicKeyCredential && navigator.credentials && navigator.credentials.create);

  // ── Login ────────────────────────────────────────────────────────────────
  var login = document.getElementById('passkeyLogin');
  if (login) {
    if (!supported) { login.closest('[data-passkey-wrap]').hidden = true; }
    else {
      var lmsg = document.getElementById('passkeyMsg');
      login.addEventListener('click', function () {
        var csrf = login.dataset.csrf;
        run(login, lmsg, function () {
          return post(login.dataset.optionsUrl, {}, csrf).then(function (opts) {
            return navigator.credentials.get({ publicKey: mapGet(opts) });
          }).then(function (cred) {
            var r = cred.response;
            return post(login.dataset.verifyUrl, {
              credential: {
                id: cred.id, rawId: bufToB64u(cred.rawId), type: cred.type,
                authenticatorAttachment: cred.authenticatorAttachment || null,
                clientExtensionResults: cred.getClientExtensionResults ? cred.getClientExtensionResults() : {},
                response: {
                  clientDataJSON: bufToB64u(r.clientDataJSON),
                  authenticatorData: bufToB64u(r.authenticatorData),
                  signature: bufToB64u(r.signature),
                  userHandle: r.userHandle ? bufToB64u(r.userHandle) : null
                }
              }
            }, csrf);
          }).then(function (res) {
            window.location.assign(res.redirect || '/');
          });
        });
      });
    }
  }

  // ── Registration ─────────────────────────────────────────────────────────
  var add = document.getElementById('passkeyAdd');
  if (add) {
    var amsg = document.getElementById('passkeyAddMsg');
    if (!supported) {
      add.disabled = true;
      showMsg(amsg, add.dataset.msgUnsupported, 'error');
    } else {
      add.addEventListener('click', function () {
        var csrf = add.dataset.csrf;
        var nameEl = document.getElementById('passkeyName');
        run(add, amsg, function () {
          return post(add.dataset.optionsUrl, {}, csrf).then(function (opts) {
            return navigator.credentials.create({ publicKey: mapCreate(opts) });
          }).then(function (cred) {
            var r = cred.response;
            return post(add.dataset.verifyUrl, {
              name: nameEl ? nameEl.value : '',
              credential: {
                id: cred.id, rawId: bufToB64u(cred.rawId), type: cred.type,
                authenticatorAttachment: cred.authenticatorAttachment || null,
                clientExtensionResults: cred.getClientExtensionResults ? cred.getClientExtensionResults() : {},
                response: {
                  clientDataJSON: bufToB64u(r.clientDataJSON),
                  attestationObject: bufToB64u(r.attestationObject),
                  transports: r.getTransports ? r.getTransports() : []
                }
              }
            }, csrf);
          }).then(function () { window.location.reload(); });
        });
      });
    }
  }

  // Delete buttons (POST + CSRF, then reload)
  Array.prototype.forEach.call(document.querySelectorAll('.js-passkey-delete'), function (b) {
    b.addEventListener('click', function () {
      if (!window.confirm(b.dataset.confirm)) return;
      b.disabled = true;
      post(b.dataset.url, {}, b.dataset.csrf).then(function () { window.location.reload(); },
        function () { b.disabled = false; });
    });
  });
})();
