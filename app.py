import os
import re
import urllib.request
import urllib.error
from functools import wraps
from pathlib import Path
from flask import (
    Flask, render_template, request, redirect, url_for,
    session, flash, Response, abort, jsonify,
)
from werkzeug.security import generate_password_hash, check_password_hash
import database as db
import labels as lbl

BRANDS_DIR = Path(__file__).parent / "static" / "brands"


def _clean_domain(domain: str) -> str:
    domain = re.sub(r'^https?://', '', domain.strip())
    domain = re.sub(r'^www\.', '', domain)
    return domain.split('/')[0].strip()


def _fetch_brand_logo(brand_name: str, domain: str) -> bool:
    BRANDS_DIR.mkdir(exist_ok=True)
    slug = re.sub(r'[^a-z0-9]+', '-', brand_name.lower()).strip('-')
    dest = BRANDS_DIR / f"{slug}.png"
    clean = _clean_domain(domain)
    url = (
        f"https://t3.gstatic.com/faviconV2"
        f"?client=SOCIAL&type=FAVICON&fallback_opts=TYPE,SIZE,URL"
        f"&url=https://{clean}&size=256"
    )
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            ct = resp.headers.get('Content-Type', '')
            if resp.status == 200 and ('image' in ct or 'octet' in ct):
                dest.write_bytes(resp.read())
                db.update_brand_logo_path(brand_name, f"brands/{slug}.png")
                return True
    except Exception:
        pass
    return False

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-me")
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("SECURE_COOKIES", "0") == "1",
    PERMANENT_SESSION_LIFETIME=43200,
)


# ── Bootstrap ──────────────────────────────────────────────────────────────

def bootstrap():
    db.init_db()
    default_pass = os.environ.get("ADMIN_DEFAULT_PASS", "admin123")
    db.ensure_admin_user("admin", generate_password_hash(default_pass))


bootstrap()

ALL_MATERIALS = [
    "ABS", "ABS+", "ABS-CF",
    "ASA", "ASA-CF",
    "BVOH",
    "CPE", "CPE+",
    "FLEX",
    "HIPS",
    "NYLON", "NYLON-CF", "NYLON-GF",
    "PA", "PA6", "PA6-CF", "PA11", "PA11-CF", "PA12", "PA12-CF",
    "PEBA", "PEBA-CF",
    "PC", "PC-ABS", "PC-CF",
    "PEEK", "PEEK-CF",
    "PEI",
    "PETG", "PETG-CF",
    "PLA", "PLA+", "PLA-CF", "PLA-HT", "PLA-ST",
    "PMMA",
    "PP", "PP-CF", "PP-GF",
    "PPS",
    "PVA",
    "SBS",
    "SILK",
    "TPE",
    "TPU", "TPU-CF",
    "Compósito", "Outro",
]


def get_ordered_materials():
    in_use = set(db.get_materials_in_use())
    used = sorted([m for m in ALL_MATERIALS if m in in_use])
    extra = sorted([m for m in in_use if m not in set(ALL_MATERIALS)])
    unused = sorted([m for m in ALL_MATERIALS if m not in in_use])
    return used + extra + unused


def _parse_price(s):
    if not s:
        return None
    s = s.strip().replace("R$", "").strip().replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


@app.context_processor
def inject_globals():
    count = db.queue_count() if "user_id" in session else 0
    return {"label_queue_count": count}


# ── Auth decorators ────────────────────────────────────────────────────────

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return jsonify(error="Unauthorized"), 401
            return redirect(url_for("login", next=request.path))
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login", next=request.path))
        if session.get("role") != "admin":
            abort(403)
        return f(*args, **kwargs)
    return decorated


# ── Auth ───────────────────────────────────────────────────────────────────

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = db.get_user_by_username(username)
        if user and check_password_hash(user["password_hash"], password):
            session.permanent = True
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            session["role"] = user["role"]
            db.log_login(username, request.remote_addr or "")
            return redirect(request.args.get("next") or url_for("dashboard"))
        flash("Usuário ou senha incorretos", "danger")
    return render_template("login.html")


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("login"))


# ── Dashboard ──────────────────────────────────────────────────────────────

@app.route("/")
@login_required
def dashboard():
    stats = db.dashboard_stats()
    threshold_g = int(db.get_setting("low_stock_threshold_g", 200))
    threshold_pct = int(db.get_setting("low_stock_pct", 20))
    low_stock = db.report_low_stock(threshold_g, threshold_pct)
    return render_template("dashboard.html", stats=stats, low_stock=low_stock)


# ── Filaments ──────────────────────────────────────────────────────────────

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


@app.route("/filaments/new", methods=["GET", "POST"])
@login_required
def filaments_new():
    if request.method == "POST":
        try:
            fid = db.create_filament(
                brand=_resolve_brand(request.form),
                material=request.form["material"].strip(),
                family=request.form["family"].strip(),
                color_hex=request.form.get("color_hex", "").strip(),
                diameter_mm=float(request.form.get("diameter_mm") or 1.75),
                notes=request.form.get("notes", "").strip(),
            )
            flash("Filamento cadastrado com sucesso", "success")
            return redirect(url_for("filaments_detail", filament_id=fid))
        except Exception as e:
            flash(f"Erro: {e}", "danger")
    return render_template("filaments/form.html", filament=None,
                           materials=get_ordered_materials(), brands=db.list_brands_ordered())


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
    if request.method == "POST":
        try:
            db.update_filament(
                filament_id,
                brand=_resolve_brand(request.form),
                material=request.form["material"].strip(),
                family=request.form["family"].strip(),
                color_hex=request.form.get("color_hex", "").strip(),
                diameter_mm=float(request.form.get("diameter_mm") or 1.75),
                notes=request.form.get("notes", "").strip(),
            )
            flash("Filamento atualizado", "success")
            return redirect(url_for("filaments_detail", filament_id=filament_id))
        except Exception as e:
            flash(f"Erro: {e}", "danger")
    return render_template("filaments/form.html", filament=filament,
                           materials=get_ordered_materials(), brands=db.list_brands_ordered())


@app.route("/filaments/<int:filament_id>/delete", methods=["POST"])
@login_required
def filaments_delete(filament_id):
    try:
        db.delete_filament(filament_id)
        flash("Filamento removido", "success")
        return redirect(url_for("filaments_list"))
    except ValueError as e:
        flash(str(e), "danger")
        return redirect(url_for("filaments_detail", filament_id=filament_id))


# ── Spool Models ───────────────────────────────────────────────────────────

@app.route("/spool-models")
@login_required
def spool_models_list():
    models = db.list_spool_models()
    return render_template("spool_models/list.html", models=models)


@app.route("/spool-models/new", methods=["GET", "POST"])
@login_required
def spool_models_new():
    if request.method == "POST":
        try:
            db.create_spool_model(
                name=request.form["name"].strip(),
                tare_weight_g=float(request.form["tare_weight_g"]),
                notes=request.form.get("notes", "").strip(),
            )
            flash("Modelo de carretel cadastrado", "success")
            return redirect(url_for("spool_models_list"))
        except Exception as e:
            flash(f"Erro: {e}", "danger")
    return render_template("spool_models/form.html", model=None)


@app.route("/spool-models/<int:model_id>/edit", methods=["GET", "POST"])
@login_required
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
            flash("Modelo atualizado", "success")
            return redirect(url_for("spool_models_list"))
        except Exception as e:
            flash(f"Erro: {e}", "danger")
    return render_template("spool_models/form.html", model=model)


@app.route("/spool-models/<int:model_id>/delete", methods=["POST"])
@login_required
def spool_models_delete(model_id):
    try:
        db.delete_spool_model(model_id)
        flash("Modelo removido", "success")
    except ValueError as e:
        flash(str(e), "danger")
    return redirect(url_for("spool_models_list"))


# ── Spools ─────────────────────────────────────────────────────────────────

@app.route("/spools")
@login_required
def spools_list():
    active_only = request.args.get("all") != "1"
    q = request.args.get("q", "").strip()
    if q:
        spools = db.search_spools(q)
        active_only = True
    else:
        spools = db.list_spools(active_only=active_only)
    return render_template("spools/list.html", spools=spools, active_only=active_only, q=q)


@app.route("/spools/new", methods=["GET", "POST"])
@login_required
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
            flash("Spool cadastrado com sucesso", "success")
            return redirect(url_for("spools_detail", spool_id=spool_id, queue_prompt="1"))
        except Exception as e:
            flash(f"Erro: {e}", "danger")
    filaments = db.list_filaments()
    spool_models = db.list_spool_models()
    return render_template("spools/form.html", spool=None,
                           filaments=filaments, spool_models=spool_models,
                           selected_filament_id=filament_id)


@app.route("/spools/<int:spool_id>")
def spools_detail(spool_id):
    spool = db.get_spool(spool_id)
    if not spool:
        abort(404)
    readings = db.list_weight_readings(spool_id=spool_id, limit=10)
    logged_in = "user_id" in session
    in_queue = db.is_in_queue(spool_id) if logged_in else False
    queue_prompt = request.args.get("queue_prompt") == "1" and logged_in
    return render_template("spools/detail.html", spool=spool, readings=readings,
                           logged_in=logged_in, in_queue=in_queue, queue_prompt=queue_prompt)


@app.route("/spools/<int:spool_id>/edit", methods=["GET", "POST"])
@login_required
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
                spool_model_id=request.form.get("spool_model_id") or None,
                custom_tare_g=request.form.get("custom_tare_g") or None,
                nominal_weight_g=float(request.form.get("nominal_weight_g") or 1000),
                location=new_location,
                purchase_date=request.form.get("purchase_date", "").strip(),
                purchase_price=_parse_price(request.form.get("purchase_price", "")),
                notes=request.form.get("notes", "").strip(),
            )
            flash("Spool atualizado", "success")
            if old_location != new_location:
                return redirect(url_for("spools_detail", spool_id=spool_id, queue_prompt="1"))
            return redirect(url_for("spools_detail", spool_id=spool_id))
        except Exception as e:
            flash(f"Erro: {e}", "danger")
    filaments = db.list_filaments()
    spool_models = db.list_spool_models()
    return render_template("spools/form.html", spool=spool,
                           filaments=filaments, spool_models=spool_models,
                           selected_filament_id=spool["filament_id"])


@app.route("/spools/<int:spool_id>/weigh", methods=["GET", "POST"])
@login_required
def spools_weigh(spool_id):
    spool = db.get_spool(spool_id)
    if not spool:
        abort(404)
    if request.method == "POST":
        try:
            gross = float(request.form["gross_weight_g"])
            tare = float(spool["effective_tare_g"])
            if gross < tare:
                flash(f"Peso bruto ({gross}g) menor que tara ({tare}g). Verifique.", "warning")
            else:
                db.add_weight_reading(
                    spool_id=spool_id,
                    gross_weight_g=gross,
                    tare_weight_g=tare,
                    recorded_by=session.get("username", ""),
                    notes=request.form.get("notes", "").strip(),
                )
                flash(f"Peso registrado: {gross - tare:.0f}g de filamento", "success")
                return redirect(url_for("spools_detail", spool_id=spool_id))
        except ValueError as e:
            flash(f"Valor inválido: {e}", "danger")
    return render_template("spools/weigh.html", spool=spool)


@app.route("/spools/<int:spool_id>/deactivate", methods=["POST"])
@login_required
def spools_deactivate(spool_id):
    db.deactivate_spool(spool_id)
    flash("Spool marcado como finalizado", "success")
    return redirect(url_for("spools_list"))


@app.route("/spools/<int:spool_id>/label.pdf")
@login_required
def spool_label_pdf(spool_id):
    spool = db.get_spool(spool_id)
    if not spool:
        abort(404)
    base_url = db.get_setting("app_base_url", "http://localhost:5000")
    pdf_bytes = lbl.generate_label_pdf(dict(spool), dict(spool), base_url)
    return Response(
        pdf_bytes,
        mimetype="application/pdf",
        headers={"Content-Disposition": f"inline; filename=spool-{spool_id}.pdf"},
    )


# ── Quick Weigh ────────────────────────────────────────────────────────────

@app.route("/weigh", methods=["GET", "POST"])
@login_required
def quick_weigh():
    if request.method == "POST":
        code = request.form.get("spool_code", "").strip()
        m = re.search(r'\d+', code)
        if not m:
            flash("Código de spool inválido", "danger")
            return render_template("spools/weigh_quick.html")
        spool_id = int(m.group())
        spool = db.get_spool(spool_id)
        if not spool:
            flash(f"Spool SP-{spool_id:04d} não encontrado", "danger")
            return render_template("spools/weigh_quick.html")
        try:
            gross = float(request.form.get("gross_weight_g", "").replace(",", "."))
        except ValueError:
            flash("Peso bruto inválido", "danger")
            return render_template("spools/weigh_quick.html")
        tare = float(spool["effective_tare_g"])
        if gross < tare:
            flash(f"Peso bruto ({gross:.0f}g) menor que tara ({tare:.0f}g). Verifique.", "warning")
        else:
            db.add_weight_reading(spool_id, gross, tare, recorded_by=session.get("username", ""))
            net = gross - tare
            flash(f"SP-{spool_id:04d} — {net:.0f}g de filamento (bruto {gross:.0f}g − tara {tare:.0f}g)", "success")
        return redirect(url_for("quick_weigh"))
    return render_template("spools/weigh_quick.html")


# ── Search ─────────────────────────────────────────────────────────────────

@app.route("/search")
@login_required
def search():
    q = request.args.get("q", "").strip()
    spools = db.search_spools(q) if q else []
    filaments = db.search_filaments(q) if q else []
    return render_template("search.html", q=q, spools=spools, filaments=filaments)


# ── Label Queue ────────────────────────────────────────────────────────────

@app.route("/label-queue")
@login_required
def label_queue():
    items = db.queue_list()
    return render_template("reports/label_queue.html", items=items)


@app.route("/label-queue/add/<int:spool_id>", methods=["POST"])
@login_required
def label_queue_add(spool_id):
    db.queue_add(spool_id)
    flash("Adicionado à fila de impressão", "success")
    next_url = request.form.get("next") or url_for("spools_detail", spool_id=spool_id)
    return redirect(next_url)


@app.route("/label-queue/remove/<int:spool_id>", methods=["POST"])
@login_required
def label_queue_remove(spool_id):
    db.queue_remove(spool_id)
    next_url = request.form.get("next") or request.referrer or url_for("label_queue")
    return redirect(next_url)


@app.route("/label-queue/print")
@login_required
def label_queue_print():
    items = db.queue_list()
    if not items:
        flash("Fila vazia", "warning")
        return redirect(url_for("label_queue"))
    base_url = db.get_setting("app_base_url", "http://localhost:5000")
    pdf_bytes = lbl.generate_multi_label_pdf([dict(s) for s in items], base_url)
    return Response(
        pdf_bytes,
        mimetype="application/pdf",
        headers={"Content-Disposition": "inline; filename=etiquetas.pdf"},
    )


@app.route("/label-queue/clear", methods=["POST"])
@login_required
def label_queue_clear():
    db.queue_clear()
    flash("Fila limpa", "success")
    return redirect(url_for("label_queue"))


# ── Reports ────────────────────────────────────────────────────────────────

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


# ── Admin ──────────────────────────────────────────────────────────────────

@app.route("/admin/users")
@admin_required
def admin_users():
    users = db.list_users()
    return render_template("admin/users.html", users=users)


@app.route("/admin/users/new", methods=["POST"])
@admin_required
def admin_users_new():
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    role = request.form.get("role", "viewer")
    if not username or not password:
        flash("Usuário e senha são obrigatórios", "danger")
    elif db.get_user_by_username(username):
        flash("Usuário já existe", "danger")
    else:
        db.create_user(username, generate_password_hash(password), role)
        flash(f"Usuário {username} criado", "success")
    return redirect(url_for("admin_users"))


@app.route("/admin/users/<int:user_id>/password", methods=["POST"])
@admin_required
def admin_users_password(user_id):
    password = request.form.get("password", "")
    if not password:
        flash("Senha não pode ser vazia", "danger")
    else:
        db.update_user_password(user_id, generate_password_hash(password))
        flash("Senha atualizada", "success")
    return redirect(url_for("admin_users"))


@app.route("/admin/users/<int:user_id>/delete", methods=["POST"])
@admin_required
def admin_users_delete(user_id):
    if user_id == session["user_id"]:
        flash("Você não pode deletar seu próprio usuário", "danger")
    else:
        db.delete_user(user_id)
        flash("Usuário removido", "success")
    return redirect(url_for("admin_users"))


@app.route("/admin/brands")
@admin_required
def admin_brands():
    brands = db.list_brands()
    return render_template("admin/brands.html", brands=brands)


@app.route("/admin/brands/fetch", methods=["POST"])
@admin_required
def admin_brand_fetch():
    brand_name = request.form.get("brand_name", "").strip()
    domain = request.form.get("domain", "").strip()
    if not brand_name or not domain:
        flash("Marca e domínio são obrigatórios", "danger")
        return redirect(url_for("admin_brands"))
    db.update_brand_domain(brand_name, domain)
    if _fetch_brand_logo(brand_name, domain):
        flash(f"Logo de '{brand_name}' baixado com sucesso", "success")
    else:
        flash(f"Não foi possível baixar o logo via Clearbit para '{domain}'", "warning")
    return redirect(url_for("admin_brands"))


@app.route("/admin/brands/upload", methods=["POST"])
@admin_required
def admin_brand_upload():
    brand_name = request.form.get("brand_name", "").strip()
    if not brand_name or "logo" not in request.files:
        flash("Selecione um arquivo", "danger")
        return redirect(url_for("admin_brands"))
    f = request.files["logo"]
    if not f.filename:
        flash("Arquivo inválido", "danger")
        return redirect(url_for("admin_brands"))
    ext = Path(f.filename).suffix.lower()
    if ext not in ('.png', '.jpg', '.jpeg', '.svg', '.webp'):
        flash("Formato não suportado (PNG, JPG ou SVG)", "danger")
        return redirect(url_for("admin_brands"))
    BRANDS_DIR.mkdir(exist_ok=True)
    slug = re.sub(r'[^a-z0-9]+', '-', brand_name.lower()).strip('-')
    logo_path = f"brands/{slug}{ext}"
    f.save(str(BRANDS_DIR / f"{slug}{ext}"))
    db.update_brand_logo_path(brand_name, logo_path)
    flash(f"Logo de '{brand_name}' salvo", "success")
    return redirect(url_for("admin_brands"))


@app.route("/admin/settings", methods=["GET", "POST"])
@admin_required
def admin_settings():
    if request.method == "POST":
        db.set_setting("app_base_url", request.form.get("app_base_url", "").strip())
        db.set_setting("low_stock_threshold_g", request.form.get("low_stock_threshold_g", "200").strip())
        db.set_setting("low_stock_pct", request.form.get("low_stock_pct", "20").strip())
        flash("Configurações salvas", "success")
        return redirect(url_for("admin_settings"))
    settings = db.get_all_settings()
    return render_template("admin/settings.html", settings=settings)


# ── Health ─────────────────────────────────────────────────────────────────

@app.route("/health")
def health():
    return jsonify(status="ok")


# ── Error handlers ─────────────────────────────────────────────────────────

@app.errorhandler(403)
def err_403(e):
    return render_template("error.html", code=403, message="Acesso negado"), 403


@app.errorhandler(404)
def err_404(e):
    return render_template("error.html", code=404, message="Página não encontrada"), 404


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
