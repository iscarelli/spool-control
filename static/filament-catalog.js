/* ── filament-catalog.js — picker "Importar do catálogo" (SpoolmanDB) ──────────
 * Carrega o catálogo vendorado de /api/filament-catalog, enriquece os datalists de
 * marca/material (autocomplete) e, no modal de busca, pré-preenche o formulário de
 * filamento ao escolher uma entrada. Tudo client-side; salvar usa o fluxo normal.
 */
(function () {
  "use strict";

  var results = document.getElementById("catalogResults");
  var search = document.getElementById("catalogSearch");
  if (!results || !search) return;

  var LIMIT = 80;            // máx. de linhas renderizadas por busca
  var catalog = [];         // lista de filamentos
  var shown = [];           // fatia atualmente exibida (para mapear o clique)

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function safeHex(h) { return /^#[0-9a-fA-F]{6}$/.test(h || "") ? h : ""; }

  function addOptions(datalistId, values) {
    var dl = document.getElementById(datalistId);
    if (!dl) return;
    var have = {};
    dl.querySelectorAll("option").forEach(function (o) { have[o.value.toLowerCase()] = 1; });
    var frag = document.createDocumentFragment();
    values.forEach(function (v) {
      if (v && !have[String(v).toLowerCase()]) {
        var o = document.createElement("option");
        o.value = v;
        frag.appendChild(o);
        have[String(v).toLowerCase()] = 1;
      }
    });
    dl.appendChild(frag);
  }

  function label(e) {
    var parts = [e.material];
    if (e.finish) parts.push(e.finish);
    if (e.color) parts.push(e.color);
    return parts.join(" · ");
  }

  function render() {
    var q = search.value.trim().toLowerCase();
    if (!q) {
      results.innerHTML = '<div class="text-muted small p-2">' +
        esc(results.dataset.typehint || "") + "</div>";
      shown = [];
      return;
    }
    var matches = [];
    for (var i = 0; i < catalog.length && matches.length < LIMIT + 1; i++) {
      var e = catalog[i];
      var hay = (e.brand + " " + e.material + " " + (e.finish || "") + " " + (e.color || "")).toLowerCase();
      if (hay.indexOf(q) !== -1) matches.push(e);
    }
    var more = matches.length > LIMIT;
    shown = matches.slice(0, LIMIT);
    if (!shown.length) {
      results.innerHTML = '<div class="text-muted small p-2">' + esc(results.dataset.empty || "") + "</div>";
      return;
    }
    var html = shown.map(function (e, idx) {
      var hx = safeHex(e.color_hex);
      var sw = '<span class="border rounded flex-shrink-0" style="width:18px;height:18px;display:inline-block;' +
        (hx ? "background:" + hx : "background:repeating-linear-gradient(45deg,#ccc,#ccc 3px,#fff 3px,#fff 6px)") + '"></span>';
      var dia = e.diameter ? ('<span class="badge text-bg-light ms-2">' + esc(e.diameter) + ' mm</span>') : "";
      return '<button type="button" class="list-group-item list-group-item-action d-flex align-items-center gap-2" data-idx="' + idx + '">' +
        sw + '<span class="text-truncate"><strong>' + esc(e.brand) + "</strong> · " + esc(label(e)) + "</span>" + dia +
        "</button>";
    }).join("");
    if (more) {
      html += '<div class="text-muted small p-2">' + esc(results.dataset.more || "") + "</div>";
    }
    results.innerHTML = html;
  }

  function setVal(sel, value) {
    var el = document.querySelector(sel);
    if (el != null && value != null) el.value = value;
  }

  function pick(e) {
    setVal('input[name="material"]', e.material || "");
    setVal('input[name="brand"]', e.brand || "");
    setVal('input[name="family"]', e.finish || "");
    var hx = safeHex(e.color_hex);
    if (hx) {
      setVal("#colorHex", hx);
      var p = document.getElementById("colorPicker");
      if (p) p.value = hx;
    }
    // Diâmetro: só seta se houver a opção correspondente no select.
    var dsel = document.querySelector('select[name="diameter_mm"]');
    if (dsel && e.diameter != null) {
      var want = String(e.diameter);
      for (var i = 0; i < dsel.options.length; i++) {
        if (dsel.options[i].value === want) { dsel.value = want; break; }
      }
    }
    // Nome da cor do catálogo → campo color_name (só se estiver vazio).
    var colorNameEl = document.querySelector('input[name="color_name"]');
    if (colorNameEl && !colorNameEl.value.trim() && e.color) colorNameEl.value = e.color;

    var modalEl = document.getElementById("catalogModal");
    if (modalEl && window.bootstrap) {
      var m = window.bootstrap.Modal.getInstance(modalEl) || window.bootstrap.Modal.getOrCreateInstance(modalEl);
      m.hide();
    }
  }

  results.addEventListener("click", function (ev) {
    var btn = ev.target.closest("[data-idx]");
    if (!btn) return;
    var e = shown[parseInt(btn.dataset.idx, 10)];
    if (e) pick(e);
  });

  var t;
  search.addEventListener("input", function () { clearTimeout(t); t = setTimeout(render, 120); });

  // Carrega o catálogo uma vez: enriquece os datalists e prepara a busca.
  fetch("/api/filament-catalog")
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(function (d) {
      if (!d) return;
      catalog = d.filaments || [];
      addOptions("brandOptions", d.brands || []);
      addOptions("materialOptions", d.materials || []);
      render();
    })
    .catch(function () { /* fail-safe: sem catálogo, o picker fica vazio */ });
})();
