"""Modo demo: os quatro bloqueios que faltavam (upload/busca de logo, atualização do
sistema, refresh manual do catálogo) e os controles desabilitados na UI antes do clique.

Os já existentes (senha/2FA, usuários, config/restore de backup, integrações) são
cobertos em test_demo_account.py / test_2fa.py / test_backup.py / test_integrations.py
— este arquivo cobre só o que a task pediu de novo.

Armadilha (ver docs/ARMADILHAS.md e tests/test_ui_v138.py): `routes/admin.py` faz
`from app import ... DEMO_MODE` — um nome PRÓPRIO nesse módulo. `demo_blocked` (definido
em app.py) lê o `DEMO_MODE` de app.py, então monkeypatchar `app_module.DEMO_MODE` basta
para ele. Mas o `if DEMO_MODE:` inline em `admin_update_run` lê o nome de
`routes.admin`, que é uma referência SEPARADA — por isso `_enable_demo` patcha os dois.
"""
import io


def _enable_demo(app_module, monkeypatch):
    monkeypatch.setattr(app_module, "DEMO_MODE", True)
    import routes.admin as admin_mod
    monkeypatch.setattr(admin_mod, "DEMO_MODE", True)


# ── POST /admin/brands/upload ──────────────────────────────────────────────────

def test_brand_upload_blocked_in_demo_no_file_written(auth_client, app_module, db, monkeypatch, tmp_path):
    import routes.admin as admin_mod
    brands_dir = tmp_path / "brands"
    monkeypatch.setattr(admin_mod, "BRANDS_DIR", brands_dir)
    db.create_brand("Acme")
    _enable_demo(app_module, monkeypatch)

    resp = auth_client.post("/admin/brands/upload", data={
        "brand_name": "Acme",
        "logo": (io.BytesIO(b"fake-png-bytes"), "logo.png"),
    }, content_type="multipart/form-data")

    assert resp.status_code == 302  # demo_blocked redireciona
    assert not brands_dir.exists() or not any(brands_dir.iterdir())
    assert db.get_brand("Acme")["logo_path"] == ""


def test_brand_upload_works_when_demo_off(auth_client, db, monkeypatch, tmp_path):
    import routes.admin as admin_mod
    brands_dir = tmp_path / "brands"
    monkeypatch.setattr(admin_mod, "BRANDS_DIR", brands_dir)
    db.create_brand("Acme")

    resp = auth_client.post("/admin/brands/upload", data={
        "brand_name": "Acme",
        "logo": (io.BytesIO(b"fake-png-bytes"), "logo.png"),
    }, content_type="multipart/form-data")

    assert resp.status_code == 302
    assert (brands_dir / "acme.png").exists()
    assert db.get_brand("Acme")["logo_path"] == "brands/acme.png"


# ── POST /admin/brands/fetch ────────────────────────────────────────────────────

def test_brand_fetch_blocked_in_demo_no_network_call(auth_client, app_module, db, monkeypatch):
    import routes.admin as admin_mod
    calls = []
    monkeypatch.setattr(admin_mod, "_fetch_brand_logo", lambda name, domain: calls.append((name, domain)) or True)
    db.create_brand("Acme")
    _enable_demo(app_module, monkeypatch)

    resp = auth_client.post("/admin/brands/fetch", data={
        "brand_name": "Acme", "domain": "acme.com",
    })

    assert resp.status_code == 302  # demo_blocked redireciona
    assert calls == []
    assert db.get_brand("Acme")["domain"] == ""  # update_brand_domain também não rodou


def test_brand_fetch_works_when_demo_off(auth_client, db, monkeypatch):
    import routes.admin as admin_mod
    calls = []
    monkeypatch.setattr(admin_mod, "_fetch_brand_logo", lambda name, domain: calls.append((name, domain)) or True)
    db.create_brand("Acme")

    resp = auth_client.post("/admin/brands/fetch", data={
        "brand_name": "Acme", "domain": "acme.com",
    })

    assert resp.status_code == 302
    assert calls == [("Acme", "acme.com")]
    assert db.get_brand("Acme")["domain"] == "acme.com"


# ── POST /admin/brands/new (a marca em si fica permitida — é dado do banco,
#    resetado todo dia; só o FETCH do logo, que grava arquivo, é bloqueado) ─────

def test_brand_new_with_domain_in_demo_creates_brand_but_skips_fetch(auth_client, app_module, db, monkeypatch, tmp_path):
    import routes.admin as admin_mod
    brands_dir = tmp_path / "brands"
    monkeypatch.setattr(admin_mod, "BRANDS_DIR", brands_dir)
    calls = []
    monkeypatch.setattr(admin_mod, "_fetch_brand_logo", lambda name, domain: calls.append((name, domain)) or True)
    _enable_demo(app_module, monkeypatch)

    resp = auth_client.post("/admin/brands/new", data={
        "name": "Acme", "domain": "acme.com",
    })

    assert resp.status_code == 302
    assert calls == []                                    # não tentou baixar
    assert not brands_dir.exists() or not any(brands_dir.iterdir())  # nada gravado
    row = db.get_brand("Acme")
    assert row is not None                                # a marca foi criada
    assert row["domain"] == "acme.com"                    # domínio foi salvo


def test_brand_new_with_domain_works_when_demo_off(auth_client, db, monkeypatch, tmp_path):
    import routes.admin as admin_mod
    brands_dir = tmp_path / "brands"
    monkeypatch.setattr(admin_mod, "BRANDS_DIR", brands_dir)
    calls = []
    monkeypatch.setattr(admin_mod, "_fetch_brand_logo", lambda name, domain: calls.append((name, domain)) or True)

    resp = auth_client.post("/admin/brands/new", data={
        "name": "Acme", "domain": "acme.com",
    })

    assert resp.status_code == 302
    assert calls == [("Acme", "acme.com")]                # fetch chamado normalmente
    assert db.get_brand("Acme")["domain"] == "acme.com"


# ── POST /admin/update/run ──────────────────────────────────────────────────────

def test_update_run_blocked_in_demo_no_flag_written(auth_client, app_module, db, monkeypatch):
    flag = db.DB_PATH.parent / ".update-requested"
    if flag.exists():
        flag.unlink()
    _enable_demo(app_module, monkeypatch)

    resp = auth_client.post("/admin/update/run",
                            headers={"X-Requested-With": "XMLHttpRequest"})

    assert resp.status_code == 403
    body = resp.get_json()
    assert body["ok"] is False
    assert body["error"] == "Função desabilitada na versão demonstrativa."
    assert not flag.exists()


def test_update_run_works_when_demo_off(auth_client, db):
    """Regressão do comportamento existente (já coberto em test_smoke.py), repetida
    aqui só para deixar o par bloqueado/liberado lado a lado neste arquivo."""
    flag = db.DB_PATH.parent / ".update-requested"
    if flag.exists():
        flag.unlink()
    resp = auth_client.post("/admin/update/run",
                            headers={"X-Requested-With": "XMLHttpRequest"})
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True
    assert flag.exists()


# ── POST /admin/catalog/refresh ─────────────────────────────────────────────────

def test_catalog_refresh_blocked_in_demo_no_fetch(auth_client, app_module, db, monkeypatch):
    import routes.admin as admin_mod
    calls = []
    monkeypatch.setattr(admin_mod.spoolmandb_refresh, "fetch_and_write",
                        lambda dest, timeout=30, vendored=False: calls.append(dest) or {
                            "fetched": "2026-09-27", "brands": 1, "materials": 1, "filaments": 1,
                        })
    _enable_demo(app_module, monkeypatch)

    resp = auth_client.post("/admin/catalog/refresh")

    assert resp.status_code == 302  # demo_blocked redireciona
    assert calls == []
    assert db.get_setting("catalog_refresh_result", "") == ""
    assert db.get_setting("catalog_refresh_last_run", "") == ""


def test_catalog_refresh_works_when_demo_off(auth_client, db, monkeypatch):
    import routes.admin as admin_mod
    monkeypatch.setattr(
        admin_mod.spoolmandb_refresh, "fetch_and_write",
        lambda dest, timeout=30, vendored=False: {
            "fetched": "2026-09-27", "brands": 1, "materials": 1, "filaments": 1,
        },
    )
    resp = auth_client.post("/admin/catalog/refresh")
    assert resp.status_code == 302
    assert db.get_setting("catalog_refresh_result") == "ok"


# ── UI: /admin/settings mostra o fieldset desabilitado + o aviso só em demo ────

def test_settings_page_disabled_and_noted_in_demo(auth_client, app_module, monkeypatch):
    _enable_demo(app_module, monkeypatch)
    html = auth_client.get("/admin/settings").get_data(as_text=True)
    assert "Configurações bloqueadas na versão demonstrativa." in html
    assert "<fieldset disabled>" in html


def test_settings_page_enabled_and_no_note_when_demo_off(auth_client):
    html = auth_client.get("/admin/settings").get_data(as_text=True)
    assert "Configurações bloqueadas na versão demonstrativa." not in html
    assert "<fieldset disabled>" not in html


# ── Regressão: POST /admin/settings em demo não muda nada (bloqueio já existente) ─

def test_settings_post_in_demo_leaves_settings_unchanged(auth_client, app_module, db, monkeypatch):
    db.set_setting("app_base_url", "http://original.example")
    _enable_demo(app_module, monkeypatch)

    resp = auth_client.post("/admin/settings", data={
        "app_base_url": "http://attacker.example",
    })

    assert resp.status_code == 302
    assert db.get_setting("app_base_url") == "http://original.example"
