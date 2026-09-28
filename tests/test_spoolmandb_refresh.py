"""Testes do catálogo de filamentos (SpoolmanDB): transformação pura
(spoolmandb_refresh.build_snapshot), download+escrita atômica (fetch_and_write,
com a rede sempre mockada), precedência das duas cópias e reload por mtime
(filament_catalog), a rota manual /admin/catalog/refresh e a resiliência do
caminho do cron (run_scheduled_refresh nunca levanta). Nenhum teste toca a rede."""
import json

import pytest


# ── Transformação pura (build_snapshot) ─────────────────────────────────────

def test_build_snapshot_dedupes_variants():
    import spoolmandb_refresh as r
    filaments = [
        {"manufacturer": "Acme", "material": "PLA", "finish": "Matte", "name": "Red",
         "color_hex": "FF0000", "diameter": 1.75},
        # SpoolmanDB lista uma entrada por peso/spool — mesmos campos relevantes, dedup.
        {"manufacturer": "Acme", "material": "PLA", "finish": "Matte", "name": "Red",
         "color_hex": "FF0000", "diameter": 1.75},
    ]
    snap = r.build_snapshot(filaments, [])
    assert len(snap["filaments"]) == 1


def test_build_snapshot_cleans_glossy_and_blank_finish():
    import spoolmandb_refresh as r
    filaments = [
        {"manufacturer": "Acme", "material": "PLA", "finish": "glossy", "name": "Red",
         "color_hex": "ff0000", "diameter": 1.75},
        {"manufacturer": "Acme", "material": "PLA", "finish": "", "name": "Blue",
         "color_hex": "0000ff", "diameter": 1.75},
        {"manufacturer": "Acme", "material": "PLA", "finish": "none", "name": "Green",
         "color_hex": "00ff00", "diameter": 1.75},
    ]
    snap = r.build_snapshot(filaments, [])
    assert all(f["finish"] == "" for f in snap["filaments"])


def test_build_snapshot_titlecases_other_finishes():
    import spoolmandb_refresh as r
    filaments = [{"manufacturer": "Acme", "material": "PLA", "finish": "silk", "name": "Gold",
                  "color_hex": "ffd700", "diameter": 1.75}]
    snap = r.build_snapshot(filaments, [])
    assert snap["filaments"][0]["finish"] == "Silk"


def test_build_snapshot_sorts_by_brand_material_finish_color():
    import spoolmandb_refresh as r
    filaments = [
        {"manufacturer": "Zeta", "material": "PLA", "finish": "", "name": "Z",
         "color_hex": "000000", "diameter": 1.75},
        {"manufacturer": "Acme", "material": "PLA", "finish": "", "name": "A",
         "color_hex": "ffffff", "diameter": 1.75},
    ]
    snap = r.build_snapshot(filaments, [])
    assert [f["brand"] for f in snap["filaments"]] == ["Acme", "Zeta"]


def test_build_snapshot_skips_entries_without_brand_or_material():
    import spoolmandb_refresh as r
    filaments = [
        {"manufacturer": "", "material": "PLA", "name": "X", "color_hex": "", "diameter": 1.75},
        {"manufacturer": "Acme", "material": "", "name": "X", "color_hex": "", "diameter": 1.75},
        {"manufacturer": "Acme", "material": "PLA", "name": "X", "color_hex": "", "diameter": 1.75},
    ]
    snap = r.build_snapshot(filaments, [])
    assert len(snap["filaments"]) == 1


def test_build_snapshot_unions_materials_from_materials_json():
    import spoolmandb_refresh as r
    filaments = [{"manufacturer": "Acme", "material": "PLA", "name": "X", "color_hex": "", "diameter": 1.75}]
    materials = [{"material": "PETG"}, {"material": "PLA"}]
    snap = r.build_snapshot(filaments, materials)
    assert set(snap["materials"]) == {"PLA", "PETG"}


def test_build_snapshot_vendored_vs_server_wording():
    import spoolmandb_refresh as r
    fil = [{"manufacturer": "A", "material": "PLA", "name": "", "color_hex": "", "diameter": 1.75}]
    snap_v = r.build_snapshot(fil, [], fetched="2026-01-01", vendored=True)
    snap_s = r.build_snapshot(fil, [], fetched="2026-01-01", vendored=False)
    assert "VENDORED" in snap_v["_source"] and "do not hand-edit" in snap_v["_source"]
    assert "VENDORED" not in snap_s["_source"]
    assert snap_v["fetched"] == snap_s["fetched"] == "2026-01-01"
    # Atribuição MIT presente nos dois (upstream exige).
    assert "MIT" in snap_v["_source"] and "MIT" in snap_s["_source"]


# ── Filamentos translúcidos/transparentes (v1.39.2) ─────────────────────────
# color_hex de 8 dígitos do upstream é AARRGGBB (confirmado contra o próprio
# JSON: "Neon Green" 3C8AD77F só faz sentido com alfa=3C + RGB=8AD77F — a
# leitura RRGGBBAA daria azul). Alfa < 0xFF -> translúcido. Ver _normalize_hex.

def test_normalize_hex_8digit_splits_alpha_and_rgb():
    import spoolmandb_refresh as r
    rgb, translucent = r._normalize_hex("3C8AD77F")
    assert rgb.lower() == "8ad77f"
    assert translucent is True


def test_normalize_hex_8digit_opaque_alpha_not_translucent():
    import spoolmandb_refresh as r
    rgb, translucent = r._normalize_hex("FF112233")
    assert rgb.lower() == "112233"
    assert translucent is False


def test_normalize_hex_6digit_has_no_alpha():
    import spoolmandb_refresh as r
    rgb, translucent = r._normalize_hex("ff0000")
    assert rgb == "ff0000"
    assert translucent is False


def test_normalize_hex_empty():
    import spoolmandb_refresh as r
    rgb, translucent = r._normalize_hex("")
    assert rgb == "" and translucent is False


def test_build_snapshot_derives_translucent_from_alpha_even_if_upstream_flag_false():
    import spoolmandb_refresh as r
    filaments = [{"manufacturer": "Acme", "material": "PETG", "name": "Clear",
                  "color_hex": "00FFFFFF", "diameter": 1.75, "translucent": False}]
    snap = r.build_snapshot(filaments, [])
    f = snap["filaments"][0]
    assert f["color_hex"] == "#ffffff"
    assert f["translucent"] is True


def test_build_snapshot_derives_translucent_from_upstream_flag_alone():
    import spoolmandb_refresh as r
    filaments = [{"manufacturer": "Acme", "material": "PLA", "name": "Solid",
                  "color_hex": "ff0000", "diameter": 1.75, "translucent": True}]
    snap = r.build_snapshot(filaments, [])
    assert snap["filaments"][0]["translucent"] is True


def test_build_snapshot_opaque_6digit_and_flag_false_is_not_translucent():
    import spoolmandb_refresh as r
    filaments = [{"manufacturer": "Acme", "material": "PLA", "name": "Solid",
                  "color_hex": "ff0000", "diameter": 1.75, "translucent": False}]
    snap = r.build_snapshot(filaments, [])
    assert snap["filaments"][0]["translucent"] is False


def test_build_snapshot_translucent_is_part_of_dedup_key():
    import spoolmandb_refresh as r
    filaments = [
        {"manufacturer": "Acme", "material": "PLA", "name": "Red", "color_hex": "ff0000",
         "diameter": 1.75, "translucent": False},
        {"manufacturer": "Acme", "material": "PLA", "name": "Red", "color_hex": "ff0000",
         "diameter": 1.75, "translucent": True},
    ]
    snap = r.build_snapshot(filaments, [])
    # Mesma marca/material/cor/hex/diâmetro, translucent diferente -> NÃO dedup.
    assert len(snap["filaments"]) == 2
    assert {f["translucent"] for f in snap["filaments"]} == {True, False}


def test_filament_catalog_api_includes_translucent_field(auth_client):
    """O snapshot vendorado real (pós-refresh) já carrega `translucent` — a API
    só repassa o que está no JSON, então isto cobre static/filament-catalog.js
    sem precisar simular o clique no botão de import."""
    resp = auth_client.get("/api/filament-catalog")
    data = resp.get_json()
    assert data["filaments"], "catálogo vazio nos testes — vendor refresh não rodou?"
    assert "translucent" in data["filaments"][0]


# ── fetch_and_write: download mockado + escrita atômica ─────────────────────

def _fake_download(fil, mat):
    def _download(url, timeout):
        return fil if "filaments" in url else mat
    return _download


def test_fetch_and_write_writes_file_and_returns_counts(tmp_path, monkeypatch):
    import spoolmandb_refresh as r
    fil = [{"manufacturer": "Acme", "material": "PLA", "name": "Red", "color_hex": "ff0000", "diameter": 1.75}]
    monkeypatch.setattr(r, "_download_json", _fake_download(fil, [{"material": "PLA"}]))
    dest = tmp_path / "out.json"
    result = r.fetch_and_write(dest)
    assert dest.exists()
    assert result == {"fetched": result["fetched"], "brands": 1, "materials": 1, "filaments": 1}
    data = json.loads(dest.read_text(encoding="utf-8"))
    assert data["filaments"][0]["brand"] == "Acme"


def test_fetch_and_write_empty_filaments_raises_and_keeps_existing_file(tmp_path, monkeypatch):
    import spoolmandb_refresh as r
    dest = tmp_path / "out.json"
    dest.write_text('{"keep": true}', encoding="utf-8")
    monkeypatch.setattr(r, "_download_json", lambda url, timeout: [])
    with pytest.raises(ValueError):
        r.fetch_and_write(dest)
    # Falha ANTES de tocar no destino — o arquivo existente sobrevive intacto.
    assert json.loads(dest.read_text(encoding="utf-8")) == {"keep": True}


def test_fetch_and_write_network_error_propagates_and_keeps_existing_file(tmp_path, monkeypatch):
    import spoolmandb_refresh as r
    dest = tmp_path / "out.json"
    dest.write_text('{"keep": true}', encoding="utf-8")

    def boom(url, timeout):
        raise OSError("rede fora do ar")
    monkeypatch.setattr(r, "_download_json", boom)
    with pytest.raises(OSError):
        r.fetch_and_write(dest)
    assert json.loads(dest.read_text(encoding="utf-8")) == {"keep": True}


# ── Precedência das duas cópias (filament_catalog) ───────────────────────────

def _snapshot(fetched):
    return {
        "_source": "test",
        "fetched": fetched,
        "brands": ["Acme"],
        "materials": ["PLA"],
        "filaments": [{"brand": "Acme", "material": "PLA", "finish": "", "color": "",
                       "color_hex": "", "diameter": 1.75}],
    }


def _write_runtime_copy(catalog, fetched):
    p = catalog.runtime_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(_snapshot(fetched)), encoding="utf-8")
    catalog._state["sig"] = "unset"   # força reavaliação nesta chamada (não depende do mtime real)
    return p


def test_runtime_copy_preferred_when_newer(app_module, db):
    import filament_catalog as catalog
    _write_runtime_copy(catalog, "2099-01-01")
    info = catalog.info()
    assert info == {"fetched": "2099-01-01", "source": "server"}


def test_vendored_used_when_runtime_older(app_module, db):
    import filament_catalog as catalog
    _write_runtime_copy(catalog, "1999-01-01")
    info = catalog.info()
    assert info["source"] == "vendored"


def test_runtime_used_when_fetched_dates_equal(app_module, db):
    import filament_catalog as catalog
    vendored_fetched = json.load(open(catalog.VENDORED_PATH, encoding="utf-8"))["fetched"]
    _write_runtime_copy(catalog, vendored_fetched)
    assert catalog.info()["source"] == "server"


def test_corrupt_runtime_copy_falls_back_to_vendored(app_module, db):
    import filament_catalog as catalog
    p = catalog.runtime_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{not valid json", encoding="utf-8")
    catalog._state["sig"] = "unset"
    info = catalog.info()
    assert info["source"] == "vendored"
    assert catalog.available() is True   # o vendorado do repo cobre a falha


def test_missing_both_copies_gives_empty_lists(app_module, db, monkeypatch):
    import filament_catalog as catalog
    monkeypatch.setattr(catalog, "VENDORED_PATH", str(db.DB_PATH.parent / "does-not-exist.json"))
    catalog._state["sig"] = "unset"
    assert catalog.available() is False
    assert catalog.get_brands() == [] and catalog.get_materials() == [] and catalog.get_filaments() == []
    assert catalog.info() == {"fetched": "", "source": ""}


def test_reload_picks_up_write_without_reimport(app_module, db):
    """Mesmo processo, mesmo módulo já importado — nenhum restart necessário
    (simula os dois workers do gunicorn vendo o refresh de um deles)."""
    import filament_catalog as catalog
    catalog._state["sig"] = "unset"
    assert catalog.info()["source"] == "vendored"   # baseline: ainda sem cópia em data/
    _write_runtime_copy(catalog, "2099-06-01")
    assert catalog.info()["source"] == "server"
    assert catalog.info()["fetched"] == "2099-06-01"


def test_legacy_module_attributes_still_work(app_module, db):
    """`catalog.BRANDS`/`.MATERIALS`/`.FILAMENTS` (PEP 562 __getattr__) continuam
    funcionando para quem lê os atributos de módulo antigos."""
    import filament_catalog as catalog
    catalog._state["sig"] = "unset"
    assert catalog.BRANDS and catalog.MATERIALS and catalog.FILAMENTS
    with pytest.raises(AttributeError):
        catalog.NOT_A_REAL_ATTRIBUTE


# ── Rota manual /admin/catalog/refresh (rede sempre mockada) ────────────────

def test_admin_catalog_refresh_success_flashes_counts_and_saves_settings(auth_client, db, monkeypatch):
    import routes.admin as admin_mod
    monkeypatch.setattr(
        admin_mod.spoolmandb_refresh, "fetch_and_write",
        lambda dest, timeout=30, vendored=False: {
            "fetched": "2026-09-27", "brands": 3, "materials": 2, "filaments": 10,
        },
    )
    resp = auth_client.post("/admin/catalog/refresh")
    assert resp.status_code == 302
    assert "/admin/update" in resp.headers["Location"]
    assert db.get_setting("catalog_refresh_result") == "ok"
    assert db.get_setting("catalog_refresh_error", "") == ""
    assert db.get_setting("catalog_refresh_last_run", "")
    assert db.get_setting("catalog_refresh_source") == "manual"


def test_admin_catalog_refresh_failure_flashes_error_and_saves_settings(auth_client, db, monkeypatch):
    import routes.admin as admin_mod

    def boom(dest, timeout=30, vendored=False):
        raise OSError("rede indisponível")
    monkeypatch.setattr(admin_mod.spoolmandb_refresh, "fetch_and_write", boom)
    resp = auth_client.post("/admin/catalog/refresh")
    assert resp.status_code == 302
    assert db.get_setting("catalog_refresh_result") == "error"
    assert "rede indisponível" in db.get_setting("catalog_refresh_error")
    assert db.get_setting("catalog_refresh_source") == "manual"


def test_admin_catalog_refresh_forbidden_for_viewer(viewer_client):
    resp = viewer_client.post("/admin/catalog/refresh")
    assert resp.status_code == 403


def test_admin_catalog_refresh_requires_login(client):
    resp = client.post("/admin/catalog/refresh")
    assert resp.status_code in (302, 401, 403)


def test_admin_update_page_shows_catalog_section(auth_client):
    resp = auth_client.get("/admin/update")
    assert resp.status_code == 200
    assert b"catalog/refresh" in resp.data


# ── Rótulo "Última atualização" (auto) x manual, sem sufixo (v1.39.3) ───────

def test_update_page_shows_auto_suffix_after_scheduled_refresh(auth_client, db, monkeypatch):
    import spoolmandb_refresh as r
    fil = [{"manufacturer": "Acme", "material": "PLA", "name": "Red", "color_hex": "ff0000", "diameter": 1.75}]
    monkeypatch.setattr(r, "_download_json", _fake_download(fil, []))
    assert r.run_scheduled_refresh(force=True) is not None
    assert db.get_setting("catalog_refresh_source") == "auto"

    resp = auth_client.get("/admin/update")
    assert resp.status_code == 200
    assert "Última atualização".encode("utf-8") in resp.data
    assert b"(auto)" in resp.data
    assert "Última atualização automática".encode("utf-8") not in resp.data


def test_update_page_shows_no_auto_suffix_after_manual_refresh(auth_client, db, monkeypatch):
    import routes.admin as admin_mod
    monkeypatch.setattr(
        admin_mod.spoolmandb_refresh, "fetch_and_write",
        lambda dest, timeout=30, vendored=False: {
            "fetched": "2026-09-27", "brands": 1, "materials": 1, "filaments": 1,
        },
    )
    resp = auth_client.post("/admin/catalog/refresh")
    assert resp.status_code == 302
    assert db.get_setting("catalog_refresh_source") == "manual"

    resp = auth_client.get("/admin/update")
    assert resp.status_code == 200
    assert b"(auto)" not in resp.data


def test_update_page_still_shows_error_after_manual_failure(auth_client, db, monkeypatch):
    import routes.admin as admin_mod

    def boom(dest, timeout=30, vendored=False):
        raise OSError("rede indisponível")
    monkeypatch.setattr(admin_mod.spoolmandb_refresh, "fetch_and_write", boom)
    auth_client.post("/admin/catalog/refresh")

    resp = auth_client.get("/admin/update")
    assert resp.status_code == 200
    assert "rede indisponível".encode("utf-8") in resp.data


# ── Caminho do cron: run_scheduled_refresh NUNCA levanta ────────────────────

def test_run_scheduled_refresh_failure_does_not_raise(app_module, db, monkeypatch):
    import spoolmandb_refresh as r

    def boom(url, timeout):
        raise OSError("rede fora do ar")
    monkeypatch.setattr(r, "_download_json", boom)
    result = r.run_scheduled_refresh(force=True)
    assert result is None
    assert db.get_setting("catalog_refresh_result") == "error"
    assert "rede fora do ar" in db.get_setting("catalog_refresh_error")
    assert db.get_setting("catalog_refresh_source") == "auto"


def test_run_scheduled_refresh_success_writes_settings_and_file(app_module, db, monkeypatch):
    import spoolmandb_refresh as r
    fil = [{"manufacturer": "Acme", "material": "PLA", "name": "Red", "color_hex": "ff0000", "diameter": 1.75}]
    monkeypatch.setattr(r, "_download_json", _fake_download(fil, []))
    result = r.run_scheduled_refresh(force=True)
    assert result is not None
    assert db.get_setting("catalog_refresh_result") == "ok"
    assert (db.DB_PATH.parent / "spoolman_catalog.json").exists()


def test_run_scheduled_refresh_skips_when_already_ok_today(app_module, db, monkeypatch):
    import spoolmandb_refresh as r
    fil = [{"manufacturer": "Acme", "material": "PLA", "name": "Red", "color_hex": "ff0000", "diameter": 1.75}]
    monkeypatch.setattr(r, "_download_json", _fake_download(fil, []))
    assert r.run_scheduled_refresh(force=True) is not None

    calls = {"n": 0}

    def counting(url, timeout):
        calls["n"] += 1
        return fil if "filaments" in url else []
    monkeypatch.setattr(r, "_download_json", counting)
    assert r.run_scheduled_refresh() is None   # já ok hoje, sem force → no-op
    assert calls["n"] == 0


def test_run_scheduled_refresh_skips_when_manual_refresh_already_ok_today(app_module, db, monkeypatch):
    """Decisão deliberada: o gate diário é agnóstico à origem — um refresh MANUAL
    bem-sucedido hoje também evita que o cron bata no upstream de novo hoje."""
    import spoolmandb_refresh as r
    db.set_setting("catalog_refresh_last_run", db.now_iso())
    db.set_setting("catalog_refresh_result", "ok")
    db.set_setting("catalog_refresh_source", "manual")

    calls = {"n": 0}

    def counting(url, timeout):
        calls["n"] += 1
        return [] if "materials" in url else [
            {"manufacturer": "Acme", "material": "PLA", "name": "Red", "color_hex": "ff0000", "diameter": 1.75}
        ]
    monkeypatch.setattr(r, "_download_json", counting)
    assert r.run_scheduled_refresh() is None
    assert calls["n"] == 0
