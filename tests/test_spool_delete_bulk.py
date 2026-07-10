"""Testes de v1.37.0:

  - Exclusão permanente de rolo (db.delete_spool + rota admin-only).
  - Cadastro em lote (campo Quantidade cria N rolos idênticos).
"""
from conftest import ADMIN_USER, ADMIN_PASS


def _make_filament(db):
    return db.create_filament(brand="Acme", material="PLA", family="PLA",
                              color_hex="#ffffff")


def _make_spool(db, fid, nominal=1000.0):
    return db.create_spool(filament_id=fid, spool_model_id=None, custom_tare_g=200.0,
                           nominal_weight_g=nominal, location="", purchase_date="",
                           purchase_price=None, notes="")


# ── Exclusão permanente (cascade) ────────────────────────────────────────────

def test_delete_spool_cascades(db):
    """delete_spool apaga o rolo, o histórico de pesagens e a entrada na fila."""
    fid = _make_filament(db)
    sid = _make_spool(db, fid)
    db.add_weight_reading(sid, gross_weight_g=800.0, tare_weight_g=200.0)
    db.queue_add(sid)
    assert db.get_spool(sid) is not None
    assert db.list_weight_readings(spool_id=sid)
    assert db.is_in_queue(sid)

    db.delete_spool(sid)

    assert db.get_spool(sid) is None
    assert db.list_weight_readings(spool_id=sid) == []
    assert not db.is_in_queue(sid)


def test_delete_route_admin_only(viewer_client, auth_client, db):
    """POST /spools/<id>/delete é 403 p/ viewer e remove o rolo p/ admin."""
    fid = _make_filament(db)
    sid = _make_spool(db, fid)

    assert viewer_client.post(f"/spools/{sid}/delete", data={}).status_code == 403
    assert db.get_spool(sid) is not None  # viewer não conseguiu apagar

    resp = auth_client.post(f"/spools/{sid}/delete", data={})
    assert resp.status_code == 302
    assert db.get_spool(sid) is None


def test_delete_unknown_spool_404(auth_client):
    assert auth_client.post("/spools/999999/delete", data={}).status_code == 404


# ── Cadastro em lote (Quantidade) ────────────────────────────────────────────

def test_bulk_create_makes_n_spools(auth_client, db):
    fid = _make_filament(db)
    resp = auth_client.post("/spools/new", data={
        "filament_id": str(fid), "nominal_weight_g": "1000", "quantity": "3",
    })
    assert resp.status_code == 302
    assert "/spools?created=" in resp.headers["Location"]
    assert len(db.list_spools()) == 3


def test_single_create_keeps_detail_flow(auth_client, db):
    """Quantidade 1 (default) mantém o fluxo antigo: vai ao detalhe c/ queue_prompt."""
    fid = _make_filament(db)
    resp = auth_client.post("/spools/new", data={
        "filament_id": str(fid), "nominal_weight_g": "1000", "quantity": "1",
    })
    assert resp.status_code == 302
    loc = resp.headers["Location"]
    sid = db.list_spools()[0]["id"]
    assert f"/spools/{sid}" in loc and "queue_prompt=1" in loc


def test_bulk_create_clamps_quantity(auth_client, db):
    """Quantidade acima do teto (50) é limitada; entrada inválida vira 1."""
    fid = _make_filament(db)
    auth_client.post("/spools/new", data={
        "filament_id": str(fid), "nominal_weight_g": "1000", "quantity": "999",
    })
    assert len(db.list_spools()) == 50


# ── Renderização da UI ───────────────────────────────────────────────────────

def test_list_shows_delete_and_finish_for_admin(auth_client, db):
    fid = _make_filament(db)
    sid = _make_spool(db, fid)
    html = auth_client.get("/spools").get_data(as_text=True)
    assert f"/spools/{sid}/delete" in html      # botão excluir (admin)
    assert f"/spools/{sid}/deactivate" in html  # botão finalizar (escrita)


def test_list_hides_delete_for_viewer(viewer_client, auth_client, db):
    fid = _make_filament(db)
    sid = _make_spool(db, fid)
    html = viewer_client.get("/spools").get_data(as_text=True)
    assert f"/spools/{sid}/delete" not in html      # excluir é só admin
    assert f"/spools/{sid}/deactivate" not in html  # finalizar exige escrita


def test_new_form_has_quantity_field(auth_client):
    html = auth_client.get("/spools/new").get_data(as_text=True)
    assert 'name="quantity"' in html


def test_created_modal_renders(auth_client, db):
    fid = _make_filament(db)
    a, b = _make_spool(db, fid), _make_spool(db, fid)
    html = auth_client.get(f"/spools?created={a},{b}").get_data(as_text=True)
    assert "createdQueueModal" in html
    assert html.count('name="spool_ids"') >= 2
