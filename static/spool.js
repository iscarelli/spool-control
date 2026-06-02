/* ── Client-side table filter ─────────────────────────────────────────── */
document.querySelectorAll('[data-filter-for]').forEach(input => {
  const table = document.querySelector(input.dataset.filterFor);
  if (!table) return;
  const noResult = table.querySelector('[data-no-result]');
  input.addEventListener('input', () => {
    const q = input.value.toLowerCase();
    let visible = 0;
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
    th.insertAdjacentHTML('beforeend', '<span class="sort-icon text-muted ms-1" style="font-size:.75em;opacity:.4">⇅</span>');

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
