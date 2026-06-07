#!/usr/bin/env bash
# ── vendor-spoolmandb.sh — refresh the vendored filament catalog (SpoolmanDB) ──
#
# spool-control is PUBLIC and the production server clones it anonymously, and we
# keep the deploy fail-safe + CSP strict + offline-capable. So the filament catalog
# is NOT fetched at runtime/deploy — it is VENDORED into this repo as a snapshot.
#
# Upstream: github.com/Donkie/SpoolmanDB (MIT), compiled JSON served at
# https://donkie.github.io/SpoolmanDB/. SpoolmanDB has no releases/tags, so the
# vendored snapshot IS the pin (stamped with the fetch date).
#
# This script downloads filaments.json + materials.json, transforms them into a
# compact snapshot (only the fields we use, deduplicated) and writes
# spoolman_catalog.json. There is no runtime download and no CDN — what's in git is
# what runs. See docs/spoolmandb.md.
#
# Usage:  deploy/vendor-spoolmandb.sh
# After:  review `git diff`, bump VERSION + CHANGELOG, commit, deploy.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
DEST="$ROOT/spoolman_catalog.json"
BASE="https://donkie.github.io/SpoolmanDB"

# Pick a Python that actually runs (Linux/Mac: python3; Windows dev: py — the
# WindowsApps python3/python are Store stubs that don't execute).
PY=""
for _c in python3 py python; do
  if command -v "$_c" >/dev/null 2>&1 && "$_c" --version >/dev/null 2>&1; then PY="$_c"; break; fi
done
[ -n "$PY" ] || { echo "Python 3 required (python3/py/python)." >&2; exit 1; }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "Downloading SpoolmanDB (filaments + materials)…"
curl -fsSL "$BASE/filaments.json" -o "$TMP/filaments.json"
curl -fsSL "$BASE/materials.json" -o "$TMP/materials.json"

echo "Transforming into vendored snapshot…"
"$PY" - "$TMP/filaments.json" "$TMP/materials.json" "$DEST" "$BASE" <<'PY'
import json, sys, datetime

fil_path, mat_path, dest, base = sys.argv[1:5]
with open(fil_path, encoding="utf-8") as fh:
    filaments = json.load(fh)
with open(mat_path, encoding="utf-8") as fh:
    materials = json.load(fh)

def clean_finish(f):
    f = (f or "").strip()
    # "glossy" é o acabamento padrão/normal → tratamos como "sem família" (em branco).
    if f.lower() in ("", "glossy", "gloss", "none"):
        return ""
    return f.title()

seen, out = set(), []
brands, mats = set(), set()
for e in filaments:
    brand = (e.get("manufacturer") or "").strip()
    material = (e.get("material") or "").strip()
    hexv = (e.get("color_hex") or "").strip()
    color_hex = ("#" + hexv.lower()) if hexv else ""
    diameter = e.get("diameter")
    finish = clean_finish(e.get("finish"))
    color = (e.get("name") or "").strip()
    if not brand or not material:
        continue
    key = (brand, material, finish, color, color_hex, diameter)
    if key in seen:
        continue   # dedup variantes por peso/spool
    seen.add(key)
    out.append({
        "brand": brand, "material": material, "finish": finish,
        "color": color, "color_hex": color_hex, "diameter": diameter,
    })
    brands.add(brand)
    mats.add(material)

# materials.json dá a lista canônica de materiais; unimos com os vistos nos filamentos.
for m in materials:
    name = (m.get("material") or "").strip()
    if name:
        mats.add(name)

out.sort(key=lambda d: (d["brand"].lower(), d["material"].lower(),
                        d["finish"].lower(), d["color"].lower()))

today = datetime.date.today().isoformat()
snapshot = {
    "_source": (
        "VENDORED from SpoolmanDB (github.com/Donkie/SpoolmanDB, MIT license) — "
        f"compiled JSON at {base}/ fetched {today}. SpoolmanDB has no tags; this "
        "snapshot is the pin. Refresh via deploy/vendor-spoolmandb.sh — do not hand-edit. "
        "Attribution: filament data © SpoolmanDB contributors, MIT."
    ),
    "fetched": today,
    "brands": sorted(brands, key=str.lower),
    "materials": sorted(mats, key=str.lower),
    "filaments": out,
}
with open(dest, "w", encoding="utf-8", newline="\n") as fh:
    json.dump(snapshot, fh, ensure_ascii=False, indent=2)
    fh.write("\n")

print(f"  {len(out)} filamentos, {len(brands)} marcas, {len(mats)} materiais")
PY

echo "Updated: $DEST"
echo "Review 'git diff', then bump VERSION + CHANGELOG and deploy."
