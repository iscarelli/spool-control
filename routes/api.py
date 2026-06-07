"""API máquina-a-máquina da estação de pesagem (ESP32).

Sem sessão/login, isenta de CSRF, autenticada por API key (header X-API-Key ==
env SPOOL_API_KEY). SPOOL_API_KEY ausente = 401 sempre. Ver docs/estudo_balanca_qrcode.md.
"""
import os
import secrets
from flask import request, jsonify
import database as db
from app import app, csrf


def _api_authorized():
    key = os.environ.get("SPOOL_API_KEY", "").strip()
    if not key:
        return False   # chave ausente = fechado (não open-by-default)
    return secrets.compare_digest(
        request.headers.get("X-API-Key", ""), key
    )


def _spool_summary(spool):
    return f"{spool['brand']} {spool['material']} {spool['family']}".strip()


@app.route("/api/weigh", methods=["POST"])
@csrf.exempt
def api_weigh():
    if not _api_authorized():
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


@app.route("/api/spools/<int:spool_id>", methods=["GET"])
@csrf.exempt
def api_spool(spool_id):
    """Leitura (read-only) p/ o OLED confirmar o rolo antes de gravar."""
    if not _api_authorized():
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
