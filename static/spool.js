/* ── Toast init ─────────────────────────────────────────────────────────── */
document.querySelectorAll('.sc-toast').forEach(function (el) {
  new bootstrap.Toast(el).show();
});

/* ── Theme toggle ───────────────────────────────────────────────────────── */
(function () {
  var icon = document.getElementById('themeIcon');
  function applyTheme(t) {
    document.documentElement.setAttribute('data-bs-theme', t);
    if (icon) icon.className = t === 'dark' ? 'bi bi-sun-fill' : 'bi bi-moon-fill';
  }
  applyTheme(localStorage.getItem('sc-theme') || 'dark');
  var btn = document.getElementById('themeToggle');
  if (btn) btn.addEventListener('click', function () {
    var next = document.documentElement.getAttribute('data-bs-theme') === 'dark' ? 'light' : 'dark';
    localStorage.setItem('sc-theme', next);
    applyTheme(next);
  });
})();

/* ── Safe confirm dialogs (data-sc-confirm) ─────────────────────────────── */
/* Replaces onsubmit="return confirm('...')" — avoids XSS via JS string injection. */
document.addEventListener('submit', function (e) {
  var msg = e.target.dataset && e.target.dataset.scConfirm;
  if (msg && !confirm(msg)) e.preventDefault();
}, true);

/* ── Bootstrap tooltips (global) ─────────────────────────────────────── */
document.querySelectorAll('[data-bs-toggle="tooltip"]').forEach(el => {
  new bootstrap.Tooltip(el);
});

/* ── Client-side table filter ─────────────────────────────────────────── */
document.querySelectorAll('[data-filter-for]').forEach(input => {
  const table = document.querySelector(input.dataset.filterFor);
  if (!table) return;
  const noResult = table.querySelector('[data-no-result]');
  input.addEventListener('input', () => {
    const q = input.value.toLowerCase();
    let visible = 0;
    if (table.hasAttribute('data-grouped')) {
      // Modo agrupado: cada <tbody> é uma unidade (grupo + filhos); casa se qualquer linha casar.
      table.querySelectorAll('tbody.sc-group').forEach(tb => {
        const match = tb.textContent.toLowerCase().includes(q);
        tb.style.display = match ? '' : 'none';
        if (match) visible++;
      });
      if (noResult) noResult.closest('tbody').style.display = visible === 0 ? '' : 'none';
      return;
    }
    table.querySelectorAll('tbody tr:not([data-no-result])').forEach(row => {
      const match = row.textContent.toLowerCase().includes(q);
      row.style.display = match ? '' : 'none';
      if (match) visible++;
    });
    if (noResult) noResult.style.display = visible === 0 ? '' : 'none';
  });
});

/* ── Sortable table columns ───────────────────────────────────────────── */
document.querySelectorAll('table[data-sortable]').forEach(table => {
  let currentTh = null, asc = true;

  table.querySelectorAll('thead th[data-sort]').forEach(th => {
    th.style.cursor = 'pointer';
    th.style.userSelect = 'none';
    th.insertAdjacentHTML('beforeend', '<span class="sort-icon ms-1" style="font-size:.75em;opacity:.4;color:inherit">⇅</span>');

    th.addEventListener('click', () => {
      asc = currentTh === th ? !asc : true;
      currentTh = th;

      // reset all icons
      table.querySelectorAll('thead th .sort-icon').forEach(s => {
        s.textContent = '⇅'; s.style.opacity = '.4';
      });
      const icon = th.querySelector('.sort-icon');
      icon.textContent = asc ? '↑' : '↓';
      icon.style.opacity = '1';

      const colIndex = th.cellIndex;
      const type = th.dataset.sort; // "text" | "num" | "pct"
      const tbody = table.querySelector('tbody');
      if (table.hasAttribute('data-grouped')) {
        // Modo agrupado: ordena os <tbody> pela primeira linha; filhos acompanham o grupo.
        const units = Array.from(table.querySelectorAll('tbody.sc-group'));
        const key = tb => (tb.rows[0].cells[colIndex]?.textContent || '').trim();
        units.sort((a, b) => {
          const av = key(a), bv = key(b);
          const cmp = (type === 'num' || type === 'pct')
            ? (parseFloat(av) || 0) - (parseFloat(bv) || 0)
            : av.localeCompare(bv, 'pt-BR', { sensitivity: 'base' });
          return asc ? cmp : -cmp;
        });
        const anchor = table.querySelector('tbody:not(.sc-group)');
        units.forEach(u => table.insertBefore(u, anchor));
        return;
      }
      const rows = Array.from(tbody.querySelectorAll('tr')).filter(r => r.cells.length > 1);

      rows.sort((a, b) => {
        const av = (a.cells[colIndex]?.textContent || '').trim();
        const bv = (b.cells[colIndex]?.textContent || '').trim();
        let cmp;
        if (type === 'num' || type === 'pct') {
          cmp = (parseFloat(av) || 0) - (parseFloat(bv) || 0);
        } else {
          cmp = av.localeCompare(bv, 'pt-BR', { sensitivity: 'base' });
        }
        return asc ? cmp : -cmp;
      });
      rows.forEach(r => tbody.appendChild(r));
    });
  });
});

/* ── Grupo expansível na lista de rolos (Agrupar) ─────────────────────── */
document.querySelectorAll('tr.sc-group-row').forEach(head => {
  const toggle = () => {
    const open = head.getAttribute('aria-expanded') !== 'true';
    head.setAttribute('aria-expanded', open ? 'true' : 'false');
    head.closest('tbody').querySelectorAll('tr[data-group-child]').forEach(r => {
      r.classList.toggle('d-none', !open);
    });
  };
  head.addEventListener('click', e => {
    if (e.target.closest('.sc-stack-actions')) return;
    toggle();
  });
  head.addEventListener('keydown', e => {
    if (e.target.closest('.sc-stack-actions')) return;
    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggle(); }
  });
});
