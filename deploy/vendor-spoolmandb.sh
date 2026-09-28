#!/usr/bin/env bash
# ── vendor-spoolmandb.sh — refresh the VENDORED filament catalog (SpoolmanDB) ──
#
# This is the dev-run refresh of the COMMITTED snapshot (spoolman_catalog.json at
# the repo root) — it stays vendored for the same reasons as before (deploy fail-
# safe + CSP strict + offline fallback): the app never depends on a live fetch to
# have a baseline catalog. What changed (see docs/spoolmandb.md): the SERVER now
# also refreshes its own copy at runtime (daily cron + admin "update catalog"
# button, in data/spoolman_catalog.json) — this script is for the committed pin.
#
# The download + transform logic lives in spoolmandb_refresh.py (single source,
# shared with the runtime refresher) — this script just calls it and writes to
# the repo root instead of data/.
#
# Upstream: github.com/Donkie/SpoolmanDB (MIT), compiled JSON served at
# https://donkie.github.io/SpoolmanDB/. SpoolmanDB has no releases/tags, so the
# vendored snapshot IS the pin (stamped with the fetch date).
#
# Usage:  deploy/vendor-spoolmandb.sh
# After:  review `git diff`, bump VERSION + CHANGELOG, commit, deploy.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Pick a Python that actually runs (Linux/Mac: python3; Windows dev: py — the
# WindowsApps python3/python are Store stubs that don't execute).
PY=""
for _c in python3 py python; do
  if command -v "$_c" >/dev/null 2>&1 && "$_c" --version >/dev/null 2>&1; then PY="$_c"; break; fi
done
[ -n "$PY" ] || { echo "Python 3 required (python3/py/python)." >&2; exit 1; }

echo "Downloading + transforming SpoolmanDB (filaments + materials)…"
cd "$ROOT"
"$PY" - <<'PY'
import spoolmandb_refresh as r

result = r.fetch_and_write("spoolman_catalog.json", vendored=True)
print("  {filaments} filamentos, {brands} marcas, {materials} materiais (fetched {fetched})"
      .format(**result))
PY

echo "Updated: $ROOT/spoolman_catalog.json"
echo "Review 'git diff', then bump VERSION + CHANGELOG and deploy."
