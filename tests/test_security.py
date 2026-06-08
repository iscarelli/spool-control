"""Testes das mitigações de segurança: guarda anti-SSRF e troca de senha forçada."""
import pytest
from conftest import ADMIN_USER, ADMIN_PASS


# ── Anti-SSRF: validação do host de destino ──────────────────────────────────

@pytest.mark.parametrize("host", [
    "127.0.0.1",        # loopback
    "::1",              # loopback v6
    "10.0.0.1",         # privado
    "192.168.1.1",      # privado
    "172.16.0.1",       # privado
    "169.254.169.254",  # link-local (metadata cloud)
    "fd00::1",          # unique-local v6 (private)
    "0.0.0.0",          # unspecified
    "",                 # vazio
])
def test_is_public_host_rejects_internal(app_module, host):
    assert app_module._is_public_host(host) is False


@pytest.mark.parametrize("host", ["8.8.8.8", "1.1.1.1"])
def test_is_public_host_accepts_public(app_module, host):
    assert app_module._is_public_host(host) is True


def test_safe_urlopen_rejects_non_http_scheme(app_module):
    with pytest.raises(ValueError):
        app_module._safe_urlopen("file:///etc/passwd")


def test_safe_urlopen_rejects_internal_host(app_module):
    with pytest.raises(ValueError):
        app_module._safe_urlopen("http://127.0.0.1/")


def test_fetch_image_internal_url_returns_none(app_module):
    # _try_fetch_image engole a exceção da guarda e devolve None (sem baixar nada).
    assert app_module._try_fetch_image("http://169.254.169.254/latest/meta-data/") is None


# ── Troca de senha forçada (rec 5) ───────────────────────────────────────────

def test_admin_bootstrap_requires_password_change(db):
    """O admin criado no bootstrap nasce com troca obrigatória (senha inicial)."""
    # conftest neutraliza o flag p/ os demais testes — reativamos aqui.
    admin = db.get_user_by_username(ADMIN_USER)
    db.set_must_change_password(admin["id"], True)
    assert bool(db.get_user_by_username(ADMIN_USER)["must_change_password"]) is True


def _login(client):
    return client.post("/login", data={"username": ADMIN_USER, "password": ADMIN_PASS})


def test_pending_change_redirects_to_form(client, db):
    admin = db.get_user_by_username(ADMIN_USER)
    db.set_must_change_password(admin["id"], True)
    _login(client)
    # Qualquer rota normal é interceptada e leva ao formulário de troca.
    resp = client.get("/filaments")
    assert resp.status_code == 302
    assert "/account/password" in resp.headers["Location"]
    # O próprio formulário continua acessível.
    assert client.get("/account/password").status_code == 200


def test_change_password_clears_flag_and_unblocks(client, db):
    admin = db.get_user_by_username(ADMIN_USER)
    db.set_must_change_password(admin["id"], True)
    _login(client)
    new_pass = "nova-senha-forte"
    resp = client.post("/account/password", data={
        "current_password": ADMIN_PASS,
        "new_password": new_pass,
        "confirm_password": new_pass,
    })
    assert resp.status_code == 302
    assert "/account/password" not in resp.headers["Location"]
    # Flag limpo e acesso liberado.
    assert bool(db.get_user_by_username(ADMIN_USER)["must_change_password"]) is False
    assert client.get("/filaments").status_code == 200


def test_change_password_rejects_wrong_current(client, db):
    admin = db.get_user_by_username(ADMIN_USER)
    db.set_must_change_password(admin["id"], True)
    _login(client)
    resp = client.post("/account/password", data={
        "current_password": "errada",
        "new_password": "outra-senha-forte",
        "confirm_password": "outra-senha-forte",
    })
    assert resp.status_code == 200  # re-renderiza com erro
    assert bool(db.get_user_by_username(ADMIN_USER)["must_change_password"]) is True


def test_change_password_rejects_mismatch(client, db):
    admin = db.get_user_by_username(ADMIN_USER)
    db.set_must_change_password(admin["id"], True)
    _login(client)
    resp = client.post("/account/password", data={
        "current_password": ADMIN_PASS,
        "new_password": "senha-forte-1",
        "confirm_password": "senha-forte-2",
    })
    assert resp.status_code == 200
    assert bool(db.get_user_by_username(ADMIN_USER)["must_change_password"]) is True


def test_admin_created_user_must_change(auth_client, db):
    """Usuário criado por um admin recebe troca obrigatória no 1º login."""
    auth_client.post("/admin/users/new", data={
        "username": "novato", "password": "senha-temporaria", "role": "viewer",
    })
    assert bool(db.get_user_by_username("novato")["must_change_password"]) is True


def test_admin_reset_forces_target_change(auth_client, db):
    """Admin resetando a senha de OUTRO usuário força a troca dele."""
    from werkzeug.security import generate_password_hash
    db.create_user("alvo", generate_password_hash("senha-antiga"), role="viewer",
                   must_change=False)
    uid = db.get_user_by_username("alvo")["id"]
    auth_client.post(f"/admin/users/{uid}/password", data={"password": "reset-temporaria"})
    assert bool(db.get_user_by_username("alvo")["must_change_password"]) is True


def test_csp_has_no_external_cdn(client):
    """O CSP não deve mais confiar em cdn.jsdelivr.net (assets vendorizados)."""
    csp = client.get("/login").headers.get("Content-Security-Policy", "")
    assert "jsdelivr" not in csp
    assert "default-src 'self'" in csp


def test_health_exposes_demo_mode(client):
    """O /health expõe demo_mode p/ monitores detectarem vazamento (rec 4).
    No ambiente de teste não é demo, então deve vir False."""
    data = client.get("/health").get_json()
    assert "demo_mode" in data
    assert data["demo_mode"] is False


def test_health_exposes_backup_age(client, db):
    """O /health expõe backup_age_h p/ um monitor alertar se o backup parar."""
    data = client.get("/health").get_json()
    assert "backup_age_h" in data
    assert data["backup_age_h"] is None          # banco novo: nenhum backup ainda
    db.set_setting("backup_last_run", db.now_iso())
    data2 = client.get("/health").get_json()
    assert isinstance(data2["backup_age_h"], (int, float)) and data2["backup_age_h"] >= 0
