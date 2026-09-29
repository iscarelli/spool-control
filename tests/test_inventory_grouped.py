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


# ── v1.39.8: nome da cor, visao por material, ordenacao ───────────────────────
import re


def _mk(db, brand, material, hex_, name="", hex2="", family="Basic", nominal=1000.0, n=1):
    fid = db.create_filament(brand, material, family, hex_, color_name=name, color_hex2=hex2)
    return [db.create_spool(filament_id=fid, spool_model_id=None, custom_tare_g=200.0,
                            nominal_weight_g=nominal, location="L", purchase_date="",
                            purchase_price=None, notes="") for _ in range(n)]


def _tiles(html):
    """Textos de nome (marca ou material) de cada tile, na ordem da pagina."""
    return re.findall(r'sc-inv-name">([^<]*)<', html)


def test_color_name_on_spool_tiles(auth_client, db):
    _mk(db, "Elegoo", "PLA", "#112233", name="Meu Azul Noite")
    _mk(db, "Creality", "PLA", "#ff0000")  # sem nome: balde
    html = auth_client.get("/reports/inventory").get_data(as_text=True)
    assert "Meu Azul Noite" in html
    assert 'sc-inv-sub">Vermelho<' in html
    html = auth_client.get("/reports/inventory?view=grouped").get_data(as_text=True)
    assert 'sc-inv-sub">Meu Azul Noite<' in html and 'sc-inv-sub">Vermelho<' in html
    assert "Meu Azul Noite" in auth_client.get("/reports/inventory?q=Noite").get_data(as_text=True)


def test_material_view_merges_brands(auth_client, db):
    _mk(db, "Elegoo", "PETG", "#000000", n=1)
    _mk(db, "Creality", "PETG", "#0a0a0a", n=1)
    _mk(db, "Elegoo", "PETG", "#ff0000")
    _mk(db, "Elegoo", "PETG", "#000000", hex2="#00aa00")  # dual: outro grupo
    html = auth_client.get("/reports/inventory?view=material").get_data(as_text=True)
    assert html.count("sc-inv-group text-center") == 3
    assert "2×" in html
    assert "Creality, Elegoo" in html
    assert "Preto / Verde" in html
    assert "4 rolos" in html and "3 grupos" in html
    # modal lista marca + familia de cada rolo
    assert "Creality · Basic" in html


def test_material_view_q_and_translation(auth_client, db):
    _mk(db, "Elegoo", "PETG", "#000000")
    _mk(db, "Creality", "PLA", "#000000")
    html = auth_client.get("/reports/inventory?view=material&q=PETG").get_data(as_text=True)
    assert html.count("sc-inv-group text-center") == 1
    auth_client.get("/lang/en")
    html = auth_client.get("/reports/inventory?view=material").get_data(as_text=True)
    assert 'sc-inv-sub">Black<' in html


def test_sorts(auth_client, db):
    a = _mk(db, "Aaa", "ABS", "#ff0000", n=1)[0]          # remaining 1000 (unweighed)
    b = _mk(db, "Bbb", "PLA", "#000000", n=3)              # 3 spools
    c = _mk(db, "Ccc", "PLA", "#0000ff", n=1)[0]
    db.add_weight_reading(b[0], gross_weight_g=400, tare_weight_g=200)   # 200 g
    db.add_weight_reading(c, gross_weight_g=700, tare_weight_g=200)      # 500 g

    def names(qs):
        return _tiles(auth_client.get("/reports/inventory?" + qs).get_data(as_text=True))

    assert names("") == ["Aaa", "Bbb", "Bbb", "Bbb", "Ccc"]
    assert names("sort=bogus") == names("")
    assert names("view=bogus") == names("")
    assert names("sort=color") == ["Ccc", "Bbb", "Bbb", "Bbb", "Aaa"]            # Azul, Preto, Vermelho
    assert names("sort=remaining_asc") == ["Bbb", "Ccc", "Aaa", "Bbb", "Bbb"]    # 200, 500, 1000...
    assert names("sort=remaining_desc") == ["Aaa", "Bbb", "Bbb", "Ccc", "Bbb"]
    assert names("sort=newest") == ["Ccc", "Bbb", "Bbb", "Bbb", "Aaa"]
    # count_desc nao existe por rolo: cai em "name" e a opcao some do seletor
    assert names("sort=count_desc") == names("")
    assert 'value="count_desc"' not in auth_client.get("/reports/inventory").get_data(as_text=True)

    g = lambda qs: names("view=grouped&" + qs)   # Aaa 1000 g, Bbb 2200 g (3x), Ccc 500 g
    assert g("sort=name") == ["Aaa", "Bbb", "Ccc"]
    assert g("sort=count_desc")[0] == "Bbb"
    assert g("sort=remaining_asc") == ["Ccc", "Aaa", "Bbb"]
    assert g("sort=remaining_desc") == ["Bbb", "Aaa", "Ccc"]
    assert g("sort=newest") == ["Ccc", "Bbb", "Aaa"]
    assert g("sort=color") == ["Ccc", "Bbb", "Aaa"]
    assert 'value="count_desc"' in auth_client.get("/reports/inventory?view=grouped").get_data(as_text=True)

    # material: ABS vermelho 1000 g, PLA preto 2200 g, PLA azul 500 g
    def m(qs):
        h = auth_client.get("/reports/inventory?view=material&" + qs).get_data(as_text=True)
        return re.findall(r'sc-inv-sub">(Vermelho|Preto|Azul)<', h)
    assert m("sort=name") == ["Vermelho", "Preto", "Azul"]
    assert m("sort=remaining_asc") == ["Azul", "Vermelho", "Preto"]
    assert m("sort=remaining_desc") == ["Preto", "Vermelho", "Azul"]
    assert m("sort=count_desc")[0] == "Preto"
    assert m("sort=newest") == ["Azul", "Preto", "Vermelho"]
    assert m("sort=color") == ["Azul", "Preto", "Vermelho"]


# ── Resumo do estoque (rodapé) ───────────────────────────────────────────────
import re


def _summary(html):
    m = re.search(r'id="invSummary".*?</table>', html, re.S)
    assert m, "summary missing"
    return m.group(0)


def _kg_col(sm):
    return [float(x) for x in re.findall(r'data-label="kg">([\d.]+)<', sm)]


def test_sort_labels_renamed(auth_client, db):
    _seed(db)
    html = auth_client.get("/reports/inventory").get_data(as_text=True)
    assert "Ordenar: menor estoque primeiro" in html
    assert "Ordenar: maior estoque primeiro" in html
    assert "menos restante" not in html and "mais restante" not in html
    assert 'value="remaining_asc"' in html and 'value="remaining_desc"' in html


def test_summary_per_spool_by_material(auth_client, db):
    _seed(db)                                  # PLA: 500 + 250 + 1000 + 1000 (unweighed = nominal)
    _spool(db, "#00ff00", material="PETG", nominal=1000.0)
    sm = _summary(auth_client.get("/reports/inventory").get_data(as_text=True))
    assert "<strong>3.8 kg</strong>" in sm
    assert "5 rolos" in sm
    assert sm.index("PLA") < sm.index("PETG")   # kg desc
    assert _kg_col(sm) == [2.8, 1.0]


def test_summary_grouped(auth_client, db):
    _seed(db)
    sm = _summary(auth_client.get("/reports/inventory?view=grouped").get_data(as_text=True))
    assert _kg_col(sm) == [1.8, 1.0]
    assert sm.index("Preta") < sm.index("Outra")
    assert "Basic" in sm


def test_summary_material_view(auth_client, db):
    _seed(db)
    _spool(db, "#000000", brand="Terceira")
    sm = _summary(auth_client.get("/reports/inventory?view=material").get_data(as_text=True))
    assert _kg_col(sm) == [2.8, 1.0]
    assert "Preta, Terceira" in sm


def test_summary_follows_query(auth_client, db):
    _seed(db)
    html = auth_client.get("/reports/inventory?q=Outra").get_data(as_text=True)
    sm = _summary(html)
    assert _kg_col(sm) == [1.0]
    assert "1.0 kg" in html


def test_summary_absent_when_empty(auth_client, db):
    html = auth_client.get("/reports/inventory").get_data(as_text=True)
    assert 'id="invSummary"' not in html
