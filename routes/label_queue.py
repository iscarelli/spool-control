"""Rotas da fila de impressão de etiquetas."""
from flask import render_template, request, redirect, url_for, flash, Response
import database as db
import labels as lbl
import logger as log_cfg
from app import app, login_required, t, _safe_next, public_base_url, _label_spool

log = log_cfg.get_logger()


@app.route("/label-queue")
@login_required
def label_queue():
    items = db.queue_list()
    return render_template("reports/label_queue.html", items=items)


@app.route("/label-queue/add/<int:spool_id>", methods=["POST"])
@login_required
def label_queue_add(spool_id):
    db.queue_add(spool_id)
    flash(t("Adicionado à fila de impressão"), "success")
    next_url = _safe_next(request.form.get("next"), url_for("spools_detail", spool_id=spool_id))
    return redirect(next_url)


@app.route("/label-queue/add-all", methods=["POST"])
@login_required
def label_queue_add_all():
    ids = request.form.getlist("spool_ids")
    added = 0
    for sid in ids:
        try:
            db.queue_add(int(sid))
            added += 1
        except Exception:
            log.warning("label_queue.add_failed", spool_id=sid, exc_info=True)
    flash(t("{n} rolo(s) adicionado(s) à fila de impressão").format(n=added), "success")
    return redirect(_safe_next(request.form.get("next"), url_for("spools_list")))


@app.route("/label-queue/remove/<int:spool_id>", methods=["POST"])
@login_required
def label_queue_remove(spool_id):
    db.queue_remove(spool_id)
    next_url = (_safe_next(request.form.get("next"))
                or _safe_next(request.referrer)
                or url_for("label_queue"))
    return redirect(next_url)


@app.route("/label-queue/print")
@login_required
def label_queue_print():
    items = db.queue_list()
    if not items:
        flash(t("Fila vazia"), "warning")
        return redirect(url_for("label_queue"))
    base_url = public_base_url()
    w = float(db.get_setting("label_width_mm", "60"))
    h = float(db.get_setting("label_height_mm", "40"))
    pdf_bytes = lbl.generate_multi_label_pdf([_label_spool(s) for s in items], base_url, w, h)
    return Response(
        pdf_bytes,
        mimetype="application/pdf",
        headers={"Content-Disposition": "inline; filename=etiquetas.pdf"},
    )


@app.route("/label-queue/remove-all", methods=["POST"])
@login_required
def label_queue_remove_all():
    ids = request.form.getlist("spool_ids")
    removed = 0
    for sid in ids:
        try:
            db.queue_remove(int(sid))
            removed += 1
        except Exception:
            log.warning("label_queue.remove_failed", spool_id=sid, exc_info=True)
    flash(t("{n} rolo(s) removido(s) da fila").format(n=removed), "success")
    return redirect(_safe_next(request.form.get("next"), url_for("spools_list")))


@app.route("/label-queue/clear", methods=["POST"])
@login_required
def label_queue_clear():
    db.queue_clear()
    flash(t("Fila limpa"), "success")
    return redirect(url_for("label_queue"))
