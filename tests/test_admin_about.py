"""Página Admin -> Sobre (/admin/about): versão, licença MIT, links de código-fonte
e suporte. Cobre a T-848 (LICENSE + página institucional)."""


def test_admin_about_ok_for_admin(auth_client):
    resp = auth_client.get("/admin/about")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "iscarelli@gmail.com" in html
    assert "https://github.com/iscarelli/spool-control" in html


def test_admin_about_shows_current_version(auth_client, app_module):
    resp = auth_client.get("/admin/about")
    html = resp.get_data(as_text=True)
    assert app_module.current_version() in html


def test_admin_about_requires_admin(viewer_client):
    assert viewer_client.get("/admin/about").status_code == 403


def test_admin_about_requires_login(client):
    resp = client.get("/admin/about")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]
