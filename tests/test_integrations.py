"""Testes das integrações: chaves de API independentes, escopo (HA read-only /
balança read+write), endpoints de leitura do HA e a página Admin → Integrações."""


def _make_spool(db, tare=200.0, nominal=1000.0):
    fid = db.create_filament("MarcaAPI", "PLA", "Basic", "#ff8800")
    return db.create_spool(filament_id=fid, spool_model_id=None, custom_tare_g=tare,
                           nominal_weight_g=nominal, location="C3", purchase_date="",
                           purchase_price=None, notes="")


# ── Seed e escopo ────────────────────────────────────────────────────────────

def test_keys_seeded_with_scope(db):
    scale = db.get_api_key("scale")
    ha = db.get_api_key("homeassistant")
    assert scale and scale["scope"] == "write"
    assert ha and ha["scope"] == "read"
    assert scale["key"] != ha["key"]


def test_scale_key_can_weigh_and_read(client, db):
    sid = _make_spool(db)
    scale_key = db.get_api_key("scale")["key"]
    r = client.post("/api/weigh", json={"spool_id": sid, "gross_weight_g": 1200},
                    headers={"X-API-Key": scale_key})
    assert r.status_code == 200 and r.get_json()["ok"] is True
    assert client.get(f"/api/spools/{sid}", headers={"X-API-Key": scale_key}).status_code == 200


def test_ha_key_is_read_only(client, db):
    sid = _make_spool(db)
    ha_key = db.get_api_key("homeassistant")["key"]
    # Leitura funciona…
    assert client.get("/api/summary", headers={"X-API-Key": ha_key}).status_code == 200
    # …mas gravar pesagem é bloqueado (escopo read).
    r = client.post("/api/weigh", json={"spool_id": sid, "gross_weight_g": 1200},
                    headers={"X-API-Key": ha_key})
    assert r.status_code == 401


def test_no_key_unauthorized(client):
    assert client.get("/api/summary").status_code == 401
    assert client.get("/api/low-stock").status_code == 401


def test_wrong_key_unauthorized(client):
    assert client.get("/api/summary", headers={"X-API-Key": "nope"}).status_code == 401


# ── Independência das chaves (requisito-chave) ───────────────────────────────

def test_rotating_ha_key_does_not_affect_scale(client, db):
    scale_before = db.get_api_key("scale")["key"]
    db.regenerate_api_key("homeassistant")
    scale_after = db.get_api_key("scale")["key"]
    assert scale_before == scale_after
    # A da balança continua válida; a chave ANTIGA do HA não.
    assert client.get("/api/summary", headers={"X-API-Key": scale_after}).status_code == 200


# ── Endpoints de leitura ─────────────────────────────────────────────────────

def test_summary_shape(client, db):
    _make_spool(db)
    ha_key = db.get_api_key("homeassistant")["key"]
    data = client.get("/api/summary", headers={"X-API-Key": ha_key}).get_json()
    assert data["ok"] is True
    assert {"totals", "low_stock", "by_material"} <= set(data)
    assert "net_weight_kg" in data["totals"]


def test_low_stock_reflects_data(client, db):
    sid = _make_spool(db, tare=200, nominal=1000)
    db.add_weight_reading(sid, 250, 200)   # net 50 < 200g → estoque baixo
    ha_key = db.get_api_key("homeassistant")["key"]
    data = client.get("/api/low-stock", headers={"X-API-Key": ha_key}).get_json()
    assert data["count"] >= 1
    item = next(s for s in data["spools"] if s["spool_id"] == sid)
    assert item["code"] == f"SP-{sid:04d}"
    assert item["net_weight_g"] == 50


def test_stock_by_material_and_location(client, db):
    _make_spool(db)
    ha_key = db.get_api_key("homeassistant")["key"]
    data = client.get("/api/stock", headers={"X-API-Key": ha_key}).get_json()
    assert "by_material" in data and "by_location" in data


def test_last_used_updates(client, db):
    ha_key = db.get_api_key("homeassistant")["key"]
    assert db.get_api_key("homeassistant")["last_used_at"] == ""
    client.get("/api/summary", headers={"X-API-Key": ha_key})
    assert db.get_api_key("homeassistant")["last_used_at"] != ""


# ── Página Admin → Integrações ───────────────────────────────────────────────

def test_integrations_page_shows_ha_hides_scale(auth_client):
    r = auth_client.get("/admin/integrations")
    assert r.status_code == 200
    assert b"Home Assistant" in r.data
    # A balança fica oculta: nenhuma ação dela aparece na página.
    assert b"/admin/integrations/scale/" not in r.data


def test_regenerate_via_ui(auth_client, db):
    before = db.get_api_key("homeassistant")["key"]
    r = auth_client.post("/admin/integrations/homeassistant/regenerate")
    assert r.status_code == 302
    assert db.get_api_key("homeassistant")["key"] != before


def test_toggle_via_ui(auth_client, db):
    assert db.get_api_key("homeassistant")["enabled"] == 1
    auth_client.post("/admin/integrations/homeassistant/toggle")
    assert db.get_api_key("homeassistant")["enabled"] == 0


def test_disabled_key_is_rejected(client, db):
    ha_key = db.get_api_key("homeassistant")["key"]
    db.set_api_key_enabled("homeassistant", False)
    assert client.get("/api/summary", headers={"X-API-Key": ha_key}).status_code == 401


def test_unknown_integration_rejected(auth_client, db):
    r = auth_client.post("/admin/integrations/bogus/regenerate")
    assert r.status_code == 302
    assert db.get_api_key("bogus") is None


def test_integrations_requires_admin(client, db):
    from werkzeug.security import generate_password_hash
    db.create_user("viewer1", generate_password_hash("senha-viewer"), role="viewer",
                   must_change=False)
    client.post("/login", data={"username": "viewer1", "password": "senha-viewer"})
    assert client.get("/admin/integrations").status_code == 403
