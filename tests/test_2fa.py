"""Testes do 2FA (TOTP opcional por usuário): ativação, login em 2 fases,
códigos de recuperação one-time, desativação, throttle e o reset de lockout."""
import pyotp
import pytest
from conftest import ADMIN_USER, ADMIN_PASS


# ── Helpers ──────────────────────────────────────────────────────────────────

def _enable_2fa(client):
    """Passa pelo fluxo real de ativação e devolve (secret, recovery_codes)."""
    # GET gera o segredo pendente e o coloca na sessão.
    client.get("/account/2fa")
    with client.session_transaction() as sess:
        secret = sess["pending_totp_secret"]
    resp = client.post("/account/2fa", data={
        "action": "activate",
        "code": pyotp.TOTP(secret).now(),
    })
    assert resp.status_code == 200
    return secret


def _seed_2fa(db, app_module, secret=None):
    """Atalho de baixo nível: liga o 2FA do admin direto no banco."""
    secret = secret or pyotp.random_base32()
    admin = db.get_user_by_username(ADMIN_USER)
    db.set_totp_secret(admin["id"], secret)
    db.enable_totp(admin["id"])
    return secret, admin["id"]


# ── Ativação ─────────────────────────────────────────────────────────────────

def test_activate_enables_totp_and_shows_codes(auth_client, db):
    secret = _enable_2fa(auth_client)
    admin = db.get_user_by_username(ADMIN_USER)
    assert bool(admin["totp_enabled"]) is True
    assert admin["totp_secret"] == secret
    # 8 códigos de recuperação foram gerados.
    assert db.count_recovery_codes_remaining(admin["id"]) == 8


def test_activate_rejects_wrong_code(auth_client, db):
    auth_client.get("/account/2fa")
    resp = auth_client.post("/account/2fa", data={"action": "activate", "code": "000000"})
    assert resp.status_code == 200
    assert bool(db.get_user_by_username(ADMIN_USER)["totp_enabled"]) is False


# ── Login em 2 fases ──────────────────────────────────────────────────────────

def test_login_with_2fa_requires_second_step(client, db, app_module):
    secret, _ = _seed_2fa(db, app_module)
    # Fase 1: senha correta NÃO abre sessão; redireciona p/ /login/2fa.
    resp = client.post("/login", data={"username": ADMIN_USER, "password": ADMIN_PASS})
    assert resp.status_code == 302
    assert "/login/2fa" in resp.headers["Location"]
    with client.session_transaction() as sess:
        assert "user_id" not in sess
        assert sess.get("pre2fa_user_id") is not None
    # Fase 2: código TOTP correto promove a sessão.
    resp2 = client.post("/login/2fa", data={"code": pyotp.TOTP(secret).now()})
    assert resp2.status_code == 302
    with client.session_transaction() as sess:
        assert "user_id" in sess
        assert "pre2fa_user_id" not in sess


def test_login_2fa_wrong_code_does_not_authenticate(client, db, app_module):
    _seed_2fa(db, app_module)
    client.post("/login", data={"username": ADMIN_USER, "password": ADMIN_PASS})
    resp = client.post("/login/2fa", data={"code": "000000"})
    assert resp.status_code == 200  # re-renderiza com erro, sem redirect
    with client.session_transaction() as sess:
        assert "user_id" not in sess


def test_login_2fa_without_prestate_redirects_to_login(client):
    resp = client.get("/login/2fa")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_protected_route_blocked_during_pre2fa(client, db, app_module):
    """Estado pré-2FA não é sessão válida — rotas protegidas continuam barradas."""
    _seed_2fa(db, app_module)
    client.post("/login", data={"username": ADMIN_USER, "password": ADMIN_PASS})
    resp = client.get("/filaments")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


# ── Códigos de recuperação ────────────────────────────────────────────────────

def test_recovery_code_logs_in_and_is_single_use(client, auth_client, db, app_module):
    # Ativa via fluxo real p/ obter códigos reais não é trivial (mostrados só no HTML);
    # então geramos e guardamos diretamente, mas validamos o consumo via /login/2fa.
    from werkzeug.security import generate_password_hash
    secret, uid = _seed_2fa(db, app_module)
    codes = ["aaaa1111", "bbbb2222"]
    db.store_recovery_codes(uid, [generate_password_hash(c) for c in codes])

    client.post("/login", data={"username": ADMIN_USER, "password": ADMIN_PASS})
    resp = client.post("/login/2fa", data={"code": "aaaa1111"})
    assert resp.status_code == 302
    with client.session_transaction() as sess:
        assert "user_id" in sess
    assert db.count_recovery_codes_remaining(uid) == 1

    # Reuso do MESMO código falha.
    assert db.consume_recovery_code(uid, "aaaa1111") is False
    # O outro ainda funciona uma vez.
    assert db.consume_recovery_code(uid, "bbbb2222") is True
    assert db.count_recovery_codes_remaining(uid) == 0


# ── Desativação ───────────────────────────────────────────────────────────────

def test_disable_clears_secret_and_codes(auth_client, db):
    secret = _enable_2fa(auth_client)
    admin = db.get_user_by_username(ADMIN_USER)
    resp = auth_client.post("/account/2fa", data={
        "action": "disable",
        "password": ADMIN_PASS,
        "code": pyotp.TOTP(secret).now(),
    })
    assert resp.status_code == 302
    admin = db.get_user_by_username(ADMIN_USER)
    assert bool(admin["totp_enabled"]) is False
    assert admin["totp_secret"] == ""
    assert db.count_recovery_codes_remaining(admin["id"]) == 0


def test_disable_requires_correct_password(auth_client, db):
    secret = _enable_2fa(auth_client)
    resp = auth_client.post("/account/2fa", data={
        "action": "disable",
        "password": "senha-errada",
        "code": pyotp.TOTP(secret).now(),
    })
    assert resp.status_code == 302  # redireciona com flash de erro
    assert bool(db.get_user_by_username(ADMIN_USER)["totp_enabled"]) is True


# ── Throttle no segundo passo ─────────────────────────────────────────────────

def test_login_2fa_throttled_after_max_failures(client, db, app_module):
    _seed_2fa(db, app_module)
    ip = "203.0.113.7"
    # Fase 1 limpa: estabelece o estado pré-2FA (e zera falhas anteriores do IP).
    client.post("/login", data={"username": ADMIN_USER, "password": ADMIN_PASS},
                environ_overrides={"REMOTE_ADDR": ip})
    # Agora estoura o limite de falhas e tenta o segundo passo → bloqueado.
    for _ in range(app_module.LOGIN_MAX_FAILURES):
        db.record_login_failure(ip, ADMIN_USER)
    resp = client.post("/login/2fa", data={"code": "000000"},
                       environ_overrides={"REMOTE_ADDR": ip})
    assert resp.status_code == 429


# ── DEMO_MODE bloqueia o setup ────────────────────────────────────────────────

def test_demo_mode_blocks_2fa_setup(auth_client, app_module, monkeypatch):
    monkeypatch.setattr(app_module, "DEMO_MODE", True)
    resp = auth_client.get("/account/2fa")
    assert resp.status_code == 302  # demo_blocked redireciona


# ── Oferta de 2FA no primeiro login ───────────────────────────────────────────

def test_forced_password_change_offers_2fa(client, db):
    """Trocar a senha temporária no 1º login leva ao convite (opcional) de 2FA."""
    admin = db.get_user_by_username(ADMIN_USER)
    db.set_must_change_password(admin["id"], True)
    client.post("/login", data={"username": ADMIN_USER, "password": ADMIN_PASS})
    resp = client.post("/account/password", data={
        "current_password": ADMIN_PASS,
        "new_password": "nova-senha-forte",
        "confirm_password": "nova-senha-forte",
    })
    assert resp.status_code == 302
    assert "/account/2fa/offer" in resp.headers["Location"]
    # O convite em si é acessível e não obriga nada (sem 2FA ainda).
    assert client.get("/account/2fa/offer").status_code == 200


def test_2fa_offer_skipped_when_already_enabled(auth_client, db, app_module):
    """Quem já tem 2FA ativo não vê o convite — vai direto ao painel."""
    _seed_2fa(db, app_module)
    resp = auth_client.get("/account/2fa/offer")
    assert resp.status_code == 302
    assert "/account/2fa/offer" not in resp.headers["Location"]


# ── reset-2fa.py zera o 2FA ───────────────────────────────────────────────────

def test_reset_script_disables_2fa(db, app_module, monkeypatch):
    import os
    secret, uid = _seed_2fa(db, app_module)
    from werkzeug.security import generate_password_hash
    db.store_recovery_codes(uid, [generate_password_hash("zzzz9999")])

    import importlib.util
    from pathlib import Path
    script = Path(app_module.__file__).parent / "deploy" / "reset-2fa.py"
    spec = importlib.util.spec_from_file_location("reset_2fa", script)
    mod = importlib.util.module_from_spec(spec)
    monkeypatch.setenv("SPOOL_DB_PATH", os.environ["SPOOL_DB_PATH"])
    monkeypatch.setattr("sys.argv", ["reset-2fa.py", ADMIN_USER])
    # Recarrega o módulo lendo o DB_PATH do ambiente no import.
    spec.loader.exec_module(mod)
    rc = mod.main()
    assert rc == 0
    admin = db.get_user_by_username(ADMIN_USER)
    assert bool(admin["totp_enabled"]) is False
    assert admin["totp_secret"] == ""
    assert db.count_recovery_codes_remaining(uid) == 0
