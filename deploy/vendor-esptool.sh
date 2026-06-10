#!/usr/bin/env bash
# ── vendor-esptool.sh — re-vendora o esptool-js (gravador Web Serial) ──────────
#
# spool-control é PÚBLICO e o servidor clona anonimamente, então o esptool-js NÃO
# pode ser baixado em deploy/runtime — é VENDORADO no repo (igual ao driver Niimbot).
# O upstream é o pacote npm `esptool-js` (Espressif), que publica um `bundle.js`
# ESM único (mesmo bundle usado pelo ESP Web Tools).
#
# Esta é a única forma deliberada e reprodutível de atualizar a cópia vendorada:
# baixa o bundle de uma VERSÃO FIXA, carimba versão/origem no topo e grava em
# static/esptool.js. Sem download em runtime/deploy e sem CDN — o que está no git é
# o que roda (preserva CSP, deploy à prova de falhas e operação offline).
#
# Uso:
#   deploy/vendor-esptool.sh            # versão pinada abaixo
#   deploy/vendor-esptool.sh 0.6.0      # uma versão específica
#
# Depois: revise `git diff`, bump VERSION + CHANGELOG, committe, deploy.
set -euo pipefail

ESPTOOL_VERSION="${1:-0.6.0}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
DEST="$ROOT/static/esptool.js"
URL="https://unpkg.com/esptool-js@${ESPTOOL_VERSION}/bundle.js"
TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT

echo "==> Baixando esptool-js@${ESPTOOL_VERSION} de unpkg…"
curl -fsSL --max-time 60 "$URL" -o "$TMP"

# Sanidade: precisa ser o bundle ESM com os exports que o esp-flash.js usa.
grep -q "as ESPLoader" "$TMP" || { echo "Bundle inesperado: não exporta ESPLoader." >&2; exit 1; }
grep -q "as Transport" "$TMP" || { echo "Bundle inesperado: não exporta Transport." >&2; exit 1; }

{
  echo "// VENDORADO — esptool-js@${ESPTOOL_VERSION} (Apache-2.0), Espressif Systems."
  echo "// Fonte: ${URL}"
  echo "// NÃO EDITAR À MÃO — atualize via deploy/vendor-esptool.sh. Bundle ESM único"
  echo "// (importado por static/esp-flash.js). Carimbado em $(date -u +%Y-%m-%dT%H:%M:%SZ)."
  cat "$TMP"
} > "$DEST"

echo "==> OK: $DEST ($(wc -c < "$DEST") bytes)"
echo "Revise o git diff e committe."
