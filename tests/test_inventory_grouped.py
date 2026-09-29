"""Inventário agrupado (?view=grouped) e contorno do donut."""


def _spool(db, hex_="#000000", brand="Marca", material="PLA", family="Basic", nominal=1000.0, loc="A1"):
    fid = db.create_filament(brand, material, family, hex_)
    return db.create_spool(
        filament_id=fid, spool_model_id=None, custom_tare_g=200.0,
        nominal_weight_g=nominal, location=loc, purchase_date="",
        purchase_price=None, notes="",
    )


def _seed(db):
    # mesmo filamento: 3 rolos pretos (um sem pesagem) + 1 vermelho de outra marca
    fid = db.create_filament("Preta", "PLA", "Basic", "#000000")
    ids = [db.create_spool(filament_id=fid, spool_model_id=None, custom_tare_g=200.0,
                           nominal_weight_g=1000.0, location="Prateleira", purchase_date="",
                           purchase_price=None, notes="") for _ in range(3)]
    db.add_weight_reading(ids[0], gross_weight_g=700, tare_weight_g=200)   # 500 g
    db.add_weight_reading(ids[1], gross_weight_g=450, tare_weight_g=200)   # 250 g
    _spool(db, "#ff0000", brand="Outra", loc="Gaveta")
    return ids


def test_default_view_one_tile_per_spool(auth_client, db):
    _seed(db)
    html = auth_client.get("/reports/inventory").get_data(as_text=True)
    assert html.count('class="sc-inv-tile text-center"') == 4
    assert "sc-inv-group text-center" not in html
    assert "3×" not in html


def test_grouped_view(auth_client, db):
    _seed(db)
    html = auth_client.get("/reports/inventory?view=grouped").get_data(as_text=True)
    assert html.count("sc-inv-group text-center") == 2
    assert "3×" in html and "1×" in html
    # (500 + 250 + 1000) / 3000 = 58.3% ; dasharray "58.3 41.7"
    assert 'stroke-dasharray="58.3 41.7"' in html
    assert "1750 g" not in html and "1.8 kg" in html


def test_grouped_view_filters_by_q(auth_client, db):
    _seed(db)
    html = auth_client.get("/reports/inventory?view=grouped&q=Outra").get_data(as_text=True)
    assert html.count("sc-inv-group text-center") == 1
    assert "1×" in html and "3×" not in html


def test_donut_outline(auth_client, db):
    _seed(db)
    for url in ("/reports/inventory", "/reports/inventory?view=grouped"):
        html = auth_client.get(url).get_data(as_text=True)
        assert "donut-outline" in html
    assert "--sc-donut-outline" in auth_client.get("/static/spool.css").get_data(as_text=True)
