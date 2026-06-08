"""Rotas administrativas (só admin): usuários, marcas, configurações, atualização
do sistema e backup/restauração."""
import io
import os
import re
import json
import time
import zipfile
import tempfile
import subprocess
from pathlib import Path
from flask import (
    render_template, request, redirect, url_for, session, flash, jsonify, Response,
)
from werkzeug.security import generate_password_hash
import database as db
import niimbot_registry as reg
import logger as log_cfg
from app import (
    app, admin_required, demo_blocked, t, MIN_PASSWORD_LEN, DEMO_MODE,
    BRANDS_DIR, _fetch_brand_logo, _clean_domain, public_base_url, APP_VERSION,
    RELEASES_URL, check_latest_release, current_version, _version_tuple,
    latest_release_notes, render_release_notes,
)

log = log_cfg.get_logger()

# Extensões de logo aceitas no restore — espelha o upload de marcas; SVG fica de
# fora de propósito (pode embutir <script> e virar XSS servido same-origin).
BACKUP_LOGO_EXTS = ('.png', '.jpg', '.jpeg', '.webp')


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
    latest = check_latest_release(force=True)
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
    # Fallback transitório (Seamless): em instalações onde o vigia .path ainda não foi
    # instalado (ele entra na PRÓXIMA atualização, junto do novo update-lxc.sh), o grant
    # sudoers legado dispara o oneshot. `-n` evita prompt; falha é ignorada. Vira no-op
    # assim que o sudoers é removido — aí o flag + .path assumem sozinhos.
    try:
        subprocess.run(
            ["sudo", "-n", "systemctl", "start", "--no-block", "spool-update.service"],
            check=False, capture_output=True, text=True, timeout=10,
        )
    except Exception:
        pass  # sem sudoers (ou sem sudo) → tudo bem, o vigia .path cuida do flag
    log.info("admin.update_triggered")
    return jsonify(ok=True)


@app.route("/admin/update/status")
@admin_required
def admin_update_status():
    latest = check_latest_release()
    cur = current_version()
    done = bool(latest) and _version_tuple(cur) >= _version_tuple(latest)
    return jsonify(current=cur, latest=latest, done=done)


# ── Backup / restauração ─────────────────────────────────────────────────────

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
@demo_blocked
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
