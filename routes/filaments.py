"""Rotas de filamentos (cadastro, edição, duplicação, remoção)."""
from flask import render_template, request, redirect, url_for, flash, abort, jsonify
import database as db
import filament_catalog as catalog
import logger as log_cfg
from app import app, login_required, t, _safe_next, get_ordered_materials

log = log_cfg.get_logger()


@app.route("/api/filament-catalog")
@login_required
def filament_catalog_api():
    """Catálogo de filamentos (SpoolmanDB, vendorado) para o picker do formulário."""
    return jsonify({
        "brands": catalog.BRANDS,
        "materials": catalog.MATERIALS,
        "filaments": catalog.FILAMENTS,
    })


@app.route("/filaments")
@login_required
def filaments_list():
    q = request.args.get("q", "").strip()
    filaments = db.search_filaments(q) if q else db.list_filaments()
    return render_template("filaments/list.html", filaments=filaments, q=q)


def _resolve_brand(form) -> str:
    brand = form.get("brand", "").strip()
    if brand == "__new__":
        brand = form.get("new_brand_name", "").strip()
    return brand


def _resolve_material(form) -> str:
    material = form.get("material", "").strip()
    if material == "__new__":
        material = form.get("new_material_name", "").strip()
    return material


@app.route("/filaments/new", methods=["GET", "POST"])
@login_required
def filaments_new():
    if request.method == "POST":
        try:
            fid = db.create_filament(
                brand=_resolve_brand(request.form),
                material=_resolve_material(request.form),
                family=request.form["family"].strip(),
                color_hex=request.form.get("color_hex", "").strip(),
                color_name=request.form.get("color_name", "").strip(),
                diameter_mm=float(request.form.get("diameter_mm") or 1.75),
                notes=request.form.get("notes", "").strip(),
            )
            flash(t("Filamento cadastrado com sucesso"), "success")
            return redirect(url_for("filaments_detail", filament_id=fid))
        except Exception:
            log.error("filament.create_failed", exc_info=True)
            flash(t("Erro ao processar. Tente novamente."), "danger")
    return render_template("filaments/form.html", filament=None,
                           materials=get_ordered_materials(), brands=db.list_brands_ordered(),
                           catalog_available=catalog.available())


@app.route("/filaments/<int:filament_id>")
@login_required
def filaments_detail(filament_id):
    filament = db.get_filament(filament_id)
    if not filament:
        abort(404)
    spools = db.list_spools_for_filament(filament_id)
    return render_template("filaments/detail.html", filament=filament, spools=spools)


@app.route("/filaments/<int:filament_id>/edit", methods=["GET", "POST"])
@login_required
def filaments_edit(filament_id):
    filament = db.get_filament(filament_id)
    if not filament:
        abort(404)
    next_url = _safe_next(request.args.get("next") or request.form.get("next"))
    if request.method == "POST":
        try:
            db.update_filament(
                filament_id,
                brand=_resolve_brand(request.form),
                material=_resolve_material(request.form),
                family=request.form["family"].strip(),
                color_hex=request.form.get("color_hex", "").strip(),
                color_name=request.form.get("color_name", "").strip(),
                diameter_mm=float(request.form.get("diameter_mm") or 1.75),
                notes=request.form.get("notes", "").strip(),
            )
            flash(t("Filamento atualizado"), "success")
            return redirect(next_url or url_for("filaments_detail", filament_id=filament_id))
        except Exception:
            log.error("filament.update_failed", filament_id=filament_id, exc_info=True)
            flash(t("Erro ao processar. Tente novamente."), "danger")
    return render_template("filaments/form.html", filament=filament,
                           materials=get_ordered_materials(), brands=db.list_brands_ordered(),
                           next_url=next_url, catalog_available=catalog.available())


@app.route("/filaments/<int:filament_id>/duplicate", methods=["POST"])
@login_required
def filaments_duplicate(filament_id):
    src = db.get_filament(filament_id)
    if not src:
        abort(404)
    new_id = db.create_filament(
        brand=src["brand"],
        material=src["material"],
        family=src["family"],
        color_hex=src["color_hex"],
        color_name=src["color_name"],
        diameter_mm=src["diameter_mm"],
        notes=src["notes"],
    )
    flash(t("Filamento duplicado — editando cópia"), "success")
    return redirect(url_for("filaments_edit", filament_id=new_id))


@app.route("/filaments/<int:filament_id>/delete", methods=["POST"])
@login_required
def filaments_delete(filament_id):
    try:
        db.delete_filament(filament_id)
        flash(t("Filamento removido"), "success")
        return redirect(url_for("filaments_list"))
    except ValueError as e:
        flash(t(str(e)), "danger")
        return redirect(url_for("filaments_detail", filament_id=filament_id))
