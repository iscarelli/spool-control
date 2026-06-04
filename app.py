import os
import io
import re
import json
import time
import zipfile
import tempfile
import subprocess
import urllib.request
import urllib.error
from functools import wraps
from pathlib import Path
from datetime import datetime
from flask import (
    Flask, render_template, request, redirect, url_for,
    session, flash, Response, abort, jsonify,
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.middleware.proxy_fix import ProxyFix
from flask_wtf import CSRFProtect
from flask_wtf.csrf import CSRFError
import database as db
import labels as lbl
import translations as i18n
import niimbot_registry as reg

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

# Atrás do Traefik: confia em 1 proxy para X-Forwarded-For/Proto/Host.
# Necessário para que request.remote_addr seja o IP real do cliente (rate-limit
# e auditoria) e para request.is_secure refletir o HTTPS terminado no proxy.
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

# SECRET_KEY é obrigatória em produção: sem ela, cookies de sessão seriam
# assináveis por qualquer um (forja de sessão de admin). Só caímos para um
# valor de dev quando o módulo é executado diretamente (python app.py).
_secret = os.environ.get("SECRET_KEY")
if not _secret:
    if __name__ == "__main__":
        _secret = "dev-only-insecure-key"
    else:
        raise RuntimeError(
            "SECRET_KEY ausente — defina no ambiente (spool.env) antes de iniciar."
        )
app.secret_key = _secret

app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("SECURE_COOKIES", "0") == "1",
    PERMANENT_SESSION_LIFETIME=43200,
    MAX_CONTENT_LENGTH=64 * 1024 * 1024,  # 64 MB — headroom p/ restore de backup (zip: DB + logos); ainda limitado (anti-DoS)
    WTF_CSRF_TIME_LIMIT=None,             # token válido enquanto a sessão durar
)

# Proteção CSRF global em todos os POST/PUT/PATCH/DELETE.
csrf = CSRFProtect(app)

# Janela e limite do throttle de login (anti força-bruta), por IP.
LOGIN_MAX_FAILURES = 10
LOGIN_WINDOW_MIN = 15


@app.after_request
def set_security_headers(resp):
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "same-origin"
    resp.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "img-src 'self' data:; "
        "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
        "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
        "font-src 'self' https://cdn.jsdelivr.net; "
        "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    )
    if request.is_secure:
        resp.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return resp


@app.errorhandler(CSRFError)
def handle_csrf_error(e):
    if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify(error="CSRF token inválido ou ausente"), 400
    flash(t("Sessão expirada ou token inválido. Tente novamente."), "danger")
    return redirect(request.referrer or url_for("login")), 400


# ── Bootstrap ──────────────────────────────────────────────────────────────

def bootstrap():
    db.init_db()
    default_pass = os.environ.get("ADMIN_DEFAULT_PASS", "admin123")
    db.ensure_admin_user("admin", generate_password_hash(default_pass))


bootstrap()

VERSION_FILE = Path(__file__).parent / "VERSION"
APP_VERSION = VERSION_FILE.read_text().strip()

# ── Autoatualização: checagem da última release no GitHub ────────────────────
GITHUB_RELEASES_API = "https://api.github.com/repos/iscarelli/spool-control/releases/latest"
RELEASES_URL = "https://github.com/iscarelli/spool-control/releases"
# Cache em memória (por worker): evita martelar a API do GitHub (limite de 60/h
# sem token). Sucesso vale 6h; falha re-tenta em 15min. Fail-open: erro nunca
# quebra a página, apenas não mostra atualização.
_release_cache = {"tag": None, "ts": 0.0, "ok": False}
_RELEASE_TTL_OK = 6 * 3600
_RELEASE_TTL_FAIL = 15 * 60


def _version_tuple(v):
    parts = re.findall(r"\d+", v or "")
    return tuple(int(p) for p in parts) if parts else (0,)


def current_version():
    """Lê o VERSION do disco na hora — reflete um update já aplicado mesmo antes
    de o processo ser reiniciado (a constante APP_VERSION é fixada no import)."""
    try:
        return VERSION_FILE.read_text().strip()
    except Exception:
        return APP_VERSION


def check_latest_release(force=False):
    """Última tag publicada no GitHub (sem o 'v'), com cache. Devolve None se
    nunca conseguiu consultar."""
    now = time.time()
    ttl = _RELEASE_TTL_OK if _release_cache["ok"] else _RELEASE_TTL_FAIL
    if not force and _release_cache["ts"] and now - _release_cache["ts"] < ttl:
        return _release_cache["tag"]
    try:
        req = urllib.request.Request(
            GITHUB_RELEASES_API,
            headers={"User-Agent": "spool-control", "Accept": "application/vnd.github+json"},
        )
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode())
        tag = (data.get("tag_name") or "").lstrip("v").strip()
        if tag:
            _release_cache.update(tag=tag, ts=now, ok=True)
        else:
            _release_cache.update(ts=now, ok=False)
    except Exception:
        _release_cache.update(ts=now, ok=False)
    return _release_cache["tag"]


def is_update_available():
    latest = check_latest_release()
    return bool(latest) and _version_tuple(latest) > _version_tuple(current_version())

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


def t(s):
    """Traduz uma string conforme o idioma da sessão — para mensagens flash e de
    erro geradas no servidor (fora do template)."""
    return i18n.get_translator(session.get("lang", "pt"))(s)


@app.context_processor
def inject_globals():
    count = db.queue_count() if "user_id" in session else 0
    lang = session.get("lang", "pt")
    return {
        "label_queue_count": count,
        "app_version": APP_VERSION,
        "lang": lang,
        "_": i18n.get_translator(lang),
        "update_available": is_update_available() if session.get("role") == "admin" else False,
    }


# ── Formatação de data conforme o idioma ─────────────────────────────────────

def _parse_dt(value):
    if not value:
        return None
    s = str(value).strip().replace("T", " ").split(".")[0].split("+")[0].rstrip("Z").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


@app.template_filter("localdt")
def localdt(value):
    """Data + hora no formato do idioma atual (pt: dd/mm/aaaa HH:MM)."""
    dt = _parse_dt(value)
    if not dt:
        return value or ""
    fmt = "%d/%m/%Y %H:%M" if session.get("lang", "pt") == "pt" else "%m/%d/%Y %H:%M"
    return dt.strftime(fmt)


@app.template_filter("localdate")
def localdate(value):
    """Apenas a data, no formato do idioma atual (pt: dd/mm/aaaa)."""
    dt = _parse_dt(value)
    if not dt:
        return value or ""
    fmt = "%d/%m/%Y" if session.get("lang", "pt") == "pt" else "%m/%d/%Y"
    return dt.strftime(fmt)


@app.route("/lang/<code>")
def set_lang(code):
    if code in i18n.SUPPORTED:
        session["lang"] = code
    return redirect(request.referrer or url_for("dashboard"))


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
        ip = request.remote_addr or ""
        if db.count_recent_login_failures(ip, LOGIN_WINDOW_MIN) >= LOGIN_MAX_FAILURES:
            flash(
                t("Muitas tentativas. Aguarde {min} minutos e tente novamente.").format(min=LOGIN_WINDOW_MIN),
                "danger",
            )
            return render_template("login.html"), 429
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = db.get_user_by_username(username)
        if user and check_password_hash(user["password_hash"], password):
            db.clear_login_failures(ip)
            session.permanent = True
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            session["role"] = user["role"]
            db.log_login(username, ip)
            # Evita open redirect: só aceita next relativo ao próprio site.
            nxt = request.args.get("next") or ""
            if not nxt.startswith("/") or nxt.startswith("//"):
                nxt = url_for("dashboard")
            return redirect(nxt)
        db.record_login_failure(ip, username)
        flash(t("Usuário ou senha incorretos"), "danger")
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
                diameter_mm=float(request.form.get("diameter_mm") or 1.75),
                notes=request.form.get("notes", "").strip(),
            )
            flash(t("Filamento cadastrado com sucesso"), "success")
            return redirect(url_for("filaments_detail", filament_id=fid))
        except Exception as e:
            flash(f"{t('Erro')}: {e}", "danger")
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
    next_url = request.args.get("next") or request.form.get("next") or ""
    if request.method == "POST":
        try:
            db.update_filament(
                filament_id,
                brand=_resolve_brand(request.form),
                material=_resolve_material(request.form),
                family=request.form["family"].strip(),
                color_hex=request.form.get("color_hex", "").strip(),
                diameter_mm=float(request.form.get("diameter_mm") or 1.75),
                notes=request.form.get("notes", "").strip(),
            )
            flash(t("Filamento atualizado"), "success")
            return redirect(next_url or url_for("filaments_detail", filament_id=filament_id))
        except Exception as e:
            flash(f"{t('Erro')}: {e}", "danger")
    return render_template("filaments/form.html", filament=filament,
                           materials=get_ordered_materials(), brands=db.list_brands_ordered(),
                           next_url=next_url)


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
            flash(t("Modelo de carretel cadastrado"), "success")
            return redirect(url_for("spool_models_list"))
        except Exception as e:
            flash(f"{t('Erro')}: {e}", "danger")
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
            flash(t("Modelo atualizado"), "success")
            return redirect(url_for("spool_models_list"))
        except Exception as e:
            flash(f"{t('Erro')}: {e}", "danger")
    return render_template("spool_models/form.html", model=model)


@app.route("/spool-models/<int:model_id>/delete", methods=["POST"])
@login_required
def spool_models_delete(model_id):
    try:
        db.delete_spool_model(model_id)
        flash(t("Modelo removido"), "success")
    except ValueError as e:
        flash(t(str(e)), "danger")
    return redirect(url_for("spool_models_list"))


# ── Spools ─────────────────────────────────────────────────────────────────

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
            flash(t("Rolo cadastrado com sucesso"), "success")
            return redirect(url_for("spools_detail", spool_id=spool_id, queue_prompt="1"))
        except Exception as e:
            flash(f"{t('Erro')}: {e}", "danger")
    filaments = db.list_filaments()
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
        except Exception as e:
            flash(f"{t('Erro')}: {e}", "danger")
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
        except ValueError as e:
            if ajax:
                return {"ok": False, "error": str(e)}
            flash(f"{t('Valor inválido')}: {e}", "danger")
    return render_template("spools/weigh.html", spool=spool)


@app.route("/spools/<int:spool_id>/deactivate", methods=["POST"])
@login_required
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
    base_url = db.get_setting("app_base_url", "http://localhost:5000")
    w = float(db.get_setting("label_width_mm", "60"))
    h = float(db.get_setting("label_height_mm", "40"))
    pdf_bytes = lbl.generate_label_pdf(dict(spool), base_url, w, h)
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
    base_url = db.get_setting("app_base_url", "http://localhost:5000")
    size_key = request.args.get("size") or db.get_setting("niimbot_label_size", reg.DEFAULT_SIZE)
    size = reg.get_size(size_key)
    png_bytes = lbl.generate_label_png(dict(spool), base_url, size["w_px"], size["h_px"])
    return Response(png_bytes, mimetype="image/png")


@app.route("/spools/<int:spool_id>/qr.png")
@login_required
def spool_qr_png(spool_id):
    """QR isolado (PNG) apontando para a página do spool — usado no modal do
    inventário. Mesma URL codificada na etiqueta."""
    spool = db.get_spool(spool_id)
    if not spool:
        abort(404)
    base_url = db.get_setting("app_base_url", "http://localhost:5000")
    url = f"{base_url.rstrip('/')}/spools/{spool_id}"
    buf = io.BytesIO()
    lbl._make_qr_image(url).save(buf, format="PNG")
    return Response(buf.getvalue(), mimetype="image/png")


@app.route("/api/niimbot/registry")
@login_required
def niimbot_registry():
    """Modelos de impressora + tamanhos de etiqueta + seleção atual (p/ niimbot.js)."""
    return jsonify({
        "models": reg.PRINTER_MODELS,
        "sizes": reg.LABEL_SIZES,
        "selected_model": db.get_setting("niimbot_model", reg.DEFAULT_MODEL),
        "selected_size": db.get_setting("niimbot_label_size", reg.DEFAULT_SIZE),
    })


# ── Quick Weigh ────────────────────────────────────────────────────────────

@app.route("/weigh", methods=["GET", "POST"])
@login_required
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
    flash(t("Adicionado à fila de impressão"), "success")
    next_url = request.form.get("next") or url_for("spools_detail", spool_id=spool_id)
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
            pass
    flash(t("{n} rolo(s) adicionado(s) à fila de impressão").format(n=added), "success")
    return redirect(request.form.get("next") or url_for("spools_list"))


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
        flash(t("Fila vazia"), "warning")
        return redirect(url_for("label_queue"))
    base_url = db.get_setting("app_base_url", "http://localhost:5000")
    w = float(db.get_setting("label_width_mm", "60"))
    h = float(db.get_setting("label_height_mm", "40"))
    pdf_bytes = lbl.generate_multi_label_pdf([dict(s) for s in items], base_url, w, h)
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
            pass
    flash(t("{n} rolo(s) removido(s) da fila").format(n=removed), "success")
    return redirect(request.form.get("next") or url_for("spools_list"))


@app.route("/label-queue/clear", methods=["POST"])
@login_required
def label_queue_clear():
    db.queue_clear()
    flash(t("Fila limpa"), "success")
    return redirect(url_for("label_queue"))


# ── Reports ────────────────────────────────────────────────────────────────

@app.route("/reports/stats")
@login_required
def report_stats():
    return render_template("reports/stats.html", stats=db.stats_counts())


@app.route("/reports/inventory")
@login_required
def report_inventory():
    q = request.args.get("q", "").strip()
    items = db.list_inventory(q or None)
    return render_template("reports/inventory.html", items=items, q=q)


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
        flash(t("Usuário e senha são obrigatórios"), "danger")
    elif db.get_user_by_username(username):
        flash(t("Usuário já existe"), "danger")
    else:
        db.create_user(username, generate_password_hash(password), role)
        flash(t("Usuário {u} criado").format(u=username), "success")
    return redirect(url_for("admin_users"))


@app.route("/admin/users/<int:user_id>/password", methods=["POST"])
@admin_required
def admin_users_password(user_id):
    password = request.form.get("password", "")
    if not password:
        flash(t("Senha não pode ser vazia"), "danger")
    else:
        db.update_user_password(user_id, generate_password_hash(password))
        flash(t("Senha atualizada"), "success")
    return redirect(url_for("admin_users"))


@app.route("/admin/users/<int:user_id>/delete", methods=["POST"])
@admin_required
def admin_users_delete(user_id):
    if user_id == session["user_id"]:
        flash(t("Você não pode deletar seu próprio usuário"), "danger")
    else:
        db.delete_user(user_id)
        flash(t("Usuário removido"), "success")
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
        flash(t("Marca e domínio são obrigatórios"), "danger")
        return redirect(url_for("admin_brands"))
    db.update_brand_domain(brand_name, domain)
    if _fetch_brand_logo(brand_name, domain):
        flash(t("Logo de '{brand}' baixado com sucesso").format(brand=brand_name), "success")
    else:
        flash(t("Não foi possível baixar o logo via Clearbit para '{domain}'").format(domain=domain), "warning")
    return redirect(url_for("admin_brands"))


@app.route("/admin/brands/upload", methods=["POST"])
@admin_required
def admin_brand_upload():
    brand_name = request.form.get("brand_name", "").strip()
    if not brand_name or "logo" not in request.files:
        flash(t("Selecione um arquivo"), "danger")
        return redirect(url_for("admin_brands"))
    f = request.files["logo"]
    if not f.filename:
        flash(t("Arquivo inválido"), "danger")
        return redirect(url_for("admin_brands"))
    ext = Path(f.filename).suffix.lower()
    # SVG omitido de propósito: pode embutir <script> e virar XSS armazenado
    # quando servido same-origin a partir de /static/brands/.
    if ext not in ('.png', '.jpg', '.jpeg', '.webp'):
        flash(t("Formato não suportado (PNG, JPG ou WEBP)"), "danger")
        return redirect(url_for("admin_brands"))
    BRANDS_DIR.mkdir(exist_ok=True)
    slug = re.sub(r'[^a-z0-9]+', '-', brand_name.lower()).strip('-')
    logo_path = f"brands/{slug}{ext}"
    f.save(str(BRANDS_DIR / f"{slug}{ext}"))
    db.update_brand_logo_path(brand_name, logo_path)
    flash(t("Logo de '{brand}' salvo").format(brand=brand_name), "success")
    return redirect(url_for("admin_brands"))


@app.route("/admin/settings", methods=["GET", "POST"])
@admin_required
def admin_settings():
    if request.method == "POST":
        db.set_setting("app_base_url", request.form.get("app_base_url", "").strip())
        db.set_setting("low_stock_threshold_g", request.form.get("low_stock_threshold_g", "200").strip())
        db.set_setting("low_stock_pct", request.form.get("low_stock_pct", "20").strip())
        db.set_setting("label_width_mm", request.form.get("label_width_mm", "60").strip())
        db.set_setting("label_height_mm", request.form.get("label_height_mm", "40").strip())
        model = request.form.get("niimbot_model", reg.DEFAULT_MODEL).strip()
        db.set_setting("niimbot_model", model if model in reg.PRINTER_MODELS else reg.DEFAULT_MODEL)
        size = request.form.get("niimbot_label_size", reg.DEFAULT_SIZE).strip()
        db.set_setting("niimbot_label_size", size if size in reg.LABEL_SIZES else reg.DEFAULT_SIZE)
        flash(t("Configurações salvas"), "success")
        return redirect(url_for("admin_settings"))
    settings = db.get_all_settings()
    return render_template(
        "admin/settings.html", settings=settings,
        niimbot_models=reg.PRINTER_MODELS, niimbot_sizes=reg.LABEL_SIZES,
        niimbot_model=db.get_setting("niimbot_model", reg.DEFAULT_MODEL),
        niimbot_label_size=db.get_setting("niimbot_label_size", reg.DEFAULT_SIZE),
    )


# ── Atualização do sistema ───────────────────────────────────────────────────

@app.route("/admin/update")
@admin_required
def admin_update():
    latest = check_latest_release(force=True)
    cur = current_version()
    return render_template(
        "admin/update.html",
        current=cur,
        latest=latest,
        update_available=bool(latest) and _version_tuple(latest) > _version_tuple(cur),
        releases_url=RELEASES_URL,
    )


@app.route("/admin/update/run", methods=["POST"])
@admin_required
def admin_update_run():
    # Dispara o oneshot systemd como root (sudoers libera só este comando fixo,
    # sem argumentos vindos da web). --no-block retorna na hora; o update roda
    # em cgroup próprio e sobrevive ao restart do spool-control que ele aciona.
    try:
        subprocess.run(
            ["sudo", "systemctl", "start", "--no-block", "spool-update.service"],
            check=True, capture_output=True, text=True, timeout=15,
        )
    except Exception as e:
        msg = (getattr(e, "stderr", "") or str(e)).strip()
        return jsonify(ok=False, error=msg[:300]), 500
    return jsonify(ok=True)


@app.route("/admin/update/status")
@admin_required
def admin_update_status():
    latest = check_latest_release()
    cur = current_version()
    done = bool(latest) and _version_tuple(cur) >= _version_tuple(latest)
    return jsonify(current=cur, latest=latest, done=done)


# ── Backup / restauração ─────────────────────────────────────────────────────

# Extensões de logo aceitas no restore — espelha o upload de marcas; SVG fica de
# fora de propósito (pode embutir <script> e virar XSS servido same-origin).
BACKUP_LOGO_EXTS = ('.png', '.jpg', '.jpeg', '.webp')


@app.route("/admin/backup")
@admin_required
def admin_backup():
    return render_template("admin/backup.html")


@app.route("/admin/backup/download")
@admin_required
def admin_backup_download():
    # Snapshot consistente do DB para um temp e empacota com os logos num zip.
    mem = io.BytesIO()
    tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp_db.close()
    try:
        db.backup_to(tmp_db.name)
        with zipfile.ZipFile(mem, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(tmp_db.name, "spool.db")
            if BRANDS_DIR.is_dir():
                for p in sorted(BRANDS_DIR.iterdir()):
                    if p.is_file() and p.suffix.lower() in BACKUP_LOGO_EXTS:
                        z.write(p, f"brands/{p.name}")
            z.writestr("manifest.json", json.dumps({
                "app": "spool-control",
                "version": APP_VERSION,
                "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
            }, indent=2))
    finally:
        os.remove(tmp_db.name)
    mem.seek(0)
    fname = "spool-backup-" + time.strftime("%Y%m%d-%H%M%S") + ".zip"
    return Response(
        mem.read(),
        mimetype="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@app.route("/admin/backup/restore", methods=["POST"])
@admin_required
def admin_backup_restore():
    f = request.files.get("backup")
    if not f or not f.filename:
        flash(t("Selecione um arquivo de backup (.zip)"), "danger")
        return redirect(url_for("admin_backup"))
    try:
        zf = zipfile.ZipFile(io.BytesIO(f.read()))
    except Exception:
        flash(t("Arquivo inválido — não é um .zip de backup"), "danger")
        return redirect(url_for("admin_backup"))

    names = zf.namelist()
    if "spool.db" not in names:
        flash(t("Backup inválido: spool.db ausente no arquivo"), "danger")
        return redirect(url_for("admin_backup"))

    # Grava o DB do backup num temp e valida antes de tocar no banco ativo.
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    try:
        tmp.write(zf.read("spool.db"))
        tmp.close()
        if not db.is_valid_backup_db(tmp.name):
            flash(t("Backup inválido: o banco não tem a estrutura do Spool Control"), "danger")
            return redirect(url_for("admin_backup"))
        db.restore_from(tmp.name)
    finally:
        os.remove(tmp.name)

    # Restaura os logos (apenas o basename, extensões de imagem — anti zip-slip).
    BRANDS_DIR.mkdir(exist_ok=True)
    restored_logos = 0
    for name in names:
        if not name.startswith("brands/") or name.endswith("/"):
            continue
        base = os.path.basename(name)
        if not base or Path(base).suffix.lower() not in BACKUP_LOGO_EXTS:
            continue
        (BRANDS_DIR / base).write_bytes(zf.read(name))
        restored_logos += 1

    flash(t("Backup restaurado com sucesso ({n} logo(s)). Recomendado sair e entrar novamente.").format(n=restored_logos), "success")
    return redirect(url_for("admin_backup"))


# ── Health ─────────────────────────────────────────────────────────────────

@app.route("/health")
def health():
    return jsonify(status="ok")


# ── Error handlers ─────────────────────────────────────────────────────────

@app.errorhandler(403)
def err_403(e):
    return render_template("error.html", code=403, message=t("Acesso negado")), 403


@app.errorhandler(404)
def err_404(e):
    return render_template("error.html", code=404, message=t("Página não encontrada")), 404


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
