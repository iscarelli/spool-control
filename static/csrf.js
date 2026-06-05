(function () {
  var meta = document.querySelector('meta[name="csrf-token"]');
  var token = meta ? meta.getAttribute('content') : '';

  // Inject CSRF token into every POST form that doesn't already have it.
  document.addEventListener('submit', function (e) {
    var f = e.target;
    if (f && (f.method || '').toLowerCase() === 'post' &&
        !f.querySelector('input[name="csrf_token"]')) {
      var i = document.createElement('input');
      i.type = 'hidden'; i.name = 'csrf_token'; i.value = token;
      f.appendChild(i);
    }
  }, true);

  // Attach X-CSRFToken header to every non-safe fetch() call.
  var _fetch = window.fetch;
  window.fetch = function (input, init) {
    init = init || {};
    var method = (init.method ||
      (input && typeof input !== 'string' && input.method) || 'GET').toUpperCase();
    if (method !== 'GET' && method !== 'HEAD') {
      var h = new Headers(init.headers || {});
      if (!h.has('X-CSRFToken')) h.set('X-CSRFToken', token);
      init.headers = h;
    }
    return _fetch(input, init);
  };
})();
