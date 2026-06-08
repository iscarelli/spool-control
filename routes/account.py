"""Conta do próprio usuário: troca de senha (self-service).

Também é o destino do gate de troca obrigatória (senha temporária) definido em
app.py (_force_password_change)."""
from flask import render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
import database as db
import logger as log_cfg
from app import app, login_required, demo_blocked, t, MIN_PASSWORD_LEN

log = log_cfg.get_logger()


@app.route("/account/password", methods=["GET", "POST"])
@login_required
@demo_blocked
def account_password():
    forced = bool(session.get("must_change_password"))
    if request.method == "POST":
        current = request.form.get("current_password", "")
        new = request.form.get("new_password", "")
        confirm = request.form.get("confirm_password", "")
        user = db.get_user_by_id(session["user_id"])
        if not user or not check_password_hash(user["password_hash"], current):
            flash(t("Senha atual incorreta"), "danger")
        elif len(new) < MIN_PASSWORD_LEN:
            flash(t("A senha precisa ter pelo menos {n} caracteres").format(n=MIN_PASSWORD_LEN), "danger")
        elif new != confirm:
            flash(t("As senhas não coincidem"), "danger")
        elif new == current:
            flash(t("A nova senha deve ser diferente da atual"), "danger")
        else:
            db.update_user_password(session["user_id"], generate_password_hash(new),
                                    must_change=False)
            session.pop("must_change_password", None)
            log.info("account.password_changed", forced=forced)
            flash(t("Senha alterada com sucesso"), "success")
            return redirect(url_for("dashboard"))
    return render_template("account/password.html", forced=forced)
