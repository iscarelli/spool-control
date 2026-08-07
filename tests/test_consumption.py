"""Relatório de Histórico de Consumo (`/reports/consumption`).

O que estes testes protegem, além do caminho feliz:

* a data de término é **carimbada** ao finalizar e **estimada** (com marca) no backfill —
  rolo finalizado que nunca foi pesado NÃO ganha data inventada;
* consumo é a soma dos deltas entre pesagens consecutivas **do mesmo rolo**, e peso que
  sobe é descartado (troca de tara / erro de leitura), nunca vira consumo negativo.
"""
import sqlite3

import pytest


def _spool(db, brand="MarcaTeste", material="PLA", nominal=1000.0, tare=200.0):
    fid = db.create_filament(brand, material, "Basic", "#ff0000")
    return db.create_spool(
        filament_id=fid, spool_model_id=None, custom_tare_g=tare,
        nominal_weight_g=nominal, location="A1", purchase_date="",
        purchase_price=None, notes="",
    )


def _reading(db, spool_id, net_g, ts, tare=200.0):
    """Insere uma pesagem com timestamp controlado (add_weight_reading usa now_iso())."""
    with sqlite3.connect(db.DB_PATH) as con:
        con.execute(
            "INSERT INTO weight_readings (spool_id, gross_weight_g, tare_weight_g, ts) VALUES (?,?,?,?)",
            (spool_id, net_g + tare, tare, ts),
        )


def _row(db, spool_id):
    with sqlite3.connect(db.DB_PATH) as con:
        con.row_factory = sqlite3.Row
        return con.execute("SELECT * FROM spools WHERE id=?", (spool_id,)).fetchone()


def _finish_without_stamp(db, spool_id):
    """Finaliza o rolo do jeito ANTIGO (só active=0), simulando uma base pré-migração."""
    with sqlite3.connect(db.DB_PATH) as con:
        con.execute("UPDATE spools SET active=0, finished_at='', finished_at_estimated=0 WHERE id=?",
                    (spool_id,))


# ── 1. Migração ─────────────────────────────────────────────────────────────

def test_init_db_is_idempotent(db):
    """Rodar o init do schema de novo não quebra nem duplica as colunas novas."""
    db.init_db()
    db.init_db()
    with sqlite3.connect(db.DB_PATH) as con:
        cols = [c[1] for c in con.execute("PRAGMA table_info(spools)").fetchall()]
    assert cols.count("finished_at") == 1
    assert cols.count("finished_at_estimated") == 1


# ── 2. Backfill ─────────────────────────────────────────────────────────────

def test_backfill_uses_last_reading_and_marks_estimated(db):
    sid = _spool(db)
    _reading(db, sid, 800, "2026-03-10T12:00:00Z")
    _reading(db, sid, 400, "2026-05-20T09:30:00Z")   # a mais recente
    _finish_without_stamp(db, sid)

    db.init_db()                                     # dispara o backfill
    row = _row(db, sid)
    assert row["finished_at"] == "2026-05-20T09:30:00Z"
    assert row["finished_at_estimated"] == 1


def test_backfill_is_idempotent(db):
    sid = _spool(db)
    _reading(db, sid, 800, "2026-03-10T12:00:00Z")
    _finish_without_stamp(db, sid)

    db.init_db()
    first = dict(_row(db, sid))
    _reading(db, sid, 500, "2026-06-01T00:00:00Z")   # pesagem nova, posterior
    db.init_db()                                      # 2ª passada não pode remexer
    assert dict(_row(db, sid)) == first


# ── 3. Finalizado sem nenhuma pesagem ───────────────────────────────────────

def test_finished_without_readings_gets_no_invented_date(db):
    sid = _spool(db)
    _finish_without_stamp(db, sid)
    db.init_db()

    assert _row(db, sid)["finished_at"] == ""
    rep = db.consumption_report()
    assert rep["no_date_count"] == 1
    assert all(m["month"] for m in rep["by_month"])   # nenhum mês vazio/inventado


# ── 4. Carimbo real ─────────────────────────────────────────────────────────

def test_deactivate_spool_stamps_measured_date(db):
    sid = _spool(db)
    db.deactivate_spool(sid)
    row = _row(db, sid)
    assert row["active"] == 0
    assert row["finished_at"] != ""
    assert row["finished_at_estimated"] == 0


# ── 5. Matemática do consumo ────────────────────────────────────────────────

def test_consumption_sums_positive_deltas(db):
    sid = _spool(db)
    for net, ts in ((1000, "2026-06-01T00:00:00Z"),
                    (800,  "2026-06-10T00:00:00Z"),
                    (600,  "2026-06-20T00:00:00Z")):
        _reading(db, sid, net, ts)
    assert db.consumption_report()["total_grams"] == 400


def test_negative_delta_is_discarded_not_subtracted(db):
    """1000→800→900→700: o +100 não vira −100 nem entra como consumo. Total = 400."""
    sid = _spool(db)
    for net, ts in ((1000, "2026-06-01T00:00:00Z"),
                    (800,  "2026-06-05T00:00:00Z"),
                    (900,  "2026-06-10T00:00:00Z"),   # peso SOBE (troca de tara/erro)
                    (700,  "2026-06-15T00:00:00Z")):
        _reading(db, sid, net, ts)
    assert db.consumption_report()["total_grams"] == 400


# ── 6. Agrupamento por mês ──────────────────────────────────────────────────

def test_grams_are_grouped_by_month_of_the_later_reading(db):
    sid = _spool(db)
    for net, ts in ((1000, "2026-05-28T00:00:00Z"),
                    (900,  "2026-05-30T00:00:00Z"),   # −100 em maio
                    (600,  "2026-06-02T00:00:00Z")):  # −300 já em junho
        _reading(db, sid, net, ts)
    by_month = {m["month"]: m["grams"] for m in db.consumption_report()["by_month"]}
    assert by_month == {"2026-05": 100, "2026-06": 300}


def test_by_month_is_sorted_newest_first(db):
    sid = _spool(db)
    for net, ts in ((1000, "2026-04-01T00:00:00Z"),
                    (900,  "2026-05-01T00:00:00Z"),
                    (800,  "2026-06-01T00:00:00Z")):
        _reading(db, sid, net, ts)
    months = [m["month"] for m in db.consumption_report()["by_month"]]
    assert months == sorted(months, reverse=True)


# ── 7. Isolamento entre rolos ───────────────────────────────────────────────

def test_readings_of_different_spools_never_pair(db):
    """O rolo B começa mais leve que o A; a fronteira entre eles não pode virar consumo."""
    a = _spool(db, brand="MarcaA")
    b = _spool(db, brand="MarcaB")
    _reading(db, a, 1000, "2026-06-01T00:00:00Z")
    _reading(db, a, 900,  "2026-06-02T00:00:00Z")     # A consumiu 100
    _reading(db, b, 500,  "2026-06-03T00:00:00Z")     # 1ª leitura de B: só ancora
    _reading(db, b, 450,  "2026-06-04T00:00:00Z")     # B consumiu 50

    rep = db.consumption_report()
    assert rep["total_grams"] == 150                  # e não 150 + 400 da "fronteira"
    by_brand = {r["name"]: r["grams"] for r in rep["by_brand"]}
    assert by_brand == {"MarcaA": 100, "MarcaB": 50}


def test_breakdowns_group_by_material_and_brand(db):
    a = _spool(db, brand="MarcaA", material="PLA")
    b = _spool(db, brand="MarcaB", material="PETG")
    _reading(db, a, 1000, "2026-06-01T00:00:00Z")
    _reading(db, a, 700,  "2026-06-02T00:00:00Z")
    _reading(db, b, 1000, "2026-06-01T00:00:00Z")
    _reading(db, b, 900,  "2026-06-02T00:00:00Z")
    db.deactivate_spool(b)

    rep = db.consumption_report(months=None)
    by_material = {r["name"]: r for r in rep["by_material"]}
    assert by_material["PLA"]["grams"] == 300
    assert by_material["PETG"]["grams"] == 100
    assert by_material["PETG"]["spools_finished"] == 1
    assert by_material["PLA"]["spools_finished"] == 0
    assert rep["total_spools_finished"] == 1


def test_range_all_covers_months_outside_the_12m_window(db):
    """Uma leitura antiga só aparece em `months=None`; a janela de 12 meses a corta."""
    sid = _spool(db)
    _reading(db, sid, 1000, "2019-01-01T00:00:00Z")
    _reading(db, sid, 600,  "2019-02-01T00:00:00Z")
    assert db.consumption_report(months=12)["total_grams"] == 0
    assert db.consumption_report(months=None)["total_grams"] == 400


def test_empty_database_reports_zeros(db):
    """Relatório que quebra com zero linhas é bug comum — aqui ele tem que responder."""
    rep = db.consumption_report()
    assert rep["by_month"] == []
    assert rep["total_grams"] == 0
    assert rep["total_spools_finished"] == 0
    assert rep["no_date_count"] == 0
    assert rep["period_start"] == "" and rep["period_end"] == ""


# ── 8. Rota ─────────────────────────────────────────────────────────────────

def test_route_requires_login(client):
    r = client.get("/reports/consumption")
    assert r.status_code in (302, 401)
    if r.status_code == 302:
        assert "/login" in r.headers["Location"]


def test_route_renders_empty_and_with_data(auth_client, db):
    assert auth_client.get("/reports/consumption").status_code == 200   # banco vazio

    sid = _spool(db)
    _reading(db, sid, 1000, "2026-06-01T00:00:00Z")
    _reading(db, sid, 750,  "2026-06-10T00:00:00Z")
    db.deactivate_spool(sid)

    r = auth_client.get("/reports/consumption")
    assert r.status_code == 200
    assert "Histórico de Consumo" in r.get_data(as_text=True)


def test_route_accepts_range_all(auth_client):
    assert auth_client.get("/reports/consumption?range=all").status_code == 200


def test_nav_links_to_the_report(auth_client):
    assert "/reports/consumption" in auth_client.get("/reports/stats").get_data(as_text=True)


# ── 9. Paridade de i18n ─────────────────────────────────────────────────────

NEW_KEYS = [
    "Histórico de Consumo", "Rolos gastos", "Filamento consumido", "Período coberto",
    "Período", "Últimos 12 meses", "Tudo", "Por mês", "Mês", "Rolos finalizados",
    "Consumido (kg)", "{n} com data estimada a partir da última pesagem", "Sem data",
    "Finalizados sem nenhuma pesagem — não há como situá-los num mês.",
    "Por material", "Por marca",
]


@pytest.mark.parametrize("key", NEW_KEYS)
def test_new_strings_translated_in_en_and_es(key):
    import translations as i18n
    for lang, table in (("en", i18n._EN), ("es", i18n._ES)):
        assert key in table, f"{key!r} sem tradução em {lang}"
        assert table[key], f"{key!r} traduzido para string vazia em {lang}"


def test_en_es_key_parity_is_preserved():
    """A regra do projeto: _ES tem a mesma quantidade de chaves que _EN."""
    import translations as i18n
    assert [k for k in i18n._EN if k not in i18n._ES] == []
