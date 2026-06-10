"""Admin → Integrações: gestão das chaves de API por integração (independentes).

A balança (escopo write — grava pesagem) e o Home Assistant (escopo read — só
leitura de estoque) têm chaves SEPARADAS: rotacionar uma não afeta a outra. A
balança fica PRONTA mas OCULTA por enquanto (VISIBLE_INTEGRATIONS) — seu código,
auth e seed já funcionam; só não aparece na UI ainda."""
from flask import render_template, request, redirect, url_for, flash, jsonify, abort
import database as db
import logger as log_cfg
from app import app, admin_required, demo_blocked, t, public_base_url

log = log_cfg.get_logger()

# Integrações conhecidas (todas seedadas no bootstrap). VISIBLE controla só o que
# aparece na UI — a balança fica pronta mas oculta (adicione "scale" p/ exibir).
KNOWN_INTEGRATIONS = ("homeassistant", "scale")
VISIBLE_INTEGRATIONS = ("homeassistant",)


def _ha_endpoints():
    base = public_base_url().rstrip("/")
    return [f"{base}/api/summary", f"{base}/api/low-stock", f"{base}/api/stock"]


@app.route("/admin/integrations")
@admin_required
def admin_integrations():
    rows = {r["integration"]: r for r in db.list_api_keys()}
    items = []
    for slug in VISIBLE_INTEGRATIONS:
        row = rows.get(slug)
        if not row:
            continue
        # NUNCA mande a chave inteira para o template/DOM (CWE-200): só os 4 últimos
        # dígitos mascarados. O valor em claro é buscado sob demanda via reveal_key().
        key = row["key"] or ""
        items.append({
            "slug": slug,
            "label": row["label"] or slug,
            "key_masked": ("•" * 24) + key[-4:],
            "scope": row["scope"],
            "enabled": bool(row["enabled"]),
            "created_at": row["created_at"],
            "last_used_at": row["last_used_at"],
        })
    return render_template("admin/integrations.html",
                           items=items, ha_endpoints=_ha_endpoints())


@app.route("/admin/integrations/<integration>/key")
@admin_required
def admin_integration_key(integration):
    """Revela a chave em claro SOB DEMANDA (botão "Revelar"/"Copiar"), só p/ admin e
    nunca embutida no HTML servido. Resposta no-store p/ não ficar em cache."""
    if integration not in VISIBLE_INTEGRATIONS:
        abort(404)
    row = db.get_api_key(integration)
    if not row:
        abort(404)
    resp = jsonify(key=row["key"])
    resp.headers["Cache-Control"] = "no-store"
    return resp


@app.route("/admin/integrations/<integration>/regenerate", methods=["POST"])
@admin_required
@demo_blocked
def admin_integration_regenerate(integration):
    if integration not in KNOWN_INTEGRATIONS:
        flash(t("Integração desconhecida"), "danger")
        return redirect(url_for("admin_integrations"))
    db.regenerate_api_key(integration)
    log.info("integration.key_regenerated", integration=integration)
    flash(t("Nova chave gerada. Atualize a configuração da integração."), "success")
    return redirect(url_for("admin_integrations"))


@app.route("/admin/integrations/<integration>/toggle", methods=["POST"])
@admin_required
@demo_blocked
def admin_integration_toggle(integration):
    if integration not in KNOWN_INTEGRATIONS:
        flash(t("Integração desconhecida"), "danger")
        return redirect(url_for("admin_integrations"))
    row = db.get_api_key(integration)
    if row:
        new_state = not bool(row["enabled"])
        db.set_api_key_enabled(integration, new_state)
        log.info("integration.toggled", integration=integration, enabled=new_state)
        flash(t("Integração habilitada") if new_state else t("Integração desabilitada"), "success")
    return redirect(url_for("admin_integrations"))
