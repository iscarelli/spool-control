"""Finalizar rolo a partir da página de detalhe (destino do QR da etiqueta)."""


def _make_spool(db, nominal=1000.0):
    fid = db.create_filament(brand="Acme", material="PLA", family="PLA", color_hex="#ffffff")
    return db.create_spool(filament_id=fid, spool_model_id=None, custom_tare_g=200.0,
                           nominal_weight_g=nominal, location="", purchase_date="",
                           purchase_price=None, notes="")


def _detail(client, sid):
    r = client.get(f"/spools/{sid}")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    # guarda contra falso verde (redirect para /account/password renderiza outra página)
    assert f"SP-{sid:04d}" in html and "Etiqueta PDF" in html
    return html


def test_detail_has_finalize_modal_for_writer(auth_client, db):
    sid = _make_spool(db)
    db.add_weight_reading(sid, gross_weight_g=700.0, tare_weight_g=200.0)
    html = _detail(auth_client, sid)
    assert 'id="finalizeModal"' in html
    assert f"/spools/{sid}/deactivate" in html
    assert 'name="return_to" value="detail"' in html
    assert "<strong>500g</strong>" in html and "50%" in html


def test_detail_unweighed_spool_does_not_invent_weight(auth_client, db):
    sid = _make_spool(db)
    html = _detail(auth_client, sid)
    assert 'id="finalizeModal"' in html
    assert "Rolo nunca pesado" in html
    assert "Filamento restante que será baixado" not in html


def test_detail_hides_finalize_for_viewer(viewer_client, auth_client, db):
    sid = _make_spool(db)
    html = _detail(viewer_client, sid)
    assert f"/spools/{sid}/deactivate" not in html
    assert 'id="finalizeModal"' not in html


def test_detail_hides_finalize_when_already_finished(auth_client, db):
    sid = _make_spool(db)
    db.deactivate_spool(sid)
    html = _detail(auth_client, sid)
    assert f"/spools/{sid}/deactivate" not in html
    assert 'id="finalizeModal"' not in html


def test_deactivate_return_to_detail(auth_client, db):
    sid = _make_spool(db)
    r = auth_client.post(f"/spools/{sid}/deactivate", data={"return_to": "detail"})
    assert r.status_code == 302
    assert r.headers["Location"].endswith(f"/spools/{sid}")
    assert not db.get_spool(sid)["active"]


def test_deactivate_default_redirects_to_list(auth_client, db):
    sid = _make_spool(db)
    r = auth_client.post(f"/spools/{sid}/deactivate")
    assert r.status_code == 302
    assert r.headers["Location"].endswith("/spools")
    assert not db.get_spool(sid)["active"]


def test_deactivate_return_to_foreign_url_goes_to_list(auth_client, db):
    sid = _make_spool(db)
    r = auth_client.post(f"/spools/{sid}/deactivate",
                         data={"return_to": "https://evil.example"})
    assert r.status_code == 302
    assert "evil.example" not in r.headers["Location"]
    assert r.headers["Location"].endswith("/spools")


def test_deactivate_nonexistent_is_404(auth_client):
    assert auth_client.post("/spools/99999/deactivate").status_code == 404
