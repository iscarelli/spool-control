"""Rotas de modelos de carretel (tara padrão por modelo)."""
from flask import render_template, request, redirect, url_for, flash, abort
import database as db
import logger as log_cfg
from app import app, login_required, write_required, t

log = log_cfg.get_logger()


@app.route("/spool-models")
@login_required
def spool_models_list():
    models = db.list_spool_models()
    return render_template("spool_models/list.html", models=models)


@app.route("/spool-models/new", methods=["GET", "POST"])
@write_required
def spool_models_new():
    if request.method == "POST":
        try:
            db.create_spool_model(
                name=request.form["name"].strip(),
                tare_weight_g=float(request.form["tare_weight_g"]),
                notes=request.form.get("notes", "").strip(),
            )
            flash(t("Modelo de carretel cadastrado"), "success")
            return redirect(url_for("spool_models_list"))
        except Exception:
            log.error("spool_model.create_failed", exc_info=True)
            flash(t("Erro ao processar. Tente novamente."), "danger")
    return render_template("spool_models/form.html", model=None)


@app.route("/spool-models/<int:model_id>/edit", methods=["GET", "POST"])
@write_required
def spool_models_edit(model_id):
    model = db.get_spool_model(model_id)
    if not model:
        abort(404)
    if request.method == "POST":
        try:
            db.update_spool_model(
                model_id,
                name=request.form["name"].strip(),
                tare_weight_g=float(request.form["tare_weight_g"]),
                notes=request.form.get("notes", "").strip(),
            )
            flash(t("Modelo atualizado"), "success")
            return redirect(url_for("spool_models_list"))
        except Exception:
            log.error("spool_model.update_failed", model_id=model_id, exc_info=True)
            flash(t("Erro ao processar. Tente novamente."), "danger")
    return render_template("spool_models/form.html", model=model)


@app.route("/spool-models/<int:model_id>/delete", methods=["POST"])
@write_required
def spool_models_delete(model_id):
    try:
        db.delete_spool_model(model_id)
        flash(t("Modelo removido"), "success")
    except ValueError as e:
        flash(t(str(e)), "danger")
    return redirect(url_for("spool_models_list"))
