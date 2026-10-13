"""Finishing a spool from its detail page (v1.39.17)."""


def _spool(db):
    fid = db.create_filament(brand="Acme", material="PLA", family="PLA", color_hex="#ffffff")
    return db.create_spool(filament_id=fid, spool_model_id=None, custom_tare_g=200.0,
                           nominal_weight_g=1000.0, location="", purchase_date="",
                           purchase_price=None, notes="")


def test_deactivate_with_next_returns_to_detail(auth_client, db):
    sid = _spool(db)
    r = auth_client.post(f"/spools/{sid}/deactivate", data={"next": f"/spools/{sid}"})
    assert r.status_code == 302
    assert r.headers["Location"].endswith(f"/spools/{sid}")
    assert not db.get_spool(sid)["active"]


def test_deactivate_without_next_goes_to_list(auth_client, db):
    sid = _spool(db)
    r = auth_client.post(f"/spools/{sid}/deactivate", data={})
    assert r.status_code == 302
    assert r.headers["Location"].endswith("/spools")
    assert not db.get_spool(sid)["active"]


def test_deactivate_ignores_external_next(auth_client, db):
    sid = _spool(db)
    r = auth_client.post(f"/spools/{sid}/deactivate", data={"next": "https://evil.example/"})
    assert r.status_code == 302
    assert "evil.example" not in r.headers["Location"]
    assert r.headers["Location"].endswith("/spools")


def test_detail_shows_finish_form_only_when_active(auth_client, db):
    sid = _spool(db)
    action = f"/spools/{sid}/deactivate"
    assert action in auth_client.get(f"/spools/{sid}").get_data(as_text=True)
    db.deactivate_spool(sid)
    assert action not in auth_client.get(f"/spools/{sid}").get_data(as_text=True)
