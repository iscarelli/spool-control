"""Rotas administrativas (só admin): usuários, marcas, configurações, atualização
do sistema e backup/restauração."""
import re
import time
from pathlib import Path
from flask import (
    render_template, request, redirect, url_for, session, flash, jsonify, Response,
)
from werkzeug.security import generate_password_hash
import database as db
import backup
import niimbot_registry as reg
import logger as log_cfg
from app import (
    app, admin_required, demo_blocked, t, MIN_PASSWORD_LEN, DEMO_MODE,
    BRANDS_DIR, _fetch_brand_logo, _clean_domain, public_base_url,
    RELEASES_URL, check_latest_release, current_version, _version_tuple,
    latest_release_notes, render_release_notes,
)

log = log_cfg.get_logger()


# ── Usuários ─────────────────────────────────────────────────────────────────

@app.route("/admin/users")
@admin_required
def admin_users():
    users = db.list_users()
    return render_template("admin/users.html", users=users)


@app.route("/admin/users/new", methods=["POST"])
@admin_required
@demo_blocked
def admin_users_new():
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    role = request.form.get("role", "viewer")
    if not username or not password:
        flash(t("Usuário e senha são obrigatórios"), "danger")
    elif len(password) < MIN_PASSWORD_LEN:
        flash(t("A senha precisa ter pelo menos {n} caracteres").format(n=MIN_PASSWORD_LEN), "danger")
    elif db.get_user_by_username(username):
        flash(t("Usuário já existe"), "danger")
    else:
        db.create_user(username, generate_password_hash(password), role)
        flash(t("Usuário {u} criado").format(u=username), "success")
    return redirect(url_for("admin_users"))


@app.route("/admin/users/<int:user_id>/password", methods=["POST"])
@admin_required
@demo_blocked
def admin_users_password(user_id):
    password = request.form.get("password", "")
    if not password:
        flash(t("Senha não pode ser vazia"), "danger")
    elif len(password) < MIN_PASSWORD_LEN:
        flash(t("A senha precisa ter pelo menos {n} caracteres").format(n=MIN_PASSWORD_LEN), "danger")
    else:
        # Senha definida por um admin é temporária: o dono troca no próximo login.
        # Exceção: o admin alterando a PRÓPRIA senha já a define como definitiva.
        is_self = (user_id == session["user_id"])
        db.update_user_password(user_id, generate_password_hash(password),
                                must_change=not is_self)
        if is_self:
            session.pop("must_change_password", None)
        flash(t("Senha atualizada"), "success")
    return redirect(url_for("admin_users"))


@app.route("/admin/users/<int:user_id>/delete", methods=["POST"])
@admin_required
@demo_blocked
def admin_users_delete(user_id):
    if user_id == session["user_id"]:
        flash(t("Você não pode deletar seu próprio usuário"), "danger")
    else:
        db.delete_user(user_id)
        flash(t("Usuário removido"), "success")
    return redirect(url_for("admin_users"))


# ── Marcas ───────────────────────────────────────────────────────────────────

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


@app.route("/admin/brands/new", methods=["POST"])
@admin_required
def admin_brand_new():
    name = request.form.get("name", "").strip()
    if not name:
        flash(t("Nome da marca é obrigatório"), "danger")
        return redirect(url_for("admin_brands"))
    domain = _clean_domain(request.form.get("domain", "").strip())
    db.create_brand(name, domain)
    if domain:
        if _fetch_brand_logo(name, domain):
            flash(t("Marca '{brand}' adicionada com logo").format(brand=name), "success")
        else:
            flash(t("Marca '{brand}' adicionada (logo não encontrado)").format(brand=name), "warning")
    else:
        flash(t("Marca '{brand}' adicionada").format(brand=name), "success")
    return redirect(url_for("admin_brands"))


@app.route("/admin/brands/delete", methods=["POST"])
@admin_required
def admin_brand_delete():
    name = request.form.get("brand_name", "").strip()
    if not name:
        return redirect(url_for("admin_brands"))
    try:
        db.delete_brand(name)
        flash(t("Marca removida"), "success")
    except ValueError as e:
        flash(t(str(e)), "danger")
    return redirect(url_for("admin_brands"))


# ── Configurações ────────────────────────────────────────────────────────────

@app.route("/admin/settings", methods=["GET", "POST"])
@admin_required
def admin_settings():
    if request.method == "POST" and DEMO_MODE:
        flash(t("Função desabilitada na versão demonstrativa."), "warning")
        return redirect(url_for("admin_settings"))
    if request.method == "POST":
        db.set_setting("app_base_url", request.form.get("app_base_url", "").strip())
        db.set_setting("low_stock_threshold_g", request.form.get("low_stock_threshold_g", "200").strip())
        db.set_setting("low_stock_pct", request.form.get("low_stock_pct", "20").strip())
        db.set_setting("label_width_mm", request.form.get("label_width_mm", "60").strip())
        db.set_setting("label_height_mm", request.form.get("label_height_mm", "40").strip())
        # Escolhe-se a FAMÍLIA da impressora (B1/B1 Pro juntas) e o tamanho FÍSICO;
        # o modelo exato e o DPI são detectados na impressão (ver niimbot-spool.js).
        family = request.form.get("niimbot_printer_family", reg.DEFAULT_FAMILY).strip()
        db.set_setting("niimbot_printer_family",
                       family if family in reg.PRINTER_FAMILIES else reg.DEFAULT_FAMILY)
        size = request.form.get("niimbot_label_size", reg.DEFAULT_PHYSICAL_SIZE).strip()
        db.set_setting("niimbot_label_size",
                       size if size in reg.PHYSICAL_SIZES else reg.DEFAULT_PHYSICAL_SIZE)
        flash(t("Configurações salvas"), "success")
        return redirect(url_for("admin_settings"))
    settings = db.get_all_settings()
    # Mostra a URL efetiva (env/IP da instalação) quando o banco ainda está
    # vazio/localhost — o admin vê o que está em uso e salvar passa a valer pra tudo.
    if not settings.get("app_base_url") or settings["app_base_url"] == "http://localhost:5000":
        settings["app_base_url"] = public_base_url()
    return render_template(
        "admin/settings.html", settings=settings,
        niimbot_families=reg.PRINTER_FAMILIES,
        niimbot_printer_family=db.get_setting("niimbot_printer_family", reg.DEFAULT_FAMILY),
        niimbot_sizes=reg.PHYSICAL_SIZES,
        niimbot_label_size=db.get_setting("niimbot_label_size", reg.DEFAULT_PHYSICAL_SIZE),
    )


# ── Atualização do sistema ───────────────────────────────────────────────────

@app.route("/admin/update")
@admin_required
def admin_update():
    # Cache curto (60s) em vez de forçar a cada load: refreshes seguidos reusam o
    # resultado recente. A detecção é por redirect do site (sem REST API), então
    # nem depende mais do limite de 60/h.
    latest = check_latest_release(max_age=60)
    cur = current_version()
    return render_template(
        "admin/update.html",
        current=cur,
        latest=latest,
        update_available=bool(latest) and _version_tuple(latest) > _version_tuple(cur),
        releases_url=RELEASES_URL,
        release_notes=render_release_notes(latest_release_notes()) if latest else "",
    )


@app.route("/admin/update/run", methods=["POST"])
@admin_required
def admin_update_run():
    # Mecanismo SEM privilégio: o app (não-root) apenas ESCREVE um flag em data/.
    # Um systemd .path unit (root) detecta o arquivo via inotify e dispara o oneshot
    # de update — instantâneo, sem o app ter qualquer poder de root.
    flag = db.DB_PATH.parent / ".update-requested"
    try:
        flag.write_text(
            f"{db.now_iso()} by {session.get('username', '?')}\n", encoding="utf-8"
        )
    except Exception:
        log.error("admin.update_flag_failed", exc_info=True)
        return jsonify(ok=False,
                       error="Não foi possível registrar o pedido de atualização."), 500
    log.info("admin.update_triggered")
    return jsonify(ok=True)


# ── Backup / restauração ─────────────────────────────────────────────────────

@app.route("/admin/backup")
@admin_required
def admin_backup():
    # Tabela da rotação diária: o número é o slot (dia da semana ISO); a data
    # mostrada vem do mtime real de cada arquivo (ver backup.list_local_backups).
    return render_template(
        "admin/backup.html",
        local_backups=backup.list_local_backups(),
        external_dir=db.get_setting("backup_external_dir", ""),
        last_run=db.get_setting("backup_last_run", ""),
        last_result=db.get_setting("backup_last_result", ""),
        last_error=db.get_setting("backup_last_error", ""),
        external_error=db.get_setting("backup_external_error", ""),
    )


@app.route("/admin/backup/config", methods=["POST"])
@admin_required
@demo_blocked
def admin_backup_config():
    """Pasta externa do backup agendado (opcional). Testa a gravação na hora p/
    avisar já; o backup diário sempre grava local independente disto."""
    ext_dir = request.form.get("backup_external_dir", "").strip()
    db.set_setting("backup_external_dir", ext_dir)
    if ext_dir:
        werr = backup.test_external_writable(ext_dir)
        if werr:
            flash(t("Pasta de backup externa não é gravável: {e}").format(e=werr), "warning")
    flash(t("Configurações salvas"), "success")
    return redirect(url_for("admin_backup"))


@app.route("/admin/backup/download")
@admin_required
def admin_backup_download():
    # Backup manual = download on-demand. Mantém o nome com timestamp p/ NÃO
    # interferir na rotação diária (que usa nomes numerados por dia da semana).
    data = backup.make_backup_bytes()
    fname = "spool-backup-" + time.strftime("%Y%m%d-%H%M%S") + ".zip"
    return Response(
        data,
        mimetype="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


def _flash_restore_result(ok, n_logos, err):
    if ok:
        flash(t("Backup restaurado com sucesso ({n} logo(s)). Recomendado sair e entrar novamente.").format(n=n_logos), "success")
    else:
        msgs = {
            "not_zip": t("Arquivo inválido — não é um .zip de backup"),
            "no_db": t("Backup inválido: spool.db ausente no arquivo"),
            "invalid_db": t("Backup inválido: o banco não tem a estrutura do Spool Control"),
        }
        flash(msgs.get(err, t("Falha ao restaurar o backup")), "danger")
    return redirect(url_for("admin_backup"))


@app.route("/admin/backup/restore", methods=["POST"])
@admin_required
@demo_blocked
def admin_backup_restore():
    f = request.files.get("backup")
    if not f or not f.filename:
        flash(t("Selecione um arquivo de backup (.zip)"), "danger")
        return redirect(url_for("admin_backup"))
    ok, n, err = backup.restore_from_zip_bytes(f.read())
    return _flash_restore_result(ok, n, err)


@app.route("/admin/backup/restore-local", methods=["POST"])
@admin_required
@demo_blocked
def admin_backup_restore_local():
    """Restaura a partir de um backup da rotação diária (sem upload)."""
    data = backup.read_local_backup_bytes(request.form.get("slot", ""))
    if data is None:
        flash(t("Backup local não encontrado"), "danger")
        return redirect(url_for("admin_backup"))
    ok, n, err = backup.restore_from_zip_bytes(data)
    return _flash_restore_result(ok, n, err)
