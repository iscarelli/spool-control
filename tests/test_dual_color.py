"""Filamentos com duas cores (v1.39.7): coluna `filaments.color_hex2`, form, render."""
import sqlite3

from conftest import ADMIN_USER, ADMIN_PASS  # noqa: F401  (fixtures logam via auth_client)


def _spool_for(db, fid):
    return db.create_spool(filament_id=fid, spool_model_id=None, custom_tare_g=200.0,
                           nominal_weight_g=1000.0, location="", purchase_date="",
                           purchase_price=None, notes="")


def _form(**over):
    d = dict(brand="Elegoo", material="PLA", family="Silk", color_hex="#000000",
             color_name="Black Green", diameter_mm="1.75", notes="")
    d.update(over)
    return d


def test_migration_adds_color_hex2_to_old_db(db):
    fid = db.create_filament("Acme", "PLA", "Basic", "#ffffff")
    with sqlite3.connect(db.DB_PATH) as con:
        con.execute("ALTER TABLE filaments DROP COLUMN color_hex2")
        con.commit()
    db.init_db()
    db.init_db()
    with sqlite3.connect(db.DB_PATH) as con:
        cols = [c[1] for c in con.execute("PRAGMA table_info(filaments)").fetchall()]
        row = con.execute("SELECT color_hex2 FROM filaments WHERE id=?", (fid,)).fetchone()
    assert cols.count("color_hex2") == 1
    assert row[0] == ""


def test_create_with_and_without_second_color(auth_client, db):
    auth_client.post("/filaments/new", data=_form(dual_color="1", color_hex2="#00ff00"))
    auth_client.post("/filaments/new", data=_form(family="Plain", color_hex2="#00ff00"))
    by_family = {f["family"]: f for f in db.list_filaments()}
    assert by_family["Silk"]["color_hex2"] == "#00ff00"
    assert by_family["Plain"]["color_hex2"] == ""      # sem o checkbox, ignora


def test_edit_sets_and_clears_second_color(auth_client, db):
    fid = db.create_filament("Acme", "PLA", "Basic", "#000000")
    base = _form(brand="Acme", family="Basic")
    auth_client.post(f"/filaments/{fid}/edit", data={**base, "dual_color": "1", "color_hex2": "#ff0000"})
    assert db.get_filament(fid)["color_hex2"] == "#ff0000"
    auth_client.post(f"/filaments/{fid}/edit", data={**base, "color_hex2": "#ff0000"})  # checkbox off
    assert db.get_filament(fid)["color_hex2"] == ""


def test_invalid_second_color_is_dropped(auth_client, db):
    payload = "#f00;background:url(https://evil.example/x)"
    auth_client.post("/filaments/new", data=_form(dual_color="1", color_hex2=payload))
    assert db.list_filaments()[0]["color_hex2"] == ""
    assert db.clean_hex2("red") == "" and db.clean_hex2("#abc") == "#abc"


def test_duplicate_copies_second_color(auth_client, db):
    fid = db.create_filament("Acme", "PLA", "Basic", "#000000", color_hex2="#00ff00")
    auth_client.post(f"/filaments/{fid}/duplicate")
    dup = [f for f in db.list_filaments() if f["id"] != fid][0]
    assert dup["color_hex2"] == "#00ff00"


def test_render_both_colors_and_unchanged_when_single(auth_client, db):
    dual = db.create_filament("Acme", "PLA", "Dual", "#111111", color_hex2="#22cc33")
    _spool_for(db, dual)
    for path in ("/filaments", "/spools", f"/filaments/{dual}"):
        html = auth_client.get(path).get_data(as_text=True)
        assert "--sw-color2:#22cc33" in html or "stop-color=\"#22cc33\"" in html, path
        assert "sc-dual-111111-22cc33" in html, path
    single = db.create_filament("Acme", "PLA", "Solo", "#444444")
    _spool_for(db, single)
    html = auth_client.get(f"/filaments/{single}").get_data(as_text=True)
    assert "sc-dual" not in html and "--sw-color2" not in html


def test_malicious_second_color_not_rendered(auth_client, db):
    with sqlite3.connect(db.DB_PATH) as con:   # simula valor sujo direto no banco
        fid = db.create_filament("Acme", "PLA", "Bad", "#111111")
        con.execute("UPDATE filaments SET color_hex2=? WHERE id=?",
                    ("#f00;background:url(https://evil.example/x)", fid))
        con.commit()
    _spool_for(db, fid)
    for path in ("/filaments", "/spools", "/reports/inventory"):
        assert "evil.example" not in auth_client.get(path).get_data(as_text=True), path


def test_grouped_inventory_separates_by_second_color(auth_client, db):
    a = db.create_filament("Acme", "PLA", "Silk", "#000000", color_hex2="#00ff00")
    b = db.create_filament("Acme", "PLA", "Silk", "#000000", color_hex2="#ff0000")
    _spool_for(db, a)
    _spool_for(db, b)
    html = auth_client.get("/reports/inventory?view=grouped").get_data(as_text=True)
    assert html.count("sc-inv-group text-center") == 2
    html = auth_client.get("/reports/inventory").get_data(as_text=True)
    assert 'data-fill2="#00ff00"' in html
