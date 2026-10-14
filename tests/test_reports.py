"""Relatórios x rolo recém-cadastrado (sem pesagem).

Convenção do app: um rolo ainda não pesado é tratado como CHEIO (= nominal_weight_g).
Estes testes blindam a regressão em que os relatórios contavam o rolo novo como 0g —
caindo falsamente em "Estoque Baixo" e zerando os totais por material/local.
"""


def _make_spool(db, nominal=1000.0, tare=200.0, location="A1"):
    fid = db.create_filament("MarcaTeste", "PLA", "Basic", "#ff0000")
    return db.create_spool(
        filament_id=fid, spool_model_id=None, custom_tare_g=tare,
        nominal_weight_g=nominal, location=location, purchase_date="",
        purchase_price=None, notes="",
    )


def test_new_spool_not_flagged_low_stock(db):
    """Rolo novo (nunca pesado, nominal 1000) não pode aparecer em Estoque Baixo."""
    sid = _make_spool(db, nominal=1000)
    low = db.report_low_stock(threshold_g=200, threshold_pct=20)
    assert sid not in [r["id"] for r in low]


def test_weighed_low_spool_is_flagged(db):
    """Controle: um rolo de fato baixo continua sendo sinalizado (com peso correto)."""
    sid = _make_spool(db, nominal=1000, tare=200)
    db.add_weight_reading(sid, gross_weight_g=300, tare_weight_g=200)  # net = 100g
    low = {r["id"]: r for r in db.report_low_stock(threshold_g=200, threshold_pct=20)}
    assert sid in low
    assert low[sid]["current_net_g"] == 100


def test_by_material_counts_nominal_for_unweighed(db):
    """Total por material soma o nominal do rolo novo (não 0)."""
    _make_spool(db, nominal=1000)
    rows = {r["material"]: r for r in db.report_by_material()}
    assert rows["PLA"]["total_net_g"] == 1000


def test_by_location_counts_nominal_for_unweighed(db):
    """Total por local soma o nominal do rolo novo (não 0)."""
    _make_spool(db, nominal=1000)
    rows = {r["location"]: r for r in db.report_by_location()}
    assert rows["A1"]["total_net_g"] == 1000


# ── Rótulo de local vazio (T-883) ───────────────────────────────────────────
#
# "(sem local)" é APRESENTAÇÃO e mora no template. A camada de dados devolve
# string vazia — inclusive para `GET /api/stock`, que é JSON e não deve carregar
# rótulo de UI em português.

def test_report_by_location_returns_empty_string_not_a_label(db):
    _make_spool(db, location="")
    assert [r["location"] for r in db.report_by_location()] == [""]


def test_empty_location_label_is_translated(auth_client, db):
    _make_spool(db, location="")

    auth_client.get("/lang/en")
    body = auth_client.get("/reports/by-location").get_data(as_text=True)

    # Âncora: prova que é o CORPO deste relatório, e não uma página de
    # redirecionamento (ex.: /account/password) que também renderiza a navbar.
    assert "Stock by Location" in body
    assert "(no location)" in body
    assert "(sem local)" not in body


def test_empty_location_label_in_spanish(auth_client, db):
    _make_spool(db, location="")

    auth_client.get("/lang/es")
    body = auth_client.get("/reports/by-location").get_data(as_text=True)

    assert "(sin ubicación)" in body
    assert "(sem local)" not in body


def test_real_location_matching_a_translation_key_is_never_translated(auth_client, db):
    """A armadilha: `{{ _(r.location) }}` traduziria um local de VERDADE chamado
    "Tudo" (chave em translations.py → "All time"). O `_()` só pode envolver o
    literal do rótulo, e só no ramo em que o valor está vazio."""
    import translations as i18n
    assert i18n._EN["Tudo"] == "All time"    # o teste só faz sentido se a chave existe

    _make_spool(db, location="Tudo")

    auth_client.get("/lang/en")
    body = auth_client.get("/reports/by-location").get_data(as_text=True)

    assert "Stock by Location" in body                                # âncora
    assert '<td class="fw-semibold sc-stack-head">Tudo</td>' in body   # dado intacto
    assert "All time" not in body


def test_empty_location_label_translated_in_en_and_es():
    import translations as i18n
    for lang, table in (("en", i18n._EN), ("es", i18n._ES)):
        assert "(sem local)" in table, f"'(sem local)' sem tradução em {lang}"
        assert table["(sem local)"], f"'(sem local)' traduzido para vazio em {lang}"


# ── Estoque Baixo por filamento × Rolos perto do fim ────────────────────────

def _spool_of(db, fid, nominal=1000, tare=200):
    return db.create_spool(
        filament_id=fid, spool_model_id=None, custom_tare_g=tare,
        nominal_weight_g=nominal, location="", purchase_date="",
        purchase_price=None, notes="",
    )


def test_near_empty_spool_beside_full_one_is_not_low_stock(db):
    fid = db.create_filament("MarcaTeste", "PETG", "Basic", "#000000")
    empty = _spool_of(db, fid)
    db.add_weight_reading(empty, gross_weight_g=250, tare_weight_g=200)  # net 50
    _spool_of(db, fid)  # never weighed = new, full (1000)
    assert fid not in [r["id"] for r in db.report_low_stock_by_filament(1000)]
    assert empty in [r["id"] for r in db.report_low_stock(200, 20)]


def test_filament_with_only_near_empty_spool_is_low_stock(db):
    fid = db.create_filament("MarcaTeste", "PETG", "Basic", "#000000")
    sid = _spool_of(db, fid)
    db.add_weight_reading(sid, gross_weight_g=250, tare_weight_g=200)
    rows = {r["id"]: r for r in db.report_low_stock_by_filament(1000)}
    assert fid in rows
    assert rows[fid]["total_net_g"] == 50
    assert rows[fid]["spool_count"] == 1


def test_unweighed_spool_counts_as_nominal_in_filament_total(db):
    fid = db.create_filament("MarcaTeste", "PLA", "Basic", "#ff0000")
    _spool_of(db, fid, nominal=800)
    assert fid in [r["id"] for r in db.report_low_stock_by_filament(1000)]
    assert fid not in [r["id"] for r in db.report_low_stock_by_filament(800)]


def test_inactive_spools_excluded_from_filament_total(db):
    fid = db.create_filament("MarcaTeste", "PLA", "Basic", "#ff0000")
    sid = _spool_of(db, fid)
    db.add_weight_reading(sid, gross_weight_g=250, tare_weight_g=200)
    full = _spool_of(db, fid)
    with db.closing(db.get_db()) as c:
        c.execute("UPDATE spools SET active=0 WHERE id=?", (full,))
        c.commit()
    rows = {r["id"]: r for r in db.report_low_stock_by_filament(1000)}
    assert rows[fid]["spool_count"] == 1
    assert rows[fid]["total_net_g"] == 50


def test_filament_with_no_active_spool_not_listed(db):
    fid = db.create_filament("MarcaTeste", "PLA", "Basic", "#ff0000")
    assert fid not in [r["id"] for r in db.report_low_stock_by_filament(1000)]


def test_low_stock_pages_render(auth_client, db):
    fid = db.create_filament("MarcaTeste", "PETG", "Basic", "#000000")
    sid = _spool_of(db, fid)
    db.add_weight_reading(sid, gross_weight_g=250, tare_weight_g=200)
    for url in ("/", "/reports/low-stock", "/reports/low-stock-filaments", "/admin/settings"):
        resp = auth_client.get(url)
        assert resp.status_code == 200, url
    dash = auth_client.get("/").data
    assert dash.count(b"Rolos perto do fim") >= 2 and b"MarcaTeste" in dash
    assert b"MarcaTeste" in auth_client.get("/reports/low-stock-filaments").data
    assert b"low_stock_filament_g" in auth_client.get("/admin/settings").data


def test_dashboard_cards_share_one_row_and_warning_text_is_dark(auth_client, db):
    fid = db.create_filament("MarcaTeste", "PETG", "Basic", "#000000")
    sid = _spool_of(db, fid)
    db.add_weight_reading(sid, gross_weight_g=250, tare_weight_g=200)
    html = auth_client.get("/").data.decode()
    assert "col-6 col-md-3" not in html
    assert html.count('class="col-6 col-md"') == 4
    assert 'class="col-12 col-md"' in html
    assert html.count("card text-center border-0 h-100 bg-warning") == 2
    css = open("static/spool.css", encoding="utf-8").read()
    assert ".card.bg-warning, .card-header.bg-warning { color: #000 !important; }" in css


def test_near_end_shows_color(auth_client, db):
    """Dashboard card and report list the spool's color name (not just material)."""
    fid = db.create_filament("Elegoo", "PETG", "Rapid", "#00ff00", color_name="Verde Limao")
    sid = db.create_spool(
        filament_id=fid, spool_model_id=None, custom_tare_g=200,
        nominal_weight_g=1000, location="A1", purchase_date="",
        purchase_price=None, notes="",
    )
    db.add_weight_reading(sid, gross_weight_g=300, tare_weight_g=200)  # net 100g
    row = next(r for r in db.report_low_stock(200, 20) if r["id"] == sid)
    assert row["color_name"] == "Verde Limao"
    html = auth_client.get("/").get_data(as_text=True)
    near = html[html.rindex("Rolos perto do fim"):]
    assert "Verde Limao" in near and "swatch" in near
    assert "Verde Limao" in auth_client.get("/reports/low-stock").get_data(as_text=True)
