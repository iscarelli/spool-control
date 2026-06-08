"""API máquina-a-máquina.

Sem sessão/login, isenta de CSRF, autenticada por API key (header X-API-Key) com
chaves POR INTEGRAÇÃO geridas em Admin → Integrações (ver routes/integrations.py):
- balança / estação de pesagem (escopo write — grava pesagem)
- Home Assistant (escopo read — só leitura de estoque)

Rotacionar uma chave não afeta a outra. Sem chave válida = 401. Ver também
docs/estudo_balanca_qrcode.md e docs/home-assistant.md.
"""
from flask import request, jsonify
import database as db
from app import app, csrf


def _auth(need_write=False):
    """Valida o X-API-Key e registra o uso. Devolve o slug da integração ou None.
    need_write=True exige uma chave de escopo 'write' (balança)."""
    integ = db.verify_api_key(request.headers.get("X-API-Key", ""), need_write=need_write)
    if integ:
        try:
            db.touch_api_key(integ)
        except Exception:
            pass  # last_used é best-effort; nunca falha a requisição
    return integ


def _spool_summary(spool):
    return f"{spool['brand']} {spool['material']} {spool['family']}".strip()


def _thresholds():
    def _int(key, default):
        try:
            return int(db.get_setting(key, str(default)) or default)
        except (TypeError, ValueError):
            return default
    return _int("low_stock_threshold_g", 200), _int("low_stock_pct", 20)


# ── Escrita (balança / estação) ──────────────────────────────────────────────

@app.route("/api/weigh", methods=["POST"])
@csrf.exempt
def api_weigh():
    if not _auth(need_write=True):
        return jsonify(ok=False, error="API key inválida"), 401
    data = request.get_json(silent=True) or {}
    try:
        spool_id = int(data.get("spool_id"))
    except (TypeError, ValueError):
        return jsonify(ok=False, error="spool_id inválido"), 400
    try:
        gross = float(data.get("gross_weight_g"))
    except (TypeError, ValueError):
        return jsonify(ok=False, error="gross_weight_g inválido"), 400
    spool = db.get_spool(spool_id)
    if not spool:
        return jsonify(ok=False, error=f"Rolo SP-{spool_id:04d} não encontrado"), 404
    tare = float(spool["effective_tare_g"] or 0)
    if gross < tare:
        return jsonify(ok=False,
                       error=f"Peso bruto ({gross:.0f}g) menor que tara ({tare:.0f}g)"), 422
    db.add_weight_reading(spool_id, gross, tare, recorded_by="estação")
    net = gross - tare
    nominal = float(spool["nominal_weight_g"] or 0)
    pct = round(net / nominal * 100, 2) if nominal else 0
    return jsonify(
        ok=True, spool_id=spool_id, filament=_spool_summary(spool),
        gross_weight_g=round(gross, 1), tare_g=round(tare, 1),
        net_weight_g=round(net, 1), nominal_weight_g=nominal, remaining_pct=pct,
    )


# ── Leitura (balança OLED + Home Assistant) ──────────────────────────────────

@app.route("/api/spools/<int:spool_id>", methods=["GET"])
@csrf.exempt
def api_spool(spool_id):
    """Detalhe de um rolo (read-only)."""
    if not _auth():
        return jsonify(ok=False, error="API key inválida"), 401
    spool = db.get_spool(spool_id)
    if not spool:
        return jsonify(ok=False, error=f"Rolo SP-{spool_id:04d} não encontrado"), 404
    net = spool["current_net_g"]
    nominal = float(spool["nominal_weight_g"] or 0)
    pct = round((net or 0) / nominal * 100, 2) if nominal else 0
    return jsonify(
        ok=True, spool_id=spool_id, filament=_spool_summary(spool),
        tare_g=round(float(spool["effective_tare_g"] or 0), 1),
        nominal_weight_g=nominal,
        net_weight_g=round(net, 1) if net is not None else None,
        remaining_pct=pct, last_weighed_at=spool["last_weighed_at"],
    )


@app.route("/api/summary", methods=["GET"])
@csrf.exempt
def api_summary():
    """Visão geral p/ o Home Assistant: totais + estoque baixo + por material."""
    if not _auth():
        return jsonify(ok=False, error="API key inválida"), 401
    thr_g, thr_pct = _thresholds()
    by_mat = db.report_by_material()
    low = db.report_low_stock(thr_g, thr_pct)
    stats = db.dashboard_stats()
    net_g = round(sum(float(r["total_net_g"] or 0) for r in by_mat), 1)
    nominal_g = round(sum(float(r["total_nominal_g"] or 0) for r in by_mat), 1)
    return jsonify(
        ok=True,
        generated_at=db.now_iso(),
        totals={
            "active_spools": stats["total_spools"],
            "filaments": stats["total_filaments"],
            "net_weight_g": net_g,
            "net_weight_kg": round(net_g / 1000, 3),
            "nominal_weight_g": nominal_g,
        },
        low_stock={"count": len(low), "threshold_g": thr_g, "threshold_pct": thr_pct},
        by_material=[
            {"material": r["material"], "spool_count": r["spool_count"],
             "net_weight_g": round(float(r["total_net_g"] or 0), 1)}
            for r in by_mat
        ],
    )


@app.route("/api/low-stock", methods=["GET"])
@csrf.exempt
def api_low_stock():
    """Rolos abaixo do limite (o que está acabando) — p/ alertas no Home Assistant."""
    if not _auth():
        return jsonify(ok=False, error="API key inválida"), 401
    thr_g, thr_pct = _thresholds()
    low = db.report_low_stock(thr_g, thr_pct)
    return jsonify(
        ok=True, count=len(low), threshold_g=thr_g, threshold_pct=thr_pct,
        spools=[{
            "spool_id": r["id"], "code": f"SP-{r['id']:04d}",
            "brand": r["brand"], "material": r["material"], "family": r["family"],
            "color_hex": r["color_hex"], "location": r["location"],
            "net_weight_g": round(float(r["current_net_g"] or 0), 1),
            "nominal_weight_g": round(float(r["nominal_weight_g"] or 0), 1),
            "remaining_pct": r["pct_remaining"],
        } for r in low],
    )


@app.route("/api/stock", methods=["GET"])
@csrf.exempt
def api_stock():
    """Estoque agregado por material e por local (read-only)."""
    if not _auth():
        return jsonify(ok=False, error="API key inválida"), 401
    by_mat = db.report_by_material()
    by_loc = db.report_by_location()
    return jsonify(
        ok=True,
        by_material=[
            {"material": r["material"], "spool_count": r["spool_count"],
             "net_weight_g": round(float(r["total_net_g"] or 0), 1)}
            for r in by_mat
        ],
        by_location=[
            {"location": r["location"], "spool_count": r["spool_count"],
             "net_weight_g": round(float(r["total_net_g"] or 0), 1)}
            for r in by_loc
        ],
    )
