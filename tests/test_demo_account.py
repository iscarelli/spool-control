"""Modo demo: ações de conta bloqueadas e não oferecidas na UI.

No DEMO_MODE o admin não pode trocar a senha nem ativar 2FA — o backend bloqueia
(@demo_blocked) e o menu do usuário não mostra esses links (viram beco sem saída).
"""
from werkzeug.security import check_password_hash


def test_demo_mode_blocks_password_change_get(auth_client, app_module, monkeypatch):
    monkeypatch.setattr(app_module, "DEMO_MODE", True)
    resp = auth_client.get("/account/password")
    assert resp.status_code == 302  # demo_blocked redireciona


def test_demo_mode_blocks_password_change_post(auth_client, app_module, db, monkeypatch):
    monkeypatch.setattr(app_module, "DEMO_MODE", True)
    before = db.get_user_by_username("admin")["password_hash"]
    resp = auth_client.post("/account/password", data={
        "current_password": "admin-test-pass",
        "new_password": "nova-senha-123",
        "confirm_password": "nova-senha-123",
    })
    assert resp.status_code == 302  # bloqueado, não processa
    after = db.get_user_by_username("admin")["password_hash"]
    assert after == before  # senha intacta
    assert not check_password_hash(after, "nova-senha-123")


def test_demo_mode_hides_account_menu_links(auth_client, app_module, monkeypatch):
    monkeypatch.setattr(app_module, "DEMO_MODE", True)
    html = auth_client.get("/").get_data(as_text=True)
    assert "/account/password" not in html
    assert "/account/2fa" not in html


def test_non_demo_shows_account_menu_links(auth_client):
    html = auth_client.get("/").get_data(as_text=True)
    assert "/account/password" in html
    assert "/account/2fa" in html
