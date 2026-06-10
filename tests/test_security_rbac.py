"""Testes das correções de segurança desta release:

  #2  RBAC de escrita — `viewer` (somente leitura) não alcança rotas de mutação.
  #3  Revogação de sessão server-side — logout / troca de senha invalidam cookies.
  #4  Chave de API não trafega no DOM — revelada sob demanda por endpoint admin.
  #5  HTTPException não vira 500 — método errado responde 405, não 500.
  #9  /.well-known/security.txt servido (RFC 9116).
"""
import pytest
from conftest import ADMIN_USER, ADMIN_PASS, VIEWER_USER, VIEWER_PASS


# ── #2 Broken Access Control: viewer é somente-leitura no inventário ──────────

WRITE_PATHS = ["/spools/new", "/filaments/new", "/weigh", "/spool-models/new"]
READ_PATHS = ["/spools", "/filaments", "/spool-models", "/reports/stats"]


@pytest.mark.parametrize("path", WRITE_PATHS)
def test_viewer_cannot_reach_write_endpoints(viewer_client, path):
    # Tanto o GET do formulário quanto o POST de gravação são barrados no servidor.
    assert viewer_client.get(path).status_code == 403
    assert viewer_client.post(path, data={}).status_code == 403


@pytest.mark.parametrize("path", READ_PATHS)
def test_viewer_can_read(viewer_client, path):
    assert viewer_client.get(path).status_code == 200


def test_viewer_renders_pages_with_write_buttons_hidden(viewer_client, auth_client, db):
    """As páginas que ganharam guardas {% if can_write %} renderizam p/ viewer sem erro
    de template, e os botões/forms de escrita não aparecem."""
    # admin popula um filamento + spool p/ as páginas de detalhe terem conteúdo
    auth_client.post("/filaments/new", data={
        "brand": "Acme", "material": "PLA", "family": "PLA", "color_hex": "#fff",
        "diameter_mm": "1.75",
    })
    fid = db.list_filaments()[0]["id"]
    auth_client.post("/spools/new", data={
        "filament_id": str(fid), "nominal_weight_g": "1000",
    })
    sid = db.list_spools()[0]["id"]

    for path in ["/", "/reports/low-stock", "/filaments", "/spools",
                 f"/filaments/{fid}", f"/spools/{sid}"]:
        resp = viewer_client.get(path)
        assert resp.status_code == 200, path
        html = resp.get_data(as_text=True)
        # nenhum link/form de escrita exposto ao viewer
        assert "/spools/new" not in html, path
        assert "/filaments/new" not in html, path
        assert f"/filaments/{fid}/edit" not in html, path


@pytest.mark.parametrize("path", WRITE_PATHS)
def test_admin_can_write(auth_client, path):
    assert auth_client.get(path).status_code == 200


def test_viewer_cannot_mutate_existing_objects(viewer_client, auth_client, db):
    """POST nas rotas de edição/exclusão de objetos existentes também é 403 p/ viewer."""
    # admin cria um filamento p/ existir um id real
    auth_client.post("/filaments/new", data={
        "brand": "Acme", "material": "PLA", "family": "PLA", "color_hex": "#fff",
        "diameter_mm": "1.75",
    })
    fid = db.list_filaments()[0]["id"]
    for path in (f"/filaments/{fid}/edit", f"/filaments/{fid}/delete",
                 f"/filaments/{fid}/duplicate"):
        assert viewer_client.post(path, data={}).status_code == 403


def test_unauthenticated_write_redirects_to_login(client):
    """Sem sessão, a rota de escrita manda pro login (não 403/500)."""
    resp = client.get("/spools/new")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


# ── #3 Revogação de sessão (CWE-613) ─────────────────────────────────────────

def test_logout_rotates_session_token(auth_client, db):
    uid = db.get_user_by_username(ADMIN_USER)["id"]
    before = db.get_session_token(uid)
    assert before  # login semeou um token
    auth_client.post("/logout")
    assert db.get_session_token(uid) != before


def test_cookie_invalid_after_logout(app_module, db):
    """Replay do cookie de sessão após logout: o token rotacionado o invalida."""
    app = app_module.app
    a = app.test_client()
    a.post("/login", data={"username": ADMIN_USER, "password": ADMIN_PASS})
    captured = a.get_cookie("session").value

    # cliente novo com o cookie capturado: válido ANTES do logout
    b = app.test_client()
    b.set_cookie("session", captured, domain="localhost")
    assert b.get("/admin/users").status_code == 200

    a.post("/logout")  # rotaciona o token server-side

    b.set_cookie("session", captured, domain="localhost")
    resp = b.get("/admin/users")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_password_change_revokes_other_sessions(app_module, db):
    """Trocar a senha invalida as DEMAIS sessões (mantém a que trocou)."""
    app = app_module.app
    a = app.test_client()
    a.post("/login", data={"username": ADMIN_USER, "password": ADMIN_PASS})
    captured = a.get_cookie("session").value

    other = app.test_client()
    other.set_cookie("session", captured, domain="localhost")
    assert other.get("/admin/users").status_code == 200

    new = "senha-nova-forte-1"
    a.post("/account/password", data={
        "current_password": ADMIN_PASS, "new_password": new, "confirm_password": new,
    })
    # a sessão que trocou continua válida…
    assert a.get("/admin/users").status_code == 200
    # …a outra cai
    other.set_cookie("session", captured, domain="localhost")
    assert other.get("/admin/users").status_code == 302


def test_admin_reset_revokes_target_sessions(app_module, db):
    """Admin resetando a senha de OUTRO usuário derruba a sessão ativa do alvo."""
    app = app_module.app
    from werkzeug.security import generate_password_hash
    db.create_user("alvo", generate_password_hash("senha-antiga-1"), role="viewer",
                   must_change=False)
    victim = app.test_client()
    victim.post("/login", data={"username": "alvo", "password": "senha-antiga-1"})
    assert victim.get("/spools").status_code == 200

    admin = app.test_client()
    admin.post("/login", data={"username": ADMIN_USER, "password": ADMIN_PASS})
    uid = db.get_user_by_username("alvo")["id"]
    admin.post(f"/admin/users/{uid}/password", data={"password": "reset-temporaria"})

    assert victim.get("/spools").status_code == 302  # sessão do alvo revogada


# ── #4 Chave de API não embutida no DOM (CWE-200) ────────────────────────────

def test_api_key_not_in_html(auth_client, db):
    html = auth_client.get("/admin/integrations").get_data(as_text=True)
    full = db.get_api_key("homeassistant")["key"]
    assert "data-key=" not in html
    assert full not in html


def test_reveal_endpoint_returns_key_for_admin(auth_client, db):
    resp = auth_client.get("/admin/integrations/homeassistant/key")
    assert resp.status_code == 200
    assert resp.get_json()["key"] == db.get_api_key("homeassistant")["key"]
    assert resp.headers.get("Cache-Control") == "no-store"


def test_reveal_endpoint_forbidden_for_viewer(viewer_client):
    assert viewer_client.get("/admin/integrations/homeassistant/key").status_code == 403


def test_reveal_endpoint_unknown_integration_404(auth_client):
    assert auth_client.get("/admin/integrations/scale/key").status_code == 404


# ── #5 HTTPException não vira 500 ────────────────────────────────────────────

def test_logout_get_not_500(client):
    # /logout é POST-only: um GET deve dar 405, nunca estourar em 500.
    assert client.get("/logout").status_code == 405


def test_spool_models_post_not_500(client):
    # /spool-models é GET-only: POST → 405 (e não 500 via Exception handler).
    assert client.post("/spool-models", data={}).status_code == 405


# ── #9 security.txt (RFC 9116) ───────────────────────────────────────────────

def test_security_txt_served(client):
    resp = client.get("/.well-known/security.txt")
    assert resp.status_code == 200
    assert resp.mimetype == "text/plain"
    assert "Contact:" in resp.get_data(as_text=True)
