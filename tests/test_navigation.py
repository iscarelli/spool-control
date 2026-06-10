"""Navegação anterior/próximo nas telas de detalhe (spool e filamento).

Os helpers de vizinhança seguem a mesma ordem da listagem e devolvem None nas
pontas (sem wrap-around).
"""


def _make_filament(db, brand="Marca", material="PLA", family="Basic"):
    return db.create_filament(brand, material, family, "#ff0000")


def _make_spool(db, fid, nominal=1000.0):
    return db.create_spool(
        filament_id=fid, spool_model_id=None, custom_tare_g=200.0,
        nominal_weight_g=nominal, location="A1", purchase_date="",
        purchase_price=None, notes="",
    )


def test_filament_neighbors_order_and_ends(db):
    # Ordem da listagem: material, brand, family.
    a = _make_filament(db, "Aaa", "ABS", "X")   # 1º
    b = _make_filament(db, "Bbb", "PETG", "Y")  # 2º
    c = _make_filament(db, "Ccc", "PLA", "Z")   # 3º
    assert db.filament_neighbors(a) == (None, b)
    assert db.filament_neighbors(b) == (a, c)
    assert db.filament_neighbors(c) == (b, None)


def test_filament_neighbors_unknown_id(db):
    _make_filament(db)
    assert db.filament_neighbors(9999) == (None, None)


def test_spool_neighbors_order_and_ends(db):
    fa = _make_filament(db, "Aaa", "ABS", "X")
    fb = _make_filament(db, "Bbb", "PETG", "Y")
    s1 = _make_spool(db, fa)
    s2 = _make_spool(db, fb)
    assert db.spool_neighbors(s1) == (None, s2)
    assert db.spool_neighbors(s2) == (s1, None)


def test_spool_neighbors_separates_active_from_finalized(db):
    fa = _make_filament(db, "Aaa", "ABS", "X")
    fb = _make_filament(db, "Bbb", "PETG", "Y")
    active = _make_spool(db, fa)
    finalized = _make_spool(db, fb)
    db.deactivate_spool(finalized)
    # Cada um navega só dentro do próprio estado — sem vizinhos cruzados.
    assert db.spool_neighbors(active) == (None, None)
    assert db.spool_neighbors(finalized) == (None, None)
