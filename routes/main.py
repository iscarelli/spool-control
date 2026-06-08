"""Rotas gerais: dashboard, busca e health check."""
from datetime import datetime, timezone
from flask import render_template, request, jsonify
import database as db
import logger as log_cfg
from app import app, login_required, APP_VERSION, DEMO_MODE

log = log_cfg.get_logger()


# ── Dashboard ──────────────────────────────────────────────────────────────

@app.route("/")
@login_required
def dashboard():
    stats = db.dashboard_stats()
    threshold_g = int(db.get_setting("low_stock_threshold_g", 200))
    threshold_pct = int(db.get_setting("low_stock_pct", 20))
    low_stock = db.report_low_stock(threshold_g, threshold_pct)
    return render_template("dashboard.html", stats=stats, low_stock=low_stock)


# ── Search ─────────────────────────────────────────────────────────────────

@app.route("/search")
@login_required
def search():
    q = request.args.get("q", "").strip()
    spools = db.search_spools(q) if q else []
    filaments = db.search_filaments(q) if q else []
    return render_template("search.html", q=q, spools=spools, filaments=filaments)


# ── Health ─────────────────────────────────────────────────────────────────

@app.route("/health")
def health():
    checks: dict = {}

    try:
        conn = db.get_db()
        try:
            conn.execute("SELECT 1")
            checks["db"] = "ok"
        finally:
            conn.close()
    except Exception:
        checks["db"] = "error"
        log.error("health.db_failed", exc_info=True)

    # Diretório de dados = pasta do banco (independe de onde este módulo mora).
    checks["data_dir"] = "ok" if db.DB_PATH.parent.is_dir() else "missing"

    # Idade (horas) do último backup automático bem-sucedido — p/ um monitor alertar
    # se o backup parar (ex.: > 25h num backup diário). None se nunca rodou.
    backup_age_h = None
    last_run = db.get_setting("backup_last_run", "")
    if last_run:
        try:
            dt = datetime.strptime(last_run, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            backup_age_h = round((datetime.now(timezone.utc) - dt).total_seconds() / 3600, 1)
        except ValueError:
            backup_age_h = None
    ok = all(v == "ok" for v in checks.values())
    # demo_mode e backup_age_h são informativos (não afetam o status) — p/ monitores
    # externos detectarem vazamento de DEMO_MODE ou backup parado.
    return jsonify(
        status="ok" if ok else "degraded",
        version=APP_VERSION,
        demo_mode=DEMO_MODE,
        backup_age_h=backup_age_h,
        checks=checks,
    ), 200 if ok else 503
