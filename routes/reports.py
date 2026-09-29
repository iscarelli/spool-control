"""Rotas de relatórios (estatísticas, inventário, por material/local, baixo
estoque, histórico de pesagens e histórico de consumo)."""
from flask import render_template, request
import database as db
from app import app, login_required, t


@app.route("/reports/stats")
@login_required
def report_stats():
    return render_template("reports/stats.html", stats=db.stats_counts())


INV_VIEWS = ("", "grouped", "material")
INV_SORTS = ("name", "color", "remaining_asc", "remaining_desc", "count_desc", "newest")


def _enrich_inventory(items):
    """Dicts com nome de cor (color_name ou balde do hexa, como em routes/spools.py),
    baldes das duas cores e gramas restantes (não pesado = nominal)."""
    out = []
    for r in items:
        d = dict(r)
        d["bucket"] = db.classify_color(d.get("color_hex")) or ""
        d["bucket2"] = db.classify_color(d.get("color_hex2")) or ""
        name = (d.get("color_name") or "").strip()
        d["color_label"] = name or " / ".join(t(b) for b in (d["bucket"], d["bucket2"]) if b)
        nominal = d["nominal_weight_g"] or 0
        net = d["current_net_g"]
        d["remaining_g"] = net if net is not None else nominal
        out.append(d)
    return out


@app.route("/reports/inventory")
@login_required
def report_inventory():
    q = request.args.get("q", "").strip()
    view = request.args.get("view", "")
    if view not in INV_VIEWS:
        view = ""
    sort = request.args.get("sort", "name")
    if sort not in INV_SORTS:
        sort = "name"
    items = _enrich_inventory(db.list_inventory(q or None))
    if view:
        groups = _sort_inventory(_group_inventory(items, view), sort, True)
        return render_template("reports/inventory.html", groups=groups, items=items,
                               q=q, grouped=True, view=view, sort=sort,
                               summary=_inventory_summary(items, groups, view))
    # count_desc nao faz sentido por rolo (todo rolo conta 1): cai em "name" e a
    # opcao nem aparece no seletor.
    if sort == "count_desc":
        sort = "name"
    items = _sort_inventory(items, sort, False)
    return render_template("reports/inventory.html", items=items, q=q, grouped=False,
                           view="", sort=sort,
                           summary=_inventory_summary(items, None, ""))


def _inventory_summary(items, groups, view):
    """Resumo do estoque no rodape: total (kg, rolos) + linhas por material (visao
    por rolo) ou pelos grupos da visao atual, ordenadas por kg decrescente.
    Rolo nao pesado conta como nominal (`remaining_g`)."""
    total_g = sum(s["remaining_g"] for s in items)
    if view:
        rows = [{"brand": g["brand"], "material": g["material"], "family": g["family"],
                 "color_label": g["color_label"], "brands_txt": g["brands_txt"],
                 "color_hex": g["color_hex"], "color_hex2": g["color_hex2"],
                 "translucent": g["translucent"], "count": g["count"],
                 "grams": g["remaining_g"]} for g in groups]
    else:
        by_mat = {}
        for s in items:
            r = by_mat.setdefault(s["material"], {"material": s["material"], "count": 0, "grams": 0.0})
            r["count"] += 1
            r["grams"] += s["remaining_g"]
        rows = list(by_mat.values())
    for r in rows:
        r["kg"] = r["grams"] / 1000
        r["share"] = r["grams"] / total_g * 100 if total_g > 0 else 0
    rows.sort(key=lambda r: -r["grams"])
    return {"total_kg": total_g / 1000, "total_count": len(items), "rows": rows}


def _sort_inventory(rows, sort, grouped):
    """Ordena spools (grouped=False) ou grupos (True). `rows` ja vem na ordem
    material, marca, familia, id, e sorted() e estavel — o desempate e o "name"."""
    if sort == "color":
        rows = sorted(rows, key=lambda r: ((r["bucket"] or "￿"), r["bucket2"], r["material"].lower(),
                                           r["brand"].lower()))
    elif sort == "remaining_asc":
        rows = sorted(rows, key=lambda r: r["remaining_g"])
    elif sort == "remaining_desc":
        rows = sorted(rows, key=lambda r: -r["remaining_g"])
    elif sort == "count_desc" and grouped:
        rows = sorted(rows, key=lambda r: -r["count"])
    elif sort == "newest":
        rows = sorted(rows, key=(lambda r: -r["max_id"]) if grouped else (lambda r: -r["id"]))
    return rows


def _group_inventory(items, view="grouped"):
    """Agrupa os spools ativos. view="grouped": (marca, material, familia, cor,
    translucido). view="material": junta marcas — (material, balde da cor 1, balde
    da cor 2, translucido).

    Regra do app: rolo nao pesado conta como CHEIO (= nominal). Mantem a ordem de
    `list_inventory` (material, marca, familia). Aceita Rows ou dicts de
    `_enrich_inventory`. Devolve dicts prontos p/ o template."""
    if items and "bucket" not in items[0].keys():
        items = _enrich_inventory(items)
    by_material = view == "material"
    groups = {}
    for s in items:
        tr = bool(s["translucent"])
        if by_material:
            key = (s["material"], s["bucket"], s["bucket2"], tr)
        else:
            key = (s["brand"], s["material"], s["family"], s["color_hex"], s["color_hex2"], tr)
        g = groups.get(key)
        if g is None:
            g = groups[key] = {
                "brand": s["brand"], "material": s["material"], "family": s["family"],
                "color_hex": s["color_hex"], "color_hex2": s["color_hex2"], "translucent": tr,
                "color_label": s["color_label"], "bucket": s["bucket"], "bucket2": s["bucket2"],
                "spools": [], "brands": [], "remaining_g": 0.0, "nominal_g": 0.0, "max_id": 0,
            }
        nominal = s["nominal_weight_g"] or 0
        g["remaining_g"] += s["remaining_g"]
        g["nominal_g"] += nominal
        g["spools"].append(s)
        g["max_id"] = max(g["max_id"], s["id"])
        if s["brand"] not in g["brands"]:
            g["brands"].append(s["brand"])
    out = list(groups.values())
    for g in out:
        g["count"] = len(g["spools"])
        g["pct"] = (min(round(g["remaining_g"] / g["nominal_g"] * 100, 1), 100)
                    if g["nominal_g"] > 0 else 100)
        g["locations"] = " ".join(s["location"] or "" for s in g["spools"])
        g["brands_txt"] = ", ".join(g["brands"])
        if by_material:
            g["color_label"] = " / ".join(t(b) for b in (g["bucket"], g["bucket2"]) if b)
    return out


@app.route("/reports/by-material")
@login_required
def report_by_material():
    rows = db.report_by_material()
    return render_template("reports/by_material.html", rows=rows)


@app.route("/reports/by-location")
@login_required
def report_by_location():
    rows = db.report_by_location()
    return render_template("reports/by_location.html", rows=rows)


@app.route("/reports/low-stock")
@login_required
def report_low_stock():
    threshold_g = int(db.get_setting("low_stock_threshold_g", 200))
    threshold_pct = int(db.get_setting("low_stock_pct", 20))
    rows = db.report_low_stock(threshold_g, threshold_pct)
    return render_template("reports/low_stock.html", rows=rows,
                           threshold_g=threshold_g, threshold_pct=threshold_pct)


@app.route("/reports/consumption")
@login_required
def report_consumption():
    rng = request.args.get("range", "12m")
    months = 12 if rng == "12m" else None
    return render_template("reports/consumption.html",
                           rep=db.consumption_report(months), rng=rng)


@app.route("/reports/weight-history")
@login_required
def report_weight_history():
    spool_id = request.args.get("spool_id", type=int)
    filament_id = request.args.get("filament_id", type=int)
    readings = db.list_weight_readings(spool_id=spool_id, filament_id=filament_id)
    filaments = db.list_filaments()
    spools = db.list_spools(active_only=False)
    return render_template("reports/weight_history.html",
                           readings=readings, filaments=filaments, spools=spools,
                           sel_spool_id=spool_id, sel_filament_id=filament_id)
