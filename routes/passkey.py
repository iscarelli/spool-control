"""Passkeys (WebAuthn) como SEGUNDO fator do login — Face ID / Touch ID.

A senha continua sendo o primeiro passo e o TOTP/código de recuperação continua
valendo como alternativa (routes/account.py + app.py:login_2fa). Passkey só existe
para quem já tem 2FA ligado; desligar o 2FA apaga as passkeys (database.disable_totp).

Relying party: derivada de CADA requisição, não configurada — cada instalação tem o
próprio domínio. Atrás do Traefik o ProxyFix (app.py:139, x_host/x_proto) faz
`request.host`/`request.scheme` refletirem o que o navegador viu."""
from urllib.parse import urlparse

from flask import jsonify, request, session
from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

import database as db
import logger as log_cfg
from app import (
    app, DEMO_MODE, LOGIN_MAX_FAILURES, LOGIN_WINDOW_MIN, _promote_session, t,
)

log = log_cfg.get_logger()

RP_NAME = "Spool Control"
_REG_CHALLENGE = "passkey_reg_challenge"
_AUTH_CHALLENGE = "passkey_auth_challenge"


def _rp():
    """(rp_id, expected_origin) da requisição atual. rp_id = hostname sem porta;
    origin = esquema + host (com porta, se houver) como o navegador o enxerga."""
    host = request.host
    return urlparse("//" + host).hostname or host, f"{request.scheme}://{host}"


def _err(msg, status):
    return jsonify(error=msg), status


def _guess_name(user_agent):
    ua = user_agent or ""
    for needle, label in (("iPhone", "iPhone"), ("iPad", "iPad"), ("Android", "Android"),
                          ("Macintosh", "Mac"), ("Windows", "Windows"), ("Linux", "Linux")):
        if needle in ua:
            return label
    return t("Passkey")


def _descriptors(rows):
    return [PublicKeyCredentialDescriptor(id=base64url_to_bytes(r["credential_id"]))
            for r in rows]


# ── Registro (usuário logado, com 2FA ligado) ────────────────────────────────

def _registration_user():
    """Usuário logado habilitado a registrar passkey, ou (None, resposta_de_erro)."""
    if "user_id" not in session:
        return None, _err(t("Não autorizado"), 401)
    if DEMO_MODE:
        return None, _err(t("Função desabilitada na versão demonstrativa."), 403)
    user = db.get_user_by_id(session["user_id"])
    if not user or not user["totp_enabled"]:
        return None, _err(t("Ative a verificação em duas etapas antes de adicionar uma passkey."), 400)
    return user, None


@app.route("/account/passkey/register/options", methods=["POST"])
def passkey_register_options():
    user, err = _registration_user()
    if err:
        return err
    rp_id, _origin = _rp()
    opts = generate_registration_options(
        rp_id=rp_id,
        rp_name=RP_NAME,
        user_id=str(user["id"]).encode(),
        user_name=user["username"],
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.PREFERRED,
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
        exclude_credentials=_descriptors(db.list_passkeys(user["id"])),
    )
    session[_REG_CHALLENGE] = bytes_to_base64url(opts.challenge)
    return app.response_class(options_to_json(opts), mimetype="application/json")


@app.route("/account/passkey/register/verify", methods=["POST"])
def passkey_register_verify():
    user, err = _registration_user()
    if err:
        return err
    challenge = session.pop(_REG_CHALLENGE, None)   # uso único
    if not challenge:
        return _err(t("Sessão expirada. Tente novamente."), 400)
    body = request.get_json(silent=True) or {}
    rp_id, origin = _rp()
    try:
        verified = verify_registration_response(
            credential=body.get("credential"),
            expected_challenge=base64url_to_bytes(challenge),
            expected_rp_id=rp_id,
            expected_origin=origin,
            require_user_verification=True,
        )
    except Exception:
        log.warning("account.passkey_register_fail")
        return _err(t("Não foi possível registrar a passkey."), 400)
    name = (str(body.get("name") or "").strip()[:60]
            or _guess_name(request.headers.get("User-Agent")))
    cred_id = bytes_to_base64url(verified.credential_id)
    if db.get_passkey_by_credential_id(cred_id):
        return _err(t("Esta passkey já está registrada."), 400)
    db.add_passkey(user["id"], cred_id, verified.credential_public_key,
                   verified.sign_count, name)
    log.info("account.passkey_added")
    return jsonify(ok=True)


@app.route("/account/passkey/<int:pk_id>/delete", methods=["POST"])
def passkey_delete(pk_id):
    if "user_id" not in session:
        return _err(t("Não autorizado"), 401)
    if DEMO_MODE:
        return _err(t("Função desabilitada na versão demonstrativa."), 403)
    if not db.delete_passkey(session["user_id"], pk_id):
        return _err(t("Passkey não encontrada."), 404)
    log.info("account.passkey_deleted")
    return jsonify(ok=True)


# ── Login: segundo fator ─────────────────────────────────────────────────────

def _pre2fa_user():
    uid = session.get("pre2fa_user_id")
    user = db.get_user_by_id(uid) if uid else None
    if not user or not user["totp_enabled"]:
        return None
    return user


@app.route("/login/2fa/passkey/options", methods=["POST"])
def login_passkey_options():
    user = _pre2fa_user()
    if not user:
        return _err(t("Não autorizado"), 401)
    rows = db.list_passkeys(user["id"])
    if not rows:
        return _err(t("Nenhuma passkey registrada."), 400)
    rp_id, _origin = _rp()
    opts = generate_authentication_options(
        rp_id=rp_id,
        allow_credentials=_descriptors(rows),
        user_verification=UserVerificationRequirement.REQUIRED,
    )
    session[_AUTH_CHALLENGE] = bytes_to_base64url(opts.challenge)
    return app.response_class(options_to_json(opts), mimetype="application/json")


@app.route("/login/2fa/passkey/verify", methods=["POST"])
def login_passkey_verify():
    user = _pre2fa_user()
    if not user:
        return _err(t("Não autorizado"), 401)
    ip = request.remote_addr or ""
    # Mesmo throttle por IP da senha/TOTP.
    if db.count_recent_login_failures(ip, LOGIN_WINDOW_MIN) >= LOGIN_MAX_FAILURES:
        return _err(t("Muitas tentativas. Aguarde {min} minutos e tente novamente.")
                    .format(min=LOGIN_WINDOW_MIN), 429)
    challenge = session.pop(_AUTH_CHALLENGE, None)   # uso único
    body = request.get_json(silent=True) or {}
    cred = body.get("credential")
    row = None
    if isinstance(cred, dict) and isinstance(cred.get("id"), str):
        row = db.get_passkey_by_credential_id(cred["id"])
    ok = False
    if challenge and row and row["user_id"] == user["id"]:
        rp_id, origin = _rp()
        try:
            res = verify_authentication_response(
                credential=cred,
                expected_challenge=base64url_to_bytes(challenge),
                expected_rp_id=rp_id,
                expected_origin=origin,
                credential_public_key=bytes(row["public_key"]),
                credential_current_sign_count=row["sign_count"],
                require_user_verification=True,
            )
            db.touch_passkey(row["id"], res.new_sign_count)
            ok = True
        except Exception:
            ok = False
    if not ok:
        db.record_login_failure(ip, user["username"])
        log.warning("auth.2fa_fail", method="passkey")
        return _err(t("Passkey inválida"), 400)
    db.clear_login_failures(ip)
    remember = bool(session.pop("pre2fa_remember", False))
    nxt = session.pop("pre2fa_next", "") or ""
    session.pop("pre2fa_user_id", None)
    log.info("auth.2fa_ok", method="passkey")
    resp = _promote_session(user, remember, ip, nxt)
    return jsonify(redirect=resp.location)
