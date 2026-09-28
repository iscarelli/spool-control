"""Filament catalog (SpoolmanDB) — transform + refresh.

Single source of the SpoolmanDB → spool-control transform (`build_snapshot`),
shared by:

- `deploy/vendor-spoolmandb.sh` — dev-run, writes the VENDORED snapshot
  (`spoolman_catalog.json` at the repo root, committed to git).
- The runtime refresher (`fetch_and_write`) — used by the daily cron
  (`deploy/backup-cron.py` → `run_scheduled_refresh`) and by the manual
  "update catalog" button on `/admin/update` (`routes/admin.py`). Both write
  to `data/spoolman_catalog.json` (NOT committed — see `filament_catalog.py`
  for how the two copies are reconciled at load time).

Upstream: github.com/Donkie/SpoolmanDB (MIT), compiled JSON served at
https://donkie.github.io/SpoolmanDB/ (`filaments.json`, `materials.json`).
SpoolmanDB has no releases/tags, so each snapshot is stamped with its own
fetch date (`fetched` field) instead of pinning to a version.

Deliberately reverses, for the catalog ONLY, the project's general "no
runtime download" rule (see docs/spoolmandb.md) — kept FAIL-SAFE: a failed
fetch/transform raises without ever touching an existing file, and callers
(cron, admin route) catch it and keep the previous snapshot in place.

Stdlib only (urllib) — no new dependency.
"""
import datetime
import json
import os
import tempfile
import urllib.error
import urllib.request

BASE_URL = "https://donkie.github.io/SpoolmanDB"
FILAMENTS_URL = f"{BASE_URL}/filaments.json"
MATERIALS_URL = f"{BASE_URL}/materials.json"

_ATTRIBUTION = "Attribution: filament data © SpoolmanDB contributors, MIT."


def _clean_finish(f):
    f = (f or "").strip()
    # "glossy" é o acabamento padrão/normal → tratamos como "sem família" (em branco).
    if f.lower() in ("", "glossy", "gloss", "none"):
        return ""
    return f.title()


def _normalize_hex(hexv):
    """Normaliza um `color_hex` do SpoolmanDB (6 ou 8 dígitos) para RGB de 6 dígitos
    (sem `#`) + se o alfa embutido indica translucidez.

    Formato de 8 dígitos é **AARRGGBB** — confirmado contra o upstream (2026-09):
    `3C8AD77F` em "Neon Green" (AmazonBasics) só faz sentido como alfa=`3C` (~24%,
    translúcido) + RGB=`8AD77F` (verde); a leitura RRGGBBAA daria azul. Alfa < 0xFF
    ⇒ translúcido. Uma minoria de entradas de um único contribuidor ("Das Filament")
    parece usar a ordem inversa (RGB primeiro) — ruído dos dados upstream, não
    corrigido aqui: não há como distinguir os dois formatos sem heurística por marca,
    e a maioria (inclusive todo "…FFFFFF" = Clear/Transparent em 5 marcas diferentes)
    bate com AARRGGBB. 6 dígitos: sem alfa, nunca translúcido só pelo hex (só pelo
    campo `translucent` do upstream)."""
    hexv = (hexv or "").strip()
    if len(hexv) == 8:
        alpha_hex, rgb_hex = hexv[:2], hexv[2:]
        try:
            translucent_from_alpha = int(alpha_hex, 16) < 0xFF
        except ValueError:
            translucent_from_alpha = False
        return rgb_hex, translucent_from_alpha
    return hexv, False


def build_snapshot(filaments, materials, fetched=None, vendored=True):
    """Pure transform: `filaments` + `materials` (parsed JSON lists, in the
    SpoolmanDB shape) -> the compact snapshot dict this app stores and serves.

    Dedupes filament variants by (brand, material, finish, color, color_hex,
    diameter) — SpoolmanDB lists one entry per spool weight/size, which we
    don't care about. `materials` supplies the canonical material list, unioned
    with whatever materials show up in `filaments`.

    `vendored=True` stamps the "do not hand-edit, refresh via
    deploy/vendor-spoolmandb.sh" wording used for the committed repo file.
    `vendored=False` is for the server-written copy in `data/` — refreshed
    automatically, so it says how/when it was fetched instead of pointing at
    the dev script.
    """
    seen, out = set(), []
    brands, mats = set(), set()
    for e in filaments:
        brand = (e.get("manufacturer") or "").strip()
        material = (e.get("material") or "").strip()
        rgb_hex, translucent_from_alpha = _normalize_hex(e.get("color_hex"))
        color_hex = ("#" + rgb_hex.lower()) if rgb_hex else ""
        translucent = bool(e.get("translucent")) or translucent_from_alpha
        diameter = e.get("diameter")
        finish = _clean_finish(e.get("finish"))
        color = (e.get("name") or "").strip()
        if not brand or not material:
            continue
        key = (brand, material, finish, color, color_hex, diameter, translucent)
        if key in seen:
            continue  # dedup variantes por peso/spool
        seen.add(key)
        out.append({
            "brand": brand, "material": material, "finish": finish,
            "color": color, "color_hex": color_hex, "diameter": diameter,
            "translucent": translucent,
        })
        brands.add(brand)
        mats.add(material)

    for m in materials:
        name = (m.get("material") or "").strip()
        if name:
            mats.add(name)

    out.sort(key=lambda d: (d["brand"].lower(), d["material"].lower(),
                            d["finish"].lower(), d["color"].lower()))

    fetched = fetched or datetime.date.today().isoformat()
    if vendored:
        source = (
            "VENDORED from SpoolmanDB (github.com/Donkie/SpoolmanDB, MIT license) — "
            f"compiled JSON at {BASE_URL}/ fetched {fetched}. SpoolmanDB has no tags; "
            "this snapshot is the pin. Refresh via deploy/vendor-spoolmandb.sh — do "
            f"not hand-edit. {_ATTRIBUTION}"
        )
    else:
        source = (
            "Fetched from SpoolmanDB (github.com/Donkie/SpoolmanDB, MIT license) — "
            f"compiled JSON at {BASE_URL}/, fetched {fetched} by the server's daily "
            f"catalog refresh (or the admin \"update catalog\" button). {_ATTRIBUTION}"
        )

    return {
        "_source": source,
        "fetched": fetched,
        "brands": sorted(brands, key=str.lower),
        "materials": sorted(mats, key=str.lower),
        "filaments": out,
    }


def _download_json(url, timeout):
    req = urllib.request.Request(url, headers={"User-Agent": "spool-control-catalog-refresh"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


def fetch_and_write(dest_path, timeout=30, vendored=False):
    """Downloads filaments.json + materials.json, transforms them and writes
    the snapshot to `dest_path` ATOMICALLY (temp file in the same dir +
    os.replace). Raises on any failure (network, parse, or an empty/invalid
    result) WITHOUT ever touching an existing file at `dest_path` — callers
    (the cron job, the admin route) are responsible for catching, logging and
    reporting.

    Returns a small dict on success: {"fetched", "brands", "materials",
    "filaments"} (the last three are counts).
    """
    filaments = _download_json(FILAMENTS_URL, timeout)
    materials = _download_json(MATERIALS_URL, timeout)
    if not isinstance(filaments, list) or not filaments:
        raise ValueError("filaments.json vazio ou em formato inesperado")
    if not isinstance(materials, list):
        raise ValueError("materials.json em formato inesperado")

    snapshot = build_snapshot(filaments, materials, vendored=vendored)
    if not snapshot["filaments"]:
        raise ValueError("transformação não produziu nenhum filamento")

    dest_path = str(dest_path)
    dest_dir = os.path.dirname(dest_path) or "."
    os.makedirs(dest_dir, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=dest_dir, prefix=".spoolman_catalog.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(snapshot, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        os.replace(tmp_path, dest_path)  # atômico no mesmo filesystem
    except Exception:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise

    return {
        "fetched": snapshot["fetched"],
        "brands": len(snapshot["brands"]),
        "materials": len(snapshot["materials"]),
        "filaments": len(snapshot["filaments"]),
    }


# ── Refresh agendado (piggyback no cron diário do backup) ────────────────────
# Import tardio de database/logger só quando alguém chama run_scheduled_refresh
# (o cron e a rota admin) — build_snapshot/fetch_and_write acima não dependem
# de Flask nem do banco, e ficam livres para uso isolado/testes.

def _settings_module():
    import database as db
    return db


def already_refreshed_today():
    """True se já houve um refresh BEM-SUCEDIDO hoje (data LOCAL) — mesmo padrão
    de `backup._ran_ok_today()`, chave própria (`catalog_refresh_*`).

    Deliberadamente AGNÓSTICO à origem (`catalog_refresh_source`): um refresh
    manual bem-sucedido também conta para o gate diário, porque o objetivo do
    gate é não bater no upstream do SpoolmanDB mais de uma vez por dia — não
    importa se foi o cron ou o botão do admin que já buscou os dados de hoje."""
    db = _settings_module()
    if db.get_setting("catalog_refresh_result", "") != "ok":
        return False
    last = db.get_setting("catalog_refresh_last_run", "")
    if not last:
        return False
    from datetime import datetime, timezone
    try:
        when = datetime.strptime(last, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return False
    return when.astimezone().date() == datetime.now().date()


def run_scheduled_refresh(force=False, timeout=30):
    """Refresh diário do catálogo, chamado depois do backup em
    `deploy/backup-cron.py` (mesmo tick horário — piggyback no agendamento do
    backup, sem hora própria configurável). Sem `force`, é no-op se já houve
    sucesso hoje. Nunca levanta: falha de rede/parse só grava o erro em
    settings e loga — não pode derrubar o cron nem o backup.

    Retorna o dict de contagens em sucesso, ou None (no-op ou falha)."""
    db = _settings_module()
    import logger as log_cfg
    log = log_cfg.get_logger("spool.catalog_refresh")

    if not force and already_refreshed_today():
        return None

    dest = db.DB_PATH.parent / "spoolman_catalog.json"
    now = db.now_iso()
    try:
        result = fetch_and_write(dest, timeout=timeout, vendored=False)
    except Exception as e:
        db.set_setting("catalog_refresh_last_run", now)
        db.set_setting("catalog_refresh_result", "error")
        db.set_setting("catalog_refresh_error", str(e))
        db.set_setting("catalog_refresh_source", "auto")
        log.error("catalog_refresh.failed", exc_info=True)
        return None

    db.set_setting("catalog_refresh_last_run", now)
    db.set_setting("catalog_refresh_result", "ok")
    db.set_setting("catalog_refresh_error", "")
    db.set_setting("catalog_refresh_source", "auto")
    log.info("catalog_refresh.ok", file=str(dest), **result)
    return result
