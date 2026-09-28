"""Filamentos transparentes/translúcidos (v1.39.2).

Até aqui um filamento "Clear" (#FFFFFF) era indistinguível de Branco em toda a
UI. Cobre: a migração da coluna `filaments.translucent`, persistência via
create/update/duplicate, e a marcação visual (classes CSS/atributos) nas
páginas que desenham amostra de cor — sem depender de screenshot, só de grep
no HTML pelas classes que static/spool.css estiliza.
"""
import sqlite3

from conftest import ADMIN_USER, ADMIN_PASS


def _filament(db, **over):
    kwargs = dict(brand="Acme", material="PETG", family="Clear",
                  color_hex="#ffffff", color_name="", translucent=True)
    kwargs.update(over)
    return db.create_filament(**kwargs)


def _spool_for(db, filament_id, **over):
    kwargs = dict(filament_id=filament_id, spool_model_id=None, custom_tare_g=200.0,
                  nominal_weight_g=1000.0, location="", purchase_date="",
                  purchase_price=None, notes="")
    kwargs.update(over)
    return db.create_spool(**kwargs)


# ── 1. Migração ──────────────────────────────────────────────────────────────

def test_migration_adds_translucent_to_existing_db_without_it(db):
    fid = db.create_filament("Acme", "PLA", "Basic", "#ffffff")
    with sqlite3.connect(db.DB_PATH) as con:
        con.execute("ALTER TABLE filaments DROP COLUMN translucent")
        con.commit()
        cols = [c[1] for c in con.execute("PRAGMA table_info(filaments)").fetchall()]
    assert "translucent" not in cols

    db.init_db()   # deve readicionar a coluna sem apagar a linha existente

    with sqlite3.connect(db.DB_PATH) as con:
        con.row_factory = sqlite3.Row
        cols = [c[1] for c in con.execute("PRAGMA table_info(filaments)").fetchall()]
        row = con.execute("SELECT * FROM filaments WHERE id=?", (fid,)).fetchone()
    assert cols.count("translucent") == 1
    assert row["brand"] == "Acme"
    assert row["translucent"] == 0   # default — a info antiga (perdida) não vira 1 sozinha


def test_migration_is_idempotent(db):
    db.init_db()
    db.init_db()
    with sqlite3.connect(db.DB_PATH) as con:
        cols = [c[1] for c in con.execute("PRAGMA table_info(filaments)").fetchall()]
    assert cols.count("translucent") == 1


# ── 2. CRUD ──────────────────────────────────────────────────────────────────

def test_create_filament_persists_translucent_true(db):
    fid = _filament(db, translucent=True)
    assert db.get_filament(fid)["translucent"] == 1


def test_create_filament_defaults_to_not_translucent(db):
    fid = db.create_filament("Acme", "PLA", "Basic", "#ff0000")
    assert db.get_filament(fid)["translucent"] == 0


def test_update_filament_can_toggle_translucent(db):
    fid = db.create_filament("Acme", "PLA", "Basic", "#ff0000")
    db.update_filament(fid, "Acme", "PLA", "Basic", "#ff0000", translucent=True)
    assert db.get_filament(fid)["translucent"] == 1
    db.update_filament(fid, "Acme", "PLA", "Basic", "#ff0000", translucent=False)
    assert db.get_filament(fid)["translucent"] == 0


def test_spool_queries_carry_translucent_from_filament(db):
    """`_spool_query_base` (list_spools/get_spool/queue_list/search_spools) e
    `list_inventory` precisam expor f.translucent — não só create/get_filament."""
    fid = _filament(db, translucent=True)
    sid = _spool_for(db, fid)
    assert db.get_spool(sid)["translucent"] == 1
    assert db.list_spools()[0]["translucent"] == 1
    assert db.list_inventory()[0]["translucent"] == 1


# ── 3. Rotas: form (checkbox), duplicar ─────────────────────────────────────

def test_new_filament_route_persists_checked_checkbox(auth_client, db):
    resp = auth_client.post("/filaments/new", data={
        "brand": "Acme", "material": "PETG", "family": "Clear",
        "color_hex": "#ffffff", "diameter_mm": "1.75", "translucent": "1",
    })
    assert resp.status_code == 302
    row = db.list_filaments()[0]
    assert row["translucent"] == 1


def test_new_filament_route_unchecked_checkbox_is_false(auth_client, db):
    resp = auth_client.post("/filaments/new", data={
        "brand": "Acme", "material": "PETG", "family": "Basic",
        "color_hex": "#ff0000", "diameter_mm": "1.75",
        # sem "translucent": um checkbox desmarcado não manda o campo
    })
    assert resp.status_code == 302
    row = db.list_filaments()[0]
    assert row["translucent"] == 0


def test_edit_filament_route_updates_translucent(auth_client, db):
    fid = db.create_filament("Acme", "PLA", "Basic", "#ff0000")
    resp = auth_client.post(f"/filaments/{fid}/edit", data={
        "brand": "Acme", "material": "PLA", "family": "Basic",
        "color_hex": "#ff0000", "diameter_mm": "1.75", "translucent": "1",
    })
    assert resp.status_code == 302
    assert db.get_filament(fid)["translucent"] == 1


def test_duplicate_filament_copies_translucent_flag(auth_client, db):
    fid = _filament(db, translucent=True)
    resp = auth_client.post(f"/filaments/{fid}/duplicate")
    assert resp.status_code == 302
    dup = [f for f in db.list_filaments() if f["id"] != fid][0]
    assert dup["translucent"] == 1


def test_form_page_prefills_checkbox_when_editing_translucent(auth_client, db):
    fid = _filament(db, translucent=True)
    html = auth_client.get(f"/filaments/{fid}/edit").get_data(as_text=True)
    assert 'id="translucentCheck"' in html and "checked" in html


def test_form_page_checkbox_unchecked_for_opaque(auth_client, db):
    fid = db.create_filament("Acme", "PLA", "Basic", "#ff0000")
    html = auth_client.get(f"/filaments/{fid}/edit").get_data(as_text=True)
    # o input existe mas sem o atributo checked
    import re
    m = re.search(r'<input[^>]*id="translucentCheck"[^>]*>', html)
    assert m and "checked" not in m.group(0)


# ── 4. Renderização: amostra de cor translúcida aparece só quando marcado ──

def test_filament_list_shows_translucent_indicators(auth_client, db):
    fid = _filament(db, translucent=True)
    _spool_for(db, fid)
    db.create_filament("Acme", "PLA", "Basic", "#ff0000")   # opaco, controle
    html = auth_client.get("/filaments").get_data(as_text=True)
    assert "sc-swatch-translucent" in html
    assert "donut-arc-translucent" in html


def test_filament_list_no_translucent_class_when_none_marked(auth_client, db):
    db.create_filament("Acme", "PLA", "Basic", "#ff0000")
    html = auth_client.get("/filaments").get_data(as_text=True)
    assert "sc-swatch-translucent" not in html
    assert "donut-arc-translucent" not in html


def test_filament_detail_shows_translucent_donut(auth_client, db):
    fid = _filament(db, translucent=True)
    _spool_for(db, fid)
    html = auth_client.get(f"/filaments/{fid}").get_data(as_text=True)
    assert "donut-arc-translucent" in html


def test_filament_detail_opaque_has_no_marker(auth_client, db):
    fid = db.create_filament("Acme", "PLA", "Basic", "#ff0000")
    _spool_for(db, fid)
    html = auth_client.get(f"/filaments/{fid}").get_data(as_text=True)
    assert "donut-arc-translucent" not in html


def test_spool_list_shows_translucent_indicators(auth_client, db):
    fid = _filament(db, translucent=True)
    _spool_for(db, fid)
    html = auth_client.get("/spools").get_data(as_text=True)
    assert "sc-swatch-translucent" in html
    assert "donut-arc-translucent" in html


def test_spool_detail_shows_translucent_indicators(auth_client, db):
    fid = _filament(db, translucent=True)
    sid = _spool_for(db, fid)
    html = auth_client.get(f"/spools/{sid}").get_data(as_text=True)
    assert "sc-swatch-translucent" in html
    assert "donut-arc-translucent" in html


def test_search_shows_translucent_swatch(auth_client, db):
    fid = _filament(db, translucent=True)
    _spool_for(db, fid)
    html = auth_client.get("/search?q=Acme").get_data(as_text=True)
    assert "sc-swatch-translucent" in html


def test_label_queue_shows_translucent_swatch(auth_client, db):
    fid = _filament(db, translucent=True)
    sid = _spool_for(db, fid)
    db.queue_add(sid)
    html = auth_client.get("/label-queue").get_data(as_text=True)
    assert "sc-swatch-translucent" in html


def test_inventory_report_shows_translucent_indicators(auth_client, db):
    fid = _filament(db, translucent=True)
    _spool_for(db, fid)
    html = auth_client.get("/reports/inventory").get_data(as_text=True)
    assert 'data-translucent="1"' in html
    # o marcador na CLASSE do elemento — não a string solta, que também
    # aparece sempre no JS de openInv() (classList.toggle('donut-arc-translucent', ...))
    assert 'donut-arc donut-arc-translucent"' in html


def test_inventory_report_opaque_has_translucent_zero(auth_client, db):
    fid = db.create_filament("Acme", "PLA", "Basic", "#ff0000")
    _spool_for(db, fid)
    html = auth_client.get("/reports/inventory").get_data(as_text=True)
    assert 'data-translucent="0"' in html
    assert 'donut-arc donut-arc-translucent"' not in html


# ── 5. _label_spool: marcador + supressão quando o nome já diz ──────────────

def test_label_spool_marker_added_when_translucent_and_name_silent(app_module, db):
    fid = _filament(db, translucent=True, color_name="Azul Cobalto")
    sid = _spool_for(db, fid)
    with app_module.app.test_request_context():
        d = app_module._label_spool(db.get_spool(sid))
    assert d["translucent"] is True
    assert d["translucent_marker"] == "Translúcido"


def test_label_spool_marker_suppressed_when_name_already_says_it(app_module, db):
    for name in ("Transparent Blue", "Transparente Azul", "Clear Blue",
                 "Azul Translúcido", "azul translucido"):
        fid = _filament(db, translucent=True, color_name=name)
        sid = _spool_for(db, fid)
        with app_module.app.test_request_context():
            d = app_module._label_spool(db.get_spool(sid))
        assert d["translucent_marker"] == "", name


def test_label_spool_marker_empty_when_not_translucent(app_module, db):
    fid = db.create_filament("Acme", "PLA", "Basic", "#ff0000")
    sid = _spool_for(db, fid)
    with app_module.app.test_request_context():
        d = app_module._label_spool(db.get_spool(sid))
    assert d["translucent"] is False
    assert d["translucent_marker"] == ""


def test_label_spool_marker_alone_when_no_color_name(app_module, db):
    # color_hex também vazio: com um hex presente, _label_spool cairia no
    # fallback classify_color() e o nome viraria "Branco" — não o cenário
    # "sem nome de cor" que este teste quer exercitar.
    fid = _filament(db, translucent=True, color_name="", color_hex="")
    sid = _spool_for(db, fid)
    with app_module.app.test_request_context():
        d = app_module._label_spool(db.get_spool(sid))
    assert d["color_name"] == ""
    assert d["translucent_marker"] == "Translúcido"


# ── 6. Rotas de etiqueta ponta-a-ponta (PDF/PNG não crasham) ────────────────

def test_label_pdf_route_with_translucent_filament(auth_client, db):
    fid = _filament(db, translucent=True, color_name="Azul Cobalto")
    sid = _spool_for(db, fid)
    resp = auth_client.get(f"/spools/{sid}/label.pdf")
    assert resp.status_code == 200
    assert resp.data.startswith(b"%PDF")


def test_label_png_route_with_translucent_filament_tightest_size(auth_client, db):
    fid = _filament(db, translucent=True, color_name="Azul Cobalto")
    sid = _spool_for(db, fid)
    resp = auth_client.get(f"/spools/{sid}/label.png?size=T50x30_b1")
    assert resp.status_code == 200
    assert resp.mimetype == "image/png"
