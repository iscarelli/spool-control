"""Conta do próprio usuário: troca de senha e 2FA (self-service).

Também é o destino do gate de troca obrigatória (senha temporária) definido em
app.py (_force_password_change)."""
import io
import base64
import secrets
import pyotp
from flask import render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
import database as db
import labels
import logger as log_cfg
from app import app, login_required, demo_blocked, t, MIN_PASSWORD_LEN

log = log_cfg.get_logger()

# Quantidade de códigos de recuperação gerados na ativação/regeneração do 2FA.
RECOVERY_CODE_COUNT = 8


def _qr_data_uri(uri):
    """QR do provisioning URI como data-URI PNG (CSP já permite img-src data:)."""
    img = labels._make_qr_image(uri)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def _gen_recovery_codes():
    """8 códigos one-time legíveis (8 hex). Retorna (texto_p/_mostrar, hashes_p/_guardar)."""
    codes = [secrets.token_hex(4) for _ in range(RECOVERY_CODE_COUNT)]
    return codes, [generate_password_hash(c) for c in codes]


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


@app.route("/account/2fa", methods=["GET", "POST"])
@login_required
@demo_blocked
def account_2fa():
    """Configuração do 2FA (TOTP) do próprio usuário: ativar, desativar e regenerar
    os códigos de recuperação. Opt-in, off por padrão."""
    user = db.get_user_by_id(session["user_id"])
    new_codes = None   # códigos de recuperação a mostrar UMA vez (ativação/regeneração)

    if request.method == "POST":
        action = request.form.get("action", "")
        code = request.form.get("code", "").strip().replace(" ", "")

        # ── Ativar: confirma um código contra o segredo pendente na sessão ──
        if action == "activate" and not user["totp_enabled"]:
            secret = session.get("pending_totp_secret")
            if not secret:
                flash(t("Sessão expirada. Tente novamente."), "danger")
                return redirect(url_for("account_2fa"))
            if pyotp.TOTP(secret).verify(code, valid_window=1):
                db.set_totp_secret(user["id"], secret)
                db.enable_totp(user["id"])
                session.pop("pending_totp_secret", None)
                codes, hashes = _gen_recovery_codes()
                db.store_recovery_codes(user["id"], hashes)
                new_codes = codes
                log.info("account.2fa_enabled")
                flash(t("Verificação em duas etapas ativada"), "success")
                user = db.get_user_by_id(session["user_id"])
            else:
                # Mantém o segredo pendente → o mesmo QR é re-exibido abaixo.
                flash(t("Código inválido"), "danger")

        # ── Desativar: exige senha atual + um código (TOTP ou recuperação) ──
        elif action == "disable" and user["totp_enabled"]:
            password = request.form.get("password", "")
            if not check_password_hash(user["password_hash"], password):
                flash(t("Senha atual incorreta"), "danger")
            elif not (pyotp.TOTP(user["totp_secret"]).verify(code, valid_window=1)
                      or db.consume_recovery_code(user["id"], code)):
                flash(t("Código inválido"), "danger")
            else:
                db.disable_totp(user["id"])
                session.pop("pending_totp_secret", None)
                log.info("account.2fa_disabled")
                flash(t("Verificação em duas etapas desativada"), "success")
            return redirect(url_for("account_2fa"))

        # ── Regenerar códigos: exige um código válido (TOTP ou recuperação) ──
        elif action == "regenerate" and user["totp_enabled"]:
            if not (pyotp.TOTP(user["totp_secret"]).verify(code, valid_window=1)
                    or db.consume_recovery_code(user["id"], code)):
                flash(t("Código inválido"), "danger")
                return redirect(url_for("account_2fa"))
            codes, hashes = _gen_recovery_codes()
            db.store_recovery_codes(user["id"], hashes)
            new_codes = codes
            log.info("account.2fa_codes_regenerated")
            flash(t("Novos códigos de recuperação gerados"), "success")

    enabled = bool(user["totp_enabled"])
    qr_uri = manual_key = None
    if not enabled:
        # Segredo PENDENTE na sessão (estável entre GETs → QR não muda enquanto
        # o usuário escaneia). Só vira definitivo ao confirmar um código.
        secret = session.get("pending_totp_secret")
        if not secret:
            secret = pyotp.random_base32()
            session["pending_totp_secret"] = secret
        prov_uri = pyotp.totp.TOTP(secret).provisioning_uri(
            name=user["username"], issuer_name="Spool Control")
        qr_uri = _qr_data_uri(prov_uri)
        manual_key = secret
    else:
        session.pop("pending_totp_secret", None)

    remaining = db.count_recovery_codes_remaining(user["id"]) if enabled else 0
    return render_template(
        "account/2fa.html", enabled=enabled, qr_uri=qr_uri, manual_key=manual_key,
        new_codes=new_codes, remaining=remaining,
    )
