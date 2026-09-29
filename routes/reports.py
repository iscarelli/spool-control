"""Rotas de relatórios (estatísticas, inventário, por material/local, baixo
estoque, histórico de pesagens e histórico de consumo)."""
from flask import render_template, request
import database as db
from app import app, login_required


@app.route("/reports/stats")
@login_required
def report_stats():
    return render_template("reports/stats.html", stats=db.stats_counts())


@app.route("/reports/inventory")
@login_required
def report_inventory():
    q = request.args.get("q", "").strip()
    items = db.list_inventory(q or None)
    if request.args.get("view") == "grouped":
        groups = _group_inventory(items)
        return render_template("reports/inventory.html", groups=groups, items=items,
                               q=q, grouped=True)
    return render_template("reports/inventory.html", items=items, q=q, grouped=False)


def _group_inventory(items):
    """Agrupa os spools ativos por (marca, material, família, cor, translúcido).

    Regra do app: rolo não pesado conta como CHEIO (= nominal). Mantém a ordem de
    `list_inventory` (material, marca, família). Devolve dicts prontos p/ o template."""
    groups = {}
    for s in items:
        key = (s["brand"], s["material"], s["family"], s["color_hex"], s["color_hex2"], bool(s["translucent"]))
        g = groups.get(key)
        if g is None:
            g = groups[key] = {
                "brand": s["brand"], "material": s["material"], "family": s["family"],
                "color_hex": s["color_hex"], "color_hex2": s["color_hex2"], "translucent": bool(s["translucent"]),
                "spools": [], "remaining_g": 0.0, "nominal_g": 0.0,
            }
        nominal = s["nominal_weight_g"] or 0
        net = s["current_net_g"]
        g["remaining_g"] += net if net is not None else nominal
        g["nominal_g"] += nominal
        g["spools"].append(s)
    out = list(groups.values())
    for g in out:
        g["count"] = len(g["spools"])
        g["pct"] = (min(round(g["remaining_g"] / g["nominal_g"] * 100, 1), 100)
                    if g["nominal_g"] > 0 else 100)
        g["locations"] = " ".join(s["location"] or "" for s in g["spools"])
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
