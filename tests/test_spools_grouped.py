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


# -- Botões da linha de grupo -------------------------------------------------

def _group_row(html):
    """HTML da <tr class="sc-group-row"> (até a primeira linha filha)."""
    start = html.index('<tr class="sc-group-row"')
    return html[start:html.index("data-group-child", start)]


def test_group_row_action_slots(auth_client, db):
    a = _seed(db)[0]
    ids = a[:3]
    head = _group_row(auth_client.get("/spools?group=1").get_data(as_text=True))
    # ordem: Ver, Pesar, Fila, Editar, Duplicar, Finalizar, Excluir
    assert head.count("btn btn-sm") == 7
    pos = [head.index(x) for x in ("/filaments/", "weigh-btn", "/label-queue/add-all",
                                   "bi-pencil", f"from_spool={ids[0]}",
                                   "/spools/deactivate-bulk", "bi-trash")]
    assert pos == sorted(pos)
    assert head.count(" disabled") == 3            # pesar, editar, excluir
    for i in ids:
        assert f'name="spool_ids" value="{i}"' in head
        assert f'name="ids" value="{i}"' in head
    assert f'value="{a[3]}"' not in head           # o pesado fica fora do grupo
    assert "Finalizar 3 rolos?" in head or "Finish 3 spools?" in head
    assert head.count('data-bs-toggle="tooltip"') == 7
    for txt in ("Abre a página do filamento", "Expanda o grupo e pese o rolo",
                "Adiciona os 3 rolos do grupo", "Expanda o grupo para editar",
                "Cadastra mais rolos iguais", "Finaliza os 3 rolos do grupo",
                "Expanda o grupo para excluir"):
        assert txt in head


def test_group_row_queue_remove_state(auth_client, db):
    a, _ = _seed(db)
    for i in a[:3]:
        db.queue_add(i)
    head = _group_row(auth_client.get("/spools?group=1").get_data(as_text=True))
    assert "/label-queue/remove-all" in head and "/label-queue/add-all" not in head
    assert "Remove os 3 rolos do grupo" in head
    db.queue_remove(a[0])
    head = _group_row(auth_client.get("/spools?group=1").get_data(as_text=True))
    assert "/label-queue/add-all" in head


def test_group_row_viewer_sees_only_ver_and_queue(viewer_client, db):
    _seed(db)
    head = _group_row(viewer_client.get("/spools?group=1").get_data(as_text=True))
    assert "/filaments/" in head and "/label-queue/add-all" in head
    for gone in ("weigh-btn", "bi-pencil", "bi-copy", "deactivate-bulk", "bi-trash"):
        assert gone not in head


def test_deactivate_bulk(auth_client, db):
    a, _ = _seed(db)
    r = auth_client.post("/spools/deactivate-bulk", data={"ids": [str(a[0]), str(a[1]), "99999", "x"]})
    assert r.status_code == 302
    assert not db.get_spool(a[0])["active"] and not db.get_spool(a[1])["active"]
    assert db.get_spool(a[2])["active"] and db.get_spool(a[3])["active"]
    r = auth_client.post("/spools/deactivate-bulk", data={"ids": [str(a[0])], "next": "/spools?group=1"},
                         follow_redirects=True)
    body = r.get_data(as_text=True)
    assert "0 rolos finalizados" in body or "0 spools finished" in body


def test_deactivate_bulk_requires_write(viewer_client, db):
    a, _ = _seed(db)
    r = viewer_client.post("/spools/deactivate-bulk", data={"ids": [str(a[0])]})
    assert r.status_code == 403
    assert db.get_spool(a[0])["active"]


def test_scale_icon_has_dial():
    from pathlib import Path
    svg = (Path(__file__).resolve().parent.parent / "static" / "icon-scale.svg").read_text(encoding="utf-8")
    assert '<circle cx="12" cy="14.9" r="3.9"/>' in svg
    css = (Path(__file__).resolve().parent.parent / "static" / "spool.css").read_text(encoding="utf-8")
    assert "icon-scale.svg?v=" in css   # URL fixa no CSS: o ?v= derruba o cache do SVG antigo


def test_view_is_eye_icon_with_label(auth_client, db):
    _seed(db)
    for url in ("/spools", "/spools?group=1"):
        html = auth_client.get(url).get_data(as_text=True)
        assert 'bi bi-eye' in html
        assert 'aria-label="Ver"' in html or 'aria-label="View"' in html
        assert not re.search(r'btn-outline-secondary"[^>]*>\s*(Ver|View)\s*</a>', html)


def test_grouped_qty_column_and_id_sort_value(auth_client, db):
    a, b = _seed(db)
    html = auth_client.get("/spools?group=1").get_data(as_text=True)
    assert '<th data-sort="num">Qtd</th>' in html or '<th data-sort="num">Qty</th>' in html
    assert 'data-label="Qtd" data-sort-value="3">3<' in html   # grupo de 3
    assert html.count('data-label="Qtd" data-sort-value="1">1<') == 2   # pesado + B
    # ID da linha de grupo carrega o id do primeiro rolo, não o badge
    grp = html.split('<tr class="sc-group-row"')[1]
    first_id = min(i for i in a if i != a[3])
    assert f'data-sort-value="{first_id}"' in grp.split("</tr>")[0]


def test_ungrouped_has_no_qty_column(auth_client, db):
    _seed(db)
    html = auth_client.get("/spools?group=0").get_data(as_text=True)
    assert "Qtd" not in html and ">Qty<" not in html
    assert "sc-qty-empty" not in html.replace(".sc-qty-empty", "")
