"""Lista de rolos com o toggle "Agrupar" (?group=1, guardado na sessão)."""
import re


def _mk(db, brand, n):
    fid = db.create_filament(brand, "PLA", "Basic", "#112233")
    return [db.create_spool(filament_id=fid, spool_model_id=None, custom_tare_g=200.0,
                            nominal_weight_g=1000.0, location="A1", purchase_date="",
                            purchase_price=None, notes="") for _ in range(n)], fid


def _seed(db):
    a, fid = _mk(db, "MarcaA", 4)
    db.add_weight_reading(a[3], gross_weight_g=700, tare_weight_g=200)
    b, _ = _mk(db, "MarcaB", 1)
    return a, b


def _rows(html):
    return html.count('class="spool-row')


def test_default_off_one_row_per_spool(auth_client, db):
    _seed(db)
    html = auth_client.get("/spools").get_data(as_text=True)
    assert _rows(html) == 5
    assert "sc-group-row" not in html.replace(".sc-group-row", "")
    assert "5 spools" in html or "5 rolos" in html


def test_grouped(auth_client, db):
    a, b = _seed(db)
    html = auth_client.get("/spools?group=1").get_data(as_text=True)
    assert html.count('<tr class="sc-group-row"') == 1
    assert "3×" in html
    assert html.count("data-group-child") == 3
    assert _rows(html) == 5   # 3 filhos + pesado + B
    for i in a + b:
        assert f"SP-{i:04d}" in html
    assert "5 rolos" in html or "5 spools" in html


def test_setting_persists_in_session(auth_client, db):
    _seed(db)
    auth_client.get("/spools?group=1")
    assert "sc-group-row" in auth_client.get("/spools").get_data(as_text=True)
    auth_client.get("/spools?group=0")
    assert '<tr class="sc-group-row"' not in auth_client.get("/spools").get_data(as_text=True)


def test_all_and_q_still_work_grouped(auth_client, db):
    a, b = _seed(db)
    c, _ = _mk(db, "MarcaC", 1)
    db.deactivate_spool(c[0])
    assert f"SP-{c[0]:04d}" not in auth_client.get("/spools?group=1").get_data(as_text=True)
    assert f"SP-{c[0]:04d}" in auth_client.get("/spools?group=1&all=1").get_data(as_text=True)
    html = auth_client.get("/spools?group=1&q=MarcaB").get_data(as_text=True)
    assert f"SP-{b[0]:04d}" in html
    assert f"SP-{a[0]:04d}" not in html


def test_toggle_url_preserves_params(auth_client, db):
    _seed(db)
    html = auth_client.get("/spools?group=1&all=1&q=Marca").get_data(as_text=True)
    m = re.search(r'href="([^"]*group=0[^"]*)"', html)
    assert m and "all=1" in m.group(1) and "q=Marca" in m.group(1)


def test_viewer_children_have_no_write_buttons(auth_client, viewer_client, db):
    a, _ = _seed(db)
    html = viewer_client.get("/spools?group=1").get_data(as_text=True)
    assert "data-group-child" in html
    assert f"/spools/{a[0]}/edit" not in html
    assert f"/spools/{a[0]}/deactivate" not in html
    assert "weigh-btn" not in html
