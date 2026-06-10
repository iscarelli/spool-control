"""Rotas de rolos (spools): cadastro/edição, pesagem, etiquetas (PDF/PNG/QR),
registro Niimbot e pesagem rápida."""
import io
import re
from flask import (
    render_template, request, redirect, url_for, session, flash, Response, abort, jsonify,
)
import database as db
import labels as lbl
import niimbot_registry as reg
import logger as log_cfg
from app import app, login_required, write_required, t, _parse_price, public_base_url, _label_spool, _currency_meta

log = log_cfg.get_logger()


def _filaments_with_color_display():
    """Enriquece a lista de filamentos com color_display para o dropdown de novo spool."""
    result = []
    for f in db.list_filaments():
        d = dict(f)
        d["color_display"] = d.get("color_name", "").strip() or (db.classify_color(d.get("color_hex")) or "")
        result.append(d)
    return result


@app.route("/spools")
@login_required
def spools_list():
    active_only = request.args.get("all") != "1"
    q = request.args.get("q", "").strip()
    color = request.args.get("color", "").strip()
    if q:
        spools = db.search_spools(q)
        active_only = True
    elif color:
        # Filtro vindo do /stats: agrupa pelo balde de cor derivado do hexa.
        spools = [s for s in db.list_spools(active_only=True)
                  if db.classify_color(s["color_hex"]) == color]
        active_only = True
    else:
        spools = db.list_spools(active_only=active_only)
    return render_template("spools/list.html", spools=spools, active_only=active_only,
                           q=q, color=color, queue_ids=db.queue_ids())


@app.route("/spools/new", methods=["GET", "POST"])
@write_required
def spools_new():
    filament_id = request.args.get("filament_id", type=int)
    if request.method == "POST":
        try:
            spool_id = db.create_spool(
                filament_id=int(request.form["filament_id"]),
                spool_model_id=request.form.get("spool_model_id") or None,
                custom_tare_g=request.form.get("custom_tare_g") or None,
                nominal_weight_g=float(request.form.get("nominal_weight_g") or 1000),
                location=request.form.get("location", "").strip(),
                purchase_date=request.form.get("purchase_date", "").strip(),
                purchase_price=_parse_price(request.form.get("purchase_price", "")),
                notes=request.form.get("notes", "").strip(),
            )
            flash(t("Rolo cadastrado com sucesso"), "success")
            return redirect(url_for("spools_detail", spool_id=spool_id, queue_prompt="1"))
        except Exception:
            log.error("spool.create_failed", exc_info=True)
            flash(t("Erro ao processar. Tente novamente."), "danger")
    filaments = _filaments_with_color_display()
    spool_models = db.list_spool_models()
    return render_template("spools/form.html", spool=None,
                           filaments=filaments, spool_models=spool_models,
                           selected_filament_id=filament_id)


@app.route("/spools/<int:spool_id>")
@login_required
def spools_detail(spool_id):
    spool = db.get_spool(spool_id)
    if not spool:
        abort(404)
    readings = db.list_weight_readings(spool_id=spool_id, limit=10)
    logged_in = True
    in_queue = db.is_in_queue(spool_id)
    queue_prompt = request.args.get("queue_prompt") == "1"
    prev_id, next_id = db.spool_neighbors(spool_id)
    return render_template("spools/detail.html", spool=spool, readings=readings,
                           logged_in=logged_in, in_queue=in_queue, queue_prompt=queue_prompt,
                           prev_id=prev_id, next_id=next_id)


@app.route("/spools/<int:spool_id>/edit", methods=["GET", "POST"])
@write_required
def spools_edit(spool_id):
    spool = db.get_spool(spool_id)
    if not spool:
        abort(404)
    if request.method == "POST":
        try:
            old_location = spool["location"]
            new_location = request.form.get("location", "").strip()
            db.update_spool(
                spool_id,
                filament_id=int(request.form["filament_id"]),
                spool_model_id=request.form.get("spool_model_id") or None,
                custom_tare_g=request.form.get("custom_tare_g") or None,
                nominal_weight_g=float(request.form.get("nominal_weight_g") or 1000),
                location=new_location,
                purchase_date=request.form.get("purchase_date", "").strip(),
                purchase_price=_parse_price(request.form.get("purchase_price", "")),
                notes=request.form.get("notes", "").strip(),
            )
            flash(t("Rolo atualizado"), "success")
            if old_location != new_location:
                return redirect(url_for("spools_detail", spool_id=spool_id, queue_prompt="1"))
            return redirect(url_for("spools_detail", spool_id=spool_id))
        except Exception:
            log.error("spool.update_failed", spool_id=spool_id, exc_info=True)
            flash(t("Erro ao processar. Tente novamente."), "danger")
    filaments = _filaments_with_color_display()
    spool_models = db.list_spool_models()
    return render_template("spools/form.html", spool=spool,
                           filaments=filaments, spool_models=spool_models,
                           selected_filament_id=spool["filament_id"])


@app.route("/spools/<int:spool_id>/weigh", methods=["GET", "POST"])
@write_required
def spools_weigh(spool_id):
    spool = db.get_spool(spool_id)
    if not spool:
        abort(404)
    if request.method == "POST":
        ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"
        try:
            gross = float(request.form["gross_weight_g"])
            tare = float(spool["effective_tare_g"])
            if gross < tare:
                msg = t("Peso bruto ({g:.0f}g) menor que tara ({t:.0f}g). Verifique.").format(g=gross, t=tare)
                if ajax:
                    return {"ok": False, "error": msg}
                flash(msg, "warning")
            else:
                db.add_weight_reading(
                    spool_id=spool_id,
                    gross_weight_g=gross,
                    tare_weight_g=tare,
                    recorded_by=session.get("username", ""),
                    notes=request.form.get("notes", "").strip(),
                )
                net = gross - tare
                if ajax:
                    nominal = float(spool["nominal_weight_g"] or 1000)
                    pct = min(100, round(net / nominal * 100, 1)) if nominal else 0
                    return {"ok": True, "net_g": round(net), "pct": pct}
                flash(t("Peso registrado: {n:.0f}g de filamento").format(n=net), "success")
                return redirect(url_for("spools_detail", spool_id=spool_id))
        except ValueError:
            log.warning("spool.weigh_invalid_input", exc_info=True)
            if ajax:
                return {"ok": False, "error": "invalid_input"}
            flash(t("Valor inválido"), "danger")
    return render_template("spools/weigh.html", spool=spool)


@app.route("/spools/<int:spool_id>/deactivate", methods=["POST"])
@write_required
def spools_deactivate(spool_id):
    db.deactivate_spool(spool_id)
    flash(t("Rolo marcado como finalizado"), "success")
    return redirect(url_for("spools_list"))


@app.route("/spools/<int:spool_id>/label.pdf")
@login_required
def spool_label_pdf(spool_id):
    spool = db.get_spool(spool_id)
    if not spool:
        abort(404)
    base_url = public_base_url()
    w = float(db.get_setting("label_width_mm", "60"))
    h = float(db.get_setting("label_height_mm", "40"))
    pdf_bytes = lbl.generate_label_pdf(_label_spool(spool), base_url, w, h)
    return Response(
        pdf_bytes,
        mimetype="application/pdf",
        headers={"Content-Disposition": f"inline; filename=spool-{spool_id}.pdf"},
    )


@app.route("/spools/<int:spool_id>/label.png")
@login_required
def spool_label_png(spool_id):
    """Bitmap 1-bit da etiqueta para impressão térmica direta (Niimbot)."""
    spool = db.get_spool(spool_id)
    if not spool:
        abort(404)
    base_url = public_base_url()
    size_key = request.args.get("size") or db.get_setting("niimbot_label_size", reg.DEFAULT_SIZE)
    size = reg.get_size(size_key)
    png_bytes = lbl.generate_label_png(_label_spool(spool), base_url, size["w_px"], size["h_px"])
    return Response(png_bytes, mimetype="image/png")


@app.route("/spools/<int:spool_id>/qr.png")
@login_required
def spool_qr_png(spool_id):
    """QR isolado (PNG) apontando para a página do spool — usado no modal do
    inventário. Mesma URL codificada na etiqueta."""
    spool = db.get_spool(spool_id)
    if not spool:
        abort(404)
    base_url = public_base_url()
    url = f"{base_url.rstrip('/')}/spools/{spool_id}"
    buf = io.BytesIO()
    lbl._make_qr_image(url).save(buf, format="PNG")
    return Response(buf.getvalue(), mimetype="image/png")


@app.route("/api/niimbot/registry")
@login_required
def niimbot_registry():
    """Modelos + tamanhos (físicos e concretos) + seleção + textos i18n (p/ niimbot.js).

    O cliente escolhe só o tamanho físico; ao imprimir, identifica a impressora e
    resolve internamente o modelo (por `id`/`task`) e a variante de pixel (mesmo
    tamanho físico, DPI da impressora). `i18n` traz as mensagens já no idioma da
    sessão — o driver vendorado é só em inglês, então a tradução mora aqui."""
    return jsonify({
        "models": reg.PRINTER_MODELS,             # modelos (p/ resolução interna)
        "families": reg.PRINTER_FAMILIES,         # famílias (item do seletor; B1+B1 Pro juntas)
        "sizes": reg.LABEL_SIZES,                 # variantes concretas (p/ resolução interna)
        "size_model": reg.SIZE_MODEL,             # variante de tamanho -> modelo dono (desambigua DPI igual)
        "physical_sizes": reg.PHYSICAL_SIZES,     # tamanhos físicos (p/ o dropdown)
        "selected_family": db.get_setting("niimbot_printer_family", reg.DEFAULT_FAMILY),
        "selected_size": db.get_setting("niimbot_label_size", reg.DEFAULT_PHYSICAL_SIZE),
        "i18n": {
            "identifying": t("identificando impressora…"),
            "printing": t("imprimindo…"),
            "printed": t("Impresso"),
            "no_printer": t("Nenhuma impressora selecionada."),
            "failed": t("Falha na impressão."),
            "unsupported": t("Use Chrome ou Edge em HTTPS para imprimir direto na Niimbot."),
            "unrecognized": t("Impressora não reconhecida ({printer}). Atualize o app ou reporte."),
        },
    })


# ── Pesagem rápida ───────────────────────────────────────────────────────────

@app.route("/weigh", methods=["GET", "POST"])
@write_required
def quick_weigh():
    if request.method == "POST":
        code = request.form.get("spool_code", "").strip()
        m = re.search(r'\d+', code)
        if not m:
            flash(t("Código de rolo inválido"), "danger")
            return render_template("spools/weigh_quick.html")
        spool_id = int(m.group())
        spool = db.get_spool(spool_id)
        if not spool:
            flash(t("Rolo SP-{code} não encontrado").format(code=f"{spool_id:04d}"), "danger")
            return render_template("spools/weigh_quick.html")
        try:
            gross = float(request.form.get("gross_weight_g", "").replace(",", "."))
        except ValueError:
            flash(t("Peso bruto inválido"), "danger")
            return render_template("spools/weigh_quick.html")
        tare = float(spool["effective_tare_g"])
        if gross < tare:
            flash(t("Peso bruto ({g:.0f}g) menor que tara ({t:.0f}g). Verifique.").format(g=gross, t=tare), "warning")
        else:
            db.add_weight_reading(spool_id, gross, tare, recorded_by=session.get("username", ""))
            net = gross - tare
            flash(t("SP-{code} — {n:.0f}g de filamento (bruto {g:.0f}g − tara {t:.0f}g)").format(
                code=f"{spool_id:04d}", n=net, g=gross, t=tare), "success")
        return redirect(url_for("quick_weigh"))
    return render_template("spools/weigh_quick.html")
