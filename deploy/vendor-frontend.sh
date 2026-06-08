#!/usr/bin/env bash
# ── vendor-frontend.sh — refresh the vendored frontend assets (Bootstrap + Icons) ──
#
# spool-control is PUBLIC, the production server clones it anonymously, and we keep a
# strict CSP with NO external CDN (default-src 'self'). So Bootstrap and Bootstrap
# Icons are NOT loaded from jsdelivr at runtime — they are VENDORED into static/vendor/
# and served same-origin. What's in git is what runs (offline-capable, no third-party
# trust). Templates reference static/vendor/... (see templates/base.html, login.html).
#
# Upstream: getbootstrap.com (MIT). Versions are pinned below — bump them here when
# upgrading, re-run this script, review `git diff`, then commit the new assets.
#
# Usage:  deploy/vendor-frontend.sh
# After:  review `git diff`, bump VERSION + CHANGELOG, commit, deploy.
set -euo pipefail

BS_VER="5.3.3"
BI_VER="1.11.3"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
VENDOR="$ROOT/static/vendor"
BS_DIR="$VENDOR/bootstrap"
BI_DIR="$VENDOR/bootstrap-icons"

BS_CDN="https://cdn.jsdelivr.net/npm/bootstrap@${BS_VER}/dist"
BI_CDN="https://cdn.jsdelivr.net/npm/bootstrap-icons@${BI_VER}/font"

mkdir -p "$BS_DIR" "$BI_DIR/fonts"

echo "Downloading Bootstrap ${BS_VER}…"
curl -fsSL "$BS_CDN/css/bootstrap.min.css"       -o "$BS_DIR/bootstrap.min.css"
curl -fsSL "$BS_CDN/js/bootstrap.bundle.min.js"  -o "$BS_DIR/bootstrap.bundle.min.js"

echo "Downloading Bootstrap Icons ${BI_VER}…"
# The CSS references ./fonts/bootstrap-icons.woff2?... relative to itself, so the
# font files must sit in a fonts/ folder next to the CSS.
curl -fsSL "$BI_CDN/bootstrap-icons.min.css"           -o "$BI_DIR/bootstrap-icons.min.css"
curl -fsSL "$BI_CDN/fonts/bootstrap-icons.woff2"       -o "$BI_DIR/fonts/bootstrap-icons.woff2"
curl -fsSL "$BI_CDN/fonts/bootstrap-icons.woff"        -o "$BI_DIR/fonts/bootstrap-icons.woff"

# Pin stamp (so the vendored version is traceable in git).
cat > "$VENDOR/VENDORED.txt" <<EOF
Vendored frontend assets (served same-origin, no CDN at runtime).
  bootstrap        ${BS_VER}   (MIT, getbootstrap.com)
  bootstrap-icons  ${BI_VER}   (MIT, icons.getbootstrap.com)
Refresh via deploy/vendor-frontend.sh — do not hand-edit.
EOF

echo "Updated: $VENDOR"
echo "Review 'git diff', then bump VERSION + CHANGELOG and deploy."
