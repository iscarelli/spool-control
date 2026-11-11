"""Finish a spool from inside the QR scanner modal (finish.json + modal markup)."""


def _mk(db):
    fid = db.create_filament("MarcaQR", "PETG", "Basic", "#ff8800")
    return db.create_spool(filament_id=fid, spool_model_id=None, custom_tare_g=200.0,
                           nominal_weight_g=1000.0, location="", purchase_date="",
                           purchase_price=None, notes="")


def test_finish_json_finishes_active_spool(auth_client, db):
    sid = _mk(db)
    r = auth_client.post(f"/spools/{sid}/finish.json")
    assert r.status_code == 200
    d = r.get_json()
    assert d["ok"] and d["active"] is False and "stock_msg" in d
    assert not db.get_spool(sid)["active"]


def test_finish_json_404(auth_client):
    r = auth_client.post("/spools/9999/finish.json")
    assert r.status_code == 404 and r.get_json()["ok"] is False


def test_finish_json_already_finished_409(auth_client, db):
    sid = _mk(db)
    db.deactivate_spool(sid)
    r = auth_client.post(f"/spools/{sid}/finish.json")
    assert r.status_code == 409 and r.get_json()["ok"] is False


def test_finish_json_forbidden_for_viewer(viewer_client, db):
    sid = _mk(db)
    assert viewer_client.post(f"/spools/{sid}/finish.json").status_code == 403
    assert db.get_spool(sid)["active"]


def test_finish_json_never_weighed_creates_no_reading(auth_client, db):
    sid = _mk(db)
    assert db.list_weight_readings(spool_id=sid) == []
    d = auth_client.post(f"/spools/{sid}/finish.json").get_json()
    assert d["weighed"] is False
    assert db.list_weight_readings(spool_id=sid) == []


def test_finish_json_stock_msg_when_last_spool(auth_client, db):
    sid = _mk(db)
    d = auth_client.post(f"/spools/{sid}/finish.json").get_json()
    assert "Sem estoque" in d["stock_msg"]


def test_scan_modal_finish_ui_for_writer(auth_client):
    html = auth_client.get("/").get_data(as_text=True)
    assert 'id="qrScanModal"' in html      # dashboard-specific: not the password-change page
    for el in ('id="qrFinishBtn"', 'id="qrFinishPanel"', 'id="qrFinishConfirm"', 'id="qrFinishCancel"'):
        assert el in html, el


def test_scan_modal_finish_hidden_for_viewer(viewer_client):
    html = viewer_client.get("/").get_data(as_text=True)
    assert 'id="qrScanModal"' in html
    assert 'id="qrFinishBtn"' not in html
