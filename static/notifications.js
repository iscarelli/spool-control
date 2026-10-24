/* /account/notifications: push on this device, test send, and the device permissions check.
 *
 * "Ativar" runs only from a click (iOS requires a user gesture). Every state is written with
 * textContent. Texts arrive as JSON in data-i18n (static JS does not go through Jinja); the CSRF
 * header is added by csrf.js, which wraps fetch.
 */
(function () {
  'use strict';
  var root = document.getElementById('notif-root');
  if (!root) return;

  var M = {};
  try { M = JSON.parse(root.dataset.i18n || '{}'); } catch (e) { M = {}; }
  function m(key) { return M[key] || key; }

  var ua = navigator.userAgent;
  var ios = /iPhone|iPad|iPod/i.test(ua) || (/Macintosh/i.test(ua) && navigator.maxTouchPoints > 1);
  function installed() {
    return (window.matchMedia && window.matchMedia('(display-mode: standalone)').matches) ||
      navigator.standalone === true;
  }

  // ── Permissions ──────────────────────────────────────────────────────────
  function unblock(name) {
    var label = name === 'camera' ? 'Câmera' : 'Notificações';
    if (ios) {
      return m(installed() ? 'Ajustes › Spool › ' + label + ' › Permitir'
                           : 'Ajustes › Safari › ' + label + ' › Permitir');
    }
    return m('toque no cadeado ao lado do endereço › Permissões › Permitir');
  }
  function permRow(name) { return root.querySelector('[data-perm="' + name + '"]'); }
  function permSay(name, text, cls) {
    var el = permRow(name).querySelector('[data-perm-state]');
    el.textContent = text;
    el.className = 'small mt-1 ' + (cls || 'text-secondary');
  }
  function permBlocked(name) { permSay(name, m('Bloqueada. Para liberar:') + ' ' + unblock(name), 'text-danger'); }
  function permPaint(name, state) {
    if (state === 'granted') permSay(name, m('Permitida'), 'text-success');
    else if (state === 'denied') permBlocked(name);
    else if (state === 'prompt') permSay(name, m('Ainda não pedida'));
    else permSay(name, name === 'notifications' ? m('Sem informação neste aparelho') : m('Toque em Testar'));
  }
  function permRefresh(name) {
    if (name === 'notifications' && 'Notification' in window && Notification.permission) {
      var p = Notification.permission;
      permPaint(name, p === 'default' ? 'prompt' : p);
      return;
    }
    if (!navigator.permissions || !navigator.permissions.query) { permPaint(name, null); return; }
    navigator.permissions.query({ name: name }).then(function (st) {
      permPaint(name, st.state);
      st.onchange = function () { permPaint(name, st.state); };
    }).catch(function () { permPaint(name, null); });
  }

  function testCamera() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      permSay('camera', m('Este navegador não dá acesso à câmera.'), 'text-danger');
      return;
    }
    navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' } }).then(function (stream) {
      stream.getTracks().forEach(function (tr) { tr.stop(); });
      permSay('camera', m('Câmera OK'), 'text-success');
    }).catch(function (e) {
      if (e && (e.name === 'NotAllowedError' || e.name === 'SecurityError')) permBlocked('camera');
      else if (e && e.name === 'NotFoundError') permSay('camera', m('Este aparelho não tem câmera.'), 'text-danger');
      else permSay('camera', m('Não consegui abrir a câmera agora.'), 'text-danger');
    });
  }
  function testNotifications() {
    if (!('Notification' in window)) {
      permSay('notifications', m('Este navegador não oferece notificações aqui.'), 'text-danger');
      return;
    }
    Promise.resolve(Notification.requestPermission()).then(function (perm) {
      if (perm === 'granted') permSay('notifications', m('Notificações permitidas'), 'text-success');
      else if (perm === 'denied') permBlocked('notifications');
      else permSay('notifications', m('A permissão não foi concedida.'), 'text-danger');
    });
  }
  var tests = { camera: testCamera, notifications: testNotifications };
  ['camera', 'notifications'].forEach(function (name) {
    permRefresh(name);
    permRow(name).querySelector('[data-perm-test]').addEventListener('click', tests[name]);
  });

  // ── Push on this device ──────────────────────────────────────────────────
  var enable = document.getElementById('push-enable');
  var disable = document.getElementById('push-disable');
  var test = document.getElementById('push-test');
  var status = document.getElementById('push-status');
  var results = document.getElementById('push-results');
  var iosNote = document.getElementById('push-ios-note');

  function say(text, cls) {
    status.textContent = text;
    status.className = 'small ' + (cls || '');
  }
  function supported() {
    return 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window;
  }
  // The key is URL-safe base64 of the uncompressed P-256 point; subscribe() wants the bytes.
  function keyBytes(b64) {
    var pad = '='.repeat((4 - b64.length % 4) % 4);
    var raw = atob((b64 + pad).replace(/-/g, '+').replace(/_/g, '/'));
    var out = new Uint8Array(raw.length);
    for (var i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
    return out;
  }
  function post(url, body) {
    return fetch(url, {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'Accept': 'application/json',
                 'X-Requested-With': 'XMLHttpRequest' },
      body: JSON.stringify(body === undefined ? {} : body)
    });
  }
  function json(r) { return r.json().catch(function () { return {}; }); }
  function currentSub() {
    return navigator.serviceWorker.getRegistration().then(function (reg) {
      return reg ? reg.pushManager.getSubscription() : null;
    });
  }
  function showSubscribed(on) {
    enable.classList.toggle('d-none', on);
    disable.classList.toggle('d-none', !on);
  }

  function describe() {
    if (ios && !installed()) iosNote.classList.remove('d-none');
    if (!supported()) {
      say(m('Este navegador não oferece notificações aqui.') +
          (ios ? ' ' + m('No iPhone elas só funcionam no app instalado na Tela de Início.') : ''),
          'text-warning-emphasis');
      enable.disabled = true;
      return;
    }
    if (Notification.permission === 'denied') {
      say(m('Permissão negada.') + ' ' + unblock('notifications'), 'text-danger');
      return;
    }
    currentSub().then(function (sub) {
      showSubscribed(!!sub);
      if (sub) say(m('Este aparelho está inscrito.'), 'text-success');
      else say(m('Este aparelho ainda não está inscrito.'));
    }).catch(function () { /* leave the buttons as they are */ });
  }

  enable.addEventListener('click', function () {
    if (!supported()) { describe(); return; }
    say(m('Pedindo permissão…'));
    Promise.resolve(Notification.requestPermission()).then(function (perm) {
      if (perm !== 'granted') {
        say(perm === 'denied' ? m('Permissão negada.') + ' ' + unblock('notifications')
                              : m('A permissão não foi concedida.'), 'text-danger');
        permRefresh('notifications');
        return null;
      }
      return navigator.serviceWorker.ready.then(function (reg) {
        return reg.pushManager.subscribe({
          userVisibleOnly: true, applicationServerKey: keyBytes(root.dataset.publicKey)
        });
      }).then(function (sub) {
        return post(root.dataset.subscribeUrl, sub.toJSON()).then(function (r) {
          return json(r).then(function (j) {
            if (!r.ok) { say(j.error || m('O servidor recusou a inscrição.'), 'text-danger'); return; }
            showSubscribed(true);
            say(m('Inscrito. Envie o teste para conferir.'), 'text-success');
            permRefresh('notifications');
            var none = document.getElementById('push-no-devices');
            if (none) none.textContent = '';
          });
        });
      });
    }).catch(function () {
      say(m('Não foi possível inscrever este aparelho.'), 'text-danger');
    });
  });

  disable.addEventListener('click', function () {
    currentSub().then(function (sub) {
      if (!sub) { showSubscribed(false); return null; }
      var endpoint = sub.endpoint;
      return sub.unsubscribe().then(function () {
        return post(root.dataset.unsubscribeUrl, { endpoint: endpoint });
      }).then(function () {
        showSubscribed(false);
        say(m('Notificações desativadas neste aparelho.'));
      });
    }).catch(function () {
      say(m('Não foi possível desativar.'), 'text-danger');
    });
  });

  var LABEL = {
    ok: 'Enviada: o serviço de push aceitou.',
    expired: 'Inscrição expirada e apagada: ative de novo.',
    failed: 'O serviço de push recusou.',
    error: 'Não consegui enviar.'
  };
  test.addEventListener('click', function () {
    results.textContent = '';
    say(m('Enviando…'));
    post(root.dataset.testUrl).then(function (r) {
      return json(r).then(function (j) {
        if (!r.ok) { say(j.error || m('Não foi possível enviar o teste.'), 'text-danger'); return; }
        if (!j.results.length) { say(m('Este aparelho não está inscrito: ative as notificações primeiro.')); return; }
        say('');
        j.results.forEach(function (x) {
          var li = document.createElement('li');
          li.textContent = x.device + ': ' + m(LABEL[x.result] || x.result) + (x.status ? ' (' + x.status + ')' : '');
          li.className = x.result === 'ok' ? 'text-success' : 'text-danger';
          results.appendChild(li);
        });
      });
    }).catch(function () {
      say(m('Sem conexão: o teste não foi enviado.'), 'text-danger');
    });
  });

  describe();
})();
