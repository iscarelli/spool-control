#!/usr/bin/env bash
# ── build-firmware-bin.sh — gera os binários da balança p/ flash pela web ─────
#
# O gravador web (Web Serial + esptool-js, em /admin/scale) grava os MESMOS 4
# pedaços que o `pio run -t upload` (CLI), cada um no seu offset:
#   bootloader 0x0 · partitions 0x8000 · boot_app0 0xe000 · app 0x10000
#
# IMPORTANTE: gravar os pedaços SEPARADOS (e não uma imagem "merged" única em 0x0)
# é o que funciona com o esptool-js — a imagem merged em 0x0 falha no meio
# ("Failed to write compressed data to flash after seq N"), pois o esptool-js
# erra o cálculo de endereço de bloco numa imagem única grande. O CLI grava
# separado, por isso funciona; aqui replicamos isso.
#
# Os binários + o manifesto (offsets) são gravados em static/firmware/ e VÃO
# committados no git: o deploy é por clone público + `git archive`, então o que
# está no git é o que o site serve (sem build no servidor).
#
# Uso:  bash deploy/build-firmware-bin.sh
# Requisitos: PlatformIO (pio) no PATH.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
FW_DIR="$ROOT/firmware"
ENV="balanca-c3"
CHIP="esp32c3"
BUILD_DIR="$FW_DIR/.pio/build/$ENV"
OUT_DIR="$ROOT/static/firmware"
OUT_MANIFEST="$OUT_DIR/$ENV.json"

command -v pio >/dev/null 2>&1 || { echo "PlatformIO (pio) não encontrado no PATH." >&2; exit 1; }

# Python que de fato roda (no Windows o python/python3 do Store é stub).
PY=""
for _c in python3 py python; do
  if command -v "$_c" >/dev/null 2>&1 && "$_c" --version >/dev/null 2>&1; then PY="$_c"; break; fi
done
[ -n "$PY" ] || { echo "Python 3 necessário (python3/py/python)." >&2; exit 1; }

echo "==> Compilando firmware ($ENV)…"
pio run -d "$FW_DIR" -e "$ENV"

# Offsets padrão do ESP32-C3 Arduino. O boot_app0 (seletor OTA) vem do framework.
BOOTLOADER="$BUILD_DIR/bootloader.bin"
PARTITIONS="$BUILD_DIR/partitions.bin"
APP="$BUILD_DIR/firmware.bin"
for f in "$BOOTLOADER" "$PARTITIONS" "$APP"; do
    [ -f "$f" ] || { echo "Faltando $f (rode o build antes)." >&2; exit 1; }
done

# boot_app0.bin: prefere o diretório do framework SEM sufixo de versão (o ativo).
BOOT_APP0="$(ls -1 \
    "$HOME"/.platformio/packages/framework-arduinoespressif32/tools/partitions/boot_app0.bin \
    "$HOME"/.platformio/packages/framework-arduinoespressif32*/tools/partitions/boot_app0.bin \
    2>/dev/null | head -1)"
[ -n "$BOOT_APP0" ] && [ -f "$BOOT_APP0" ] || { echo "boot_app0.bin não encontrado no framework." >&2; exit 1; }

mkdir -p "$OUT_DIR"

echo "==> Copiando os 4 pedaços para $OUT_DIR…"
cp -f "$BOOTLOADER" "$OUT_DIR/bootloader.bin"
cp -f "$PARTITIONS" "$OUT_DIR/partitions.bin"
cp -f "$BOOT_APP0"  "$OUT_DIR/boot_app0.bin"
cp -f "$APP"        "$OUT_DIR/app.bin"

# Remove a imagem merged legada (não é mais usada — o flasher grava os pedaços).
rm -f "$OUT_DIR/$ENV.bin"

echo "==> Gerando manifesto (offsets + sha)…"
"$PY" - "$OUT_DIR" "$OUT_MANIFEST" "$CHIP" "$ROOT" <<'PYEOF'
import hashlib, json, os, subprocess, sys, datetime
out_dir, manifest, chip, root = sys.argv[1:5]
# offset → arquivo, na MESMA ordem/endereços do `pio run -t upload`.
layout = [
    ("0x0",     "bootloader.bin"),
    ("0x8000",  "partitions.bin"),
    ("0xe000",  "boot_app0.bin"),
    ("0x10000", "app.bin"),
]
def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()
parts = []
for off, fn in layout:
    p = os.path.join(out_dir, fn)
    parts.append({"offset": off, "file": fn,
                  "size": os.path.getsize(p), "sha256": sha(p)})
try:
    commit = subprocess.check_output(
        ["git", "-C", root, "log", "-1", "--format=%h", "--", "firmware"],
        text=True).strip()
except Exception:
    commit = ""
m = {
    "chip": chip,
    "parts": parts,
    # "versão" exibida = sha do app (firmware.bin); muda quando o firmware muda.
    "app_sha256": next(p["sha256"] for p in parts if p["file"] == "app.bin"),
    "source_commit": commit,
    "built_at": datetime.datetime.now(datetime.timezone.utc)
        .strftime("%Y-%m-%dT%H:%M:%SZ"),
}
json.dump(m, open(manifest, "w"), indent=2)
print(json.dumps(m, indent=2))
PYEOF

echo "==> OK. Pedaços + manifesto em $OUT_DIR."
echo "Revise o git diff e committe os artefatos."
