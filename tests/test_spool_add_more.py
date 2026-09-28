"""v1.40.0: "Add more like this" (?from_spool=<id> pre-fills the new-spool form)."""
import re


def _make_filament(db):
    return db.create_filament(brand="Acme", material="PLA", family="PLA",
                              color_hex="#ffffff")


def _make_source(db, fid):
    return db.create_spool(filament_id=fid, spool_model_id=None, custom_tare_g=212.5,
                           nominal_weight_g=750.0, location="Shelf Z9",
                           purchase_date="2020-01-01", purchase_price=42.5,
                           notes="SECRET-NOTE-XYZ")


def test_from_spool_prefills(auth_client, db):
    fid = _make_filament(db)
    sid = _make_source(db, fid)
    resp = auth_client.get(f"/spools/new?from_spool={sid}")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert f"SP-{sid:04d}" in html
    assert 'value="212.5"' in html
    assert 'value="750"' in html
    assert 'value="Shelf Z9"' in html
    assert re.search(rf'<option value="{fid}"[^>]*selected', html)
    assert "SECRET-NOTE-XYZ" not in html
    assert "2020-01-01" not in html          # purchase date stays today
    assert 'name="quantity"' in html


def test_from_spool_wins_over_filament_id(auth_client, db):
    f1 = _make_filament(db)
    f2 = db.create_filament(brand="Other", material="PETG", family="PETG",
                            color_hex="#000000")
    sid = _make_source(db, f1)
    html = auth_client.get(f"/spools/new?from_spool={sid}&filament_id={f2}").get_data(as_text=True)
    assert re.search(rf'<option value="{f1}"[^>]*selected', html)
    assert not re.search(rf'<option value="{f2}"[^>]*selected', html)


def test_unknown_from_spool_is_plain_form(auth_client):
    resp = auth_client.get("/spools/new?from_spool=999999")
    assert resp.status_code == 200
    assert "Copiando dados de" not in resp.get_data(as_text=True)


def test_post_one_keeps_queue_prompt(auth_client, db):
    fid = _make_filament(db)
    resp = auth_client.post("/spools/new", data={
        "filament_id": str(fid), "nominal_weight_g": "1000", "quantity": "1"})
    assert resp.status_code == 302
    assert "queue_prompt=1" in resp.headers["Location"]


def test_post_many_redirects_with_created(auth_client, db):
    fid = _make_filament(db)
    resp = auth_client.post("/spools/new", data={
        "filament_id": str(fid), "nominal_weight_g": "1000", "quantity": "3"})
    assert resp.status_code == 302
    m = re.search(r"created=([\d%C,]+)", resp.headers["Location"])
    assert m
    ids = re.split(r",|%2C", m.group(1))
    assert len(ids) == 3


def test_buttons_for_writer(auth_client, db):
    fid = _make_filament(db)
    sid = _make_source(db, fid)
    link = f"/spools/new?from_spool={sid}"
    assert link in auth_client.get(f"/spools/{sid}").get_data(as_text=True)
    assert link in auth_client.get("/spools").get_data(as_text=True)


def test_buttons_hidden_for_viewer(viewer_client, db):
    fid = _make_filament(db)
    sid = _make_source(db, fid)
    assert "from_spool" not in viewer_client.get(f"/spools/{sid}").get_data(as_text=True)
    assert "from_spool" not in viewer_client.get("/spools").get_data(as_text=True)
