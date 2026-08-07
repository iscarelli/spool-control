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
