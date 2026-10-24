"""Passkeys (WebAuthn) como segundo fator. O autenticador real não existe aqui: as
funções verify_* do py_webauthn são trocadas por fakes; o resto (rotas, sessão,
challenge de uso único, throttle, posse da credencial) roda de verdade."""
from types import SimpleNamespace

import pyotp
import pytest
from werkzeug.security import generate_password_hash

from conftest import ADMIN_USER, ADMIN_PASS

CRED_ID = b"cred-id-bytes-0001"
CRED_B64 = "Y3JlZC1pZC1ieXRlcy0wMDAx"   # base64url de CRED_ID


@pytest.fixture()
def pk(app_module, monkeypatch):
    """Módulo routes.passkey com verify_* fakes que aceitam tudo."""
    import routes.passkey as mod
    monkeypatch.setattr(mod, "verify_registration_response", lambda **kw: SimpleNamespace(
        credential_id=CRED_ID, credential_public_key=b"pubkey", sign_count=0))
    monkeypatch.setattr(mod, "verify_authentication_response",
                        lambda **kw: SimpleNamespace(new_sign_count=5))
    return mod


def _enable_totp(db, username=ADMIN_USER):
    u = db.get_user_by_username(username)
    db.set_totp_secret(u["id"], pyotp.random_base32())
    db.enable_totp(u["id"])
    return u["id"]


def _register(client, name="Meu iPhone"):
    assert client.post("/account/passkey/register/options").status_code == 200
    return client.post("/account/passkey/register/verify",
                       json={"credential": {"id": CRED_B64}, "name": name})


def _to_pre2fa(client, next_url=None):
    url = "/login" + (f"?next={next_url}" if next_url else "")
    r = client.post(url, data={"username": ADMIN_USER, "password": ADMIN_PASS})
    assert r.status_code == 302 and "/login/2fa" in r.headers["Location"]


# ── Registro ─────────────────────────────────────────────────────────────────

def test_register_requires_login(client):
    assert client.post("/account/passkey/register/options").status_code == 401
    assert client.post("/account/passkey/register/verify", json={}).status_code == 401


def test_register_requires_totp_enabled(auth_client, db):
    assert auth_client.post("/account/passkey/register/options").status_code == 400
    assert db.list_passkeys(db.get_user_by_username(ADMIN_USER)["id"]) == []


def test_register_options_shape(auth_client, db):
    _enable_totp(db)
    r = auth_client.post("/account/passkey/register/options")
    j = r.get_json()
    assert j["authenticatorSelection"]["userVerification"] == "required"
    assert j["authenticatorSelection"]["residentKey"] == "preferred"
    assert j["rp"]["id"] == "localhost"


def test_register_saves_credential_with_name(auth_client, db, pk):
    uid = _enable_totp(db)
    assert _register(auth_client).status_code == 200
    rows = db.list_passkeys(uid)
    assert len(rows) == 1 and rows[0]["name"] == "Meu iPhone"
    assert rows[0]["credential_id"] == CRED_B64


def test_register_default_name_from_user_agent(auth_client, db, pk):
    uid = _enable_totp(db)
    auth_client.post("/account/passkey/register/options")
    auth_client.post("/account/passkey/register/verify", json={"credential": {}},
                     headers={"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17)"})
    assert db.list_passkeys(uid)[0]["name"] == "iPhone"


def test_register_challenge_is_single_use(auth_client, db, pk):
    uid = _enable_totp(db)
    auth_client.post("/account/passkey/register/options")
    assert auth_client.post("/account/passkey/register/verify",
                            json={"credential": {}}).status_code == 200
    # Mesmo challenge de novo: já foi consumido.
    assert auth_client.post("/account/passkey/register/verify",
                            json={"credential": {}}).status_code == 400
    assert len(db.list_passkeys(uid)) == 1


def test_register_verify_failure_is_400(auth_client, db, pk, monkeypatch):
    uid = _enable_totp(db)

    def boom(**kw):
        raise ValueError("bad")
    monkeypatch.setattr(pk, "verify_registration_response", boom)
    auth_client.post("/account/passkey/register/options")
    assert auth_client.post("/account/passkey/register/verify",
                            json={"credential": {}}).status_code == 400
    assert db.list_passkeys(uid) == []


def test_register_blocked_in_demo_mode(auth_client, db, pk, monkeypatch):
    _enable_totp(db)
    monkeypatch.setattr(pk, "DEMO_MODE", True)
    assert auth_client.post("/account/passkey/register/options").status_code == 403
    assert auth_client.post("/account/passkey/register/verify",
                            json={"credential": {}}).status_code == 403


# ── Remoção ──────────────────────────────────────────────────────────────────

def test_delete_only_own_passkey(auth_client, db, pk):
    uid = _enable_totp(db)
    _register(auth_client)
    db.create_user("outro", generate_password_hash("outro-pass-123"),
                   role="viewer", must_change=False)
    other_id = db.get_user_by_username("outro")["id"]
    db.add_passkey(other_id, "other-cred", b"k", 0, "alheia")
    foreign = db.list_passkeys(other_id)[0]["id"]
    assert auth_client.post(f"/account/passkey/{foreign}/delete").status_code == 404
    assert len(db.list_passkeys(other_id)) == 1
    own = db.list_passkeys(uid)[0]["id"]
    assert auth_client.post(f"/account/passkey/{own}/delete").status_code == 200
    assert db.list_passkeys(uid) == []


def test_disabling_totp_deletes_passkeys(auth_client, db, pk):
    uid = _enable_totp(db)
    _register(auth_client)
    assert len(db.list_passkeys(uid)) == 1
    secret = db.get_user_by_id(uid)["totp_secret"]
    auth_client.post("/account/2fa", data={
        "action": "disable", "password": ADMIN_PASS, "code": pyotp.TOTP(secret).now()})
    assert not db.get_user_by_id(uid)["totp_enabled"]
    assert db.list_passkeys(uid) == []


def test_account_page_lists_passkeys(auth_client, db, pk):
    _enable_totp(db)
    _register(auth_client, name="Cofre")
    html = auth_client.get("/account/2fa").get_data(as_text=True)
    assert "Cofre" in html and "passkey.js" in html


# ── Login ────────────────────────────────────────────────────────────────────

def test_login_options_require_pre2fa(client):
    assert client.post("/login/2fa/passkey/options").status_code == 401
    assert client.post("/login/2fa/passkey/verify", json={}).status_code == 401


def test_login_page_shows_button_only_with_passkey(client, db, pk):
    uid = _enable_totp(db)
    _to_pre2fa(client)
    assert "passkeyLogin" not in client.get("/login/2fa").get_data(as_text=True)
    db.add_passkey(uid, CRED_B64, b"k", 0, "x")
    assert "passkeyLogin" in client.get("/login/2fa").get_data(as_text=True)


def test_login_options_need_a_passkey(client, db, pk):
    _enable_totp(db)
    _to_pre2fa(client)
    assert client.post("/login/2fa/passkey/options").status_code == 400


def _login_ready(client, db, next_url=None):
    uid = _enable_totp(db)
    db.add_passkey(uid, CRED_B64, b"k", 3, "x")
    _to_pre2fa(client, next_url)
    r = client.post("/login/2fa/passkey/options")
    assert r.status_code == 200
    j = r.get_json()
    assert j["userVerification"] == "required"
    assert [c["id"] for c in j["allowCredentials"]] == [CRED_B64]
    return uid


def test_login_success_promotes_session_and_honours_next(client, db, pk):
    uid = _login_ready(client, db, next_url="/spools")
    r = client.post("/login/2fa/passkey/verify", json={"credential": {"id": CRED_B64}})
    assert r.status_code == 200 and r.get_json()["redirect"] == "/spools"
    with client.session_transaction() as s:
        assert s["user_id"] == uid and "pre2fa_user_id" not in s
    assert db.list_passkeys(uid)[0]["sign_count"] == 5
    assert db.list_passkeys(uid)[0]["last_used_at"]
    assert client.get("/spools").status_code == 200


def test_login_challenge_is_single_use(client, db, pk):
    _login_ready(client, db)
    cred = {"credential": {"id": CRED_B64}}
    client.post("/login/2fa/passkey/verify", json=cred)   # consome e entra
    # Nova sessão pré-2FA sem pedir novo challenge: tem de falhar.
    c2 = client.application.test_client()
    _to_pre2fa(c2)
    assert c2.post("/login/2fa/passkey/verify", json=cred).status_code == 400


def test_login_refuses_other_users_credential(client, db, pk):
    _enable_totp(db)
    db.create_user("outro", generate_password_hash("outro-pass-123"),
                   role="viewer", must_change=False)
    other_id = db.get_user_by_username("outro")["id"]
    db.add_passkey(other_id, "zm9yZWlnbg", b"k", 0, "alheia")
    admin = db.get_user_by_username(ADMIN_USER)
    db.add_passkey(admin["id"], CRED_B64, b"k", 0, "minha")
    _to_pre2fa(client)
    client.post("/login/2fa/passkey/options")
    r = client.post("/login/2fa/passkey/verify", json={"credential": {"id": "zm9yZWlnbg"}})
    assert r.status_code == 400
    with client.session_transaction() as s:
        assert "user_id" not in s


def test_login_failure_records_failure_and_throttles(client, db, pk, monkeypatch):
    _login_ready(client, db)

    def boom(**kw):
        raise ValueError("bad sig")
    monkeypatch.setattr(pk, "verify_authentication_response", boom)
    import app as app_mod
    assert db.count_recent_login_failures("127.0.0.1", app_mod.LOGIN_WINDOW_MIN) == 0
    r = client.post("/login/2fa/passkey/verify", json={"credential": {"id": CRED_B64}})
    assert r.status_code == 400
    assert db.count_recent_login_failures("127.0.0.1", app_mod.LOGIN_WINDOW_MIN) == 1
    with client.session_transaction() as s:
        assert "user_id" not in s and "pre2fa_user_id" in s
    for _ in range(app_mod.LOGIN_MAX_FAILURES):
        db.record_login_failure("127.0.0.1", ADMIN_USER)
    r = client.post("/login/2fa/passkey/verify", json={"credential": {"id": CRED_B64}})
    assert r.status_code == 429


def test_totp_login_still_works_with_passkeys_registered(client, db, pk):
    uid = _enable_totp(db)
    db.add_passkey(uid, CRED_B64, b"k", 0, "x")
    _to_pre2fa(client)
    secret = db.get_user_by_id(uid)["totp_secret"]
    r = client.post("/login/2fa", data={"code": pyotp.TOTP(secret).now()})
    assert r.status_code == 302
    with client.session_transaction() as s:
        assert s["user_id"] == uid
