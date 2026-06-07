#!/usr/bin/env bash
# ── vendor-niimbot.sh — refresh the vendored Niimbot driver + registry ─────────
#
# spool-control is PUBLIC and the production server clones it anonymously, so the
# Niimbot driver can't be pulled at deploy time — it's VENDORED into this repo.
# The driver's upstream is the public repo iscarelli/niimbot-web-bluetooth.
#
# This script is the one deliberate, reproducible way to update the vendored copy:
# it downloads src/niimbot.js + registry.json from a PINNED tag, stamps the source
# tag/commit onto both, and writes them in place. There is no runtime/deploy-time
# download and no CDN — what's in git is what runs (see docs/niimbot.md).
#
# Usage:
#   deploy/vendor-niimbot.sh              # latest published release
#   deploy/vendor-niimbot.sh v1.2.0       # a specific tag
#
# After running: review `git diff`, bump VERSION + CHANGELOG, commit, deploy.
set -euo pipefail

REPO="iscarelli/niimbot-web-bluetooth"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
JS_DEST="$ROOT/static/niimbot.js"
JSON_DEST="$ROOT/niimbot_registry.json"

api() { curl -fsSL -H "Accept: application/vnd.github+json" "$@"; }

TAG="${1:-}"
if [[ -z "$TAG" ]]; then
  echo "Resolving latest release of $REPO…"
  TAG="$(api "https://api.github.com/repos/$REPO/releases/latest" \
    | grep -m1 '"tag_name"' | sed -E 's/.*"tag_name": *"([^"]+)".*/\1/')"
  [[ -n "$TAG" ]] || { echo "Could not resolve latest release tag." >&2; exit 1; }
fi
echo "Vendoring $REPO @ $TAG"

# Resolve the tag to a commit sha (annotated or lightweight) for the provenance stamp.
SHA="$(api "https://api.github.com/repos/$REPO/commits/$TAG" \
  | grep -m1 '"sha"' | sed -E 's/.*"sha": *"([0-9a-f]+)".*/\1/' | cut -c1-7)"
[[ -n "$SHA" ]] || SHA="unknown"
echo "  commit $SHA"

RAW="https://raw.githubusercontent.com/$REPO/$TAG"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

curl -fsSL "$RAW/src/niimbot.js"   -o "$TMP/niimbot.js"
curl -fsSL "$RAW/registry.json"    -o "$TMP/registry.json"

# ── Driver: prepend the VENDORED header, then the upstream file verbatim ───────
{
  cat <<EOF
/* ── VENDORED — do not edit here ──────────────────────────────────────────────
 * Source: github.com/$REPO  src/niimbot.js @ $TAG
 *         (commit $SHA). The upstream repo is the canonical source of truth.
 * The production server clones the PUBLIC spool-control repo anonymously, so the
 * driver must live in this repo. To refresh, run deploy/vendor-niimbot.sh (it
 * re-downloads this file + niimbot_registry.json at a pinned tag) — never hand-edit.
 * ────────────────────────────────────────────────────────────────────────────── */
EOF
  cat "$TMP/niimbot.js"
} > "$JS_DEST"

# ── Registry: inject a `_source` provenance field, write deterministically ─────
SRC_NOTE="VENDORED from github.com/$REPO registry.json @ $TAG (commit $SHA). Refresh via deploy/vendor-niimbot.sh — do not hand-edit. niimbot_registry.py loads this file; entries with an \`_untested\` key are hidden until validated on hardware."
python3 - "$TMP/registry.json" "$JSON_DEST" "$SRC_NOTE" <<'PY'
import json, sys
src, dest, note = sys.argv[1], sys.argv[2], sys.argv[3]
with open(src, encoding="utf-8") as fh:
    data = json.load(fh)
# Place _source right after _comment (or first) so the provenance is obvious.
out = {}
if "_comment" in data:
    out["_comment"] = data.pop("_comment")
out["_source"] = note
out.update(data)
with open(dest, "w", encoding="utf-8", newline="\n") as fh:
    json.dump(out, fh, ensure_ascii=False, indent=2)
    fh.write("\n")
PY

echo "Updated:"
echo "  $JS_DEST"
echo "  $JSON_DEST"
echo "Review 'git diff', then bump VERSION + CHANGELOG and deploy."
