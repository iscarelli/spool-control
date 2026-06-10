"""Relatórios x rolo recém-cadastrado (sem pesagem).

Convenção do app: um rolo ainda não pesado é tratado como CHEIO (= nominal_weight_g).
Estes testes blindam a regressão em que os relatórios contavam o rolo novo como 0g —
caindo falsamente em "Estoque Baixo" e zerando os totais por material/local.
"""


def _make_spool(db, nominal=1000.0, tare=200.0):
    fid = db.create_filament("MarcaTeste", "PLA", "Basic", "#ff0000")
    return db.create_spool(
        filament_id=fid, spool_model_id=None, custom_tare_g=tare,
        nominal_weight_g=nominal, location="A1", purchase_date="",
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
