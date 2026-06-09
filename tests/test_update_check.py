"""Checagem de versão: detecção por redirect do site (sem REST API), badge cache-only
(não toca a rede fora da página de update) e remoção do endpoint órfão."""
import pytest
from conftest import ADMIN_USER, ADMIN_PASS


class _FakeResp:
    """Resposta mínima com header Location, usável como context manager."""
    def __init__(self, location):
        self.headers = {"Location": location}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


# ── Detecção por redirect (sem REST API) ──────────────────────────────────────

def test_tag_parsed_from_redirect_location(app_module, monkeypatch):
    monkeypatch.setattr(
        app_module._redirect_reader, "open",
        lambda req, timeout=4: _FakeResp(
            "https://github.com/iscarelli/spool-control/releases/tag/v1.31.0"),
    )
    assert app_module._latest_release_tag_via_web() == "v1.31.0"


def test_check_latest_release_populates_cache_via_web(app_module, monkeypatch):
    monkeypatch.setattr(app_module, "_latest_release_tag_via_web", lambda: "v9.9.9")
    assert app_module.check_latest_release() == "9.9.9"
    assert app_module._release_cache["ok"] is True


# ── Badge cache-only: NUNCA toca a rede fora da página de update ───────────────

def test_badge_never_hits_network(app_module, monkeypatch):
    client = app_module.app.test_client()
    client.post("/login", data={"username": ADMIN_USER, "password": ADMIN_PASS})
    calls = {"n": 0}

    def boom():
        calls["n"] += 1
        raise AssertionError("o badge não pode tocar a rede")

    monkeypatch.setattr(app_module, "_latest_release_tag_via_web", boom)
    # Páginas comuns renderizam o badge (inject_globals via base.html) — sem fetch.
    for path in ("/admin/users", "/admin/brands", "/filaments"):
        assert client.get(path).status_code == 200
    assert calls["n"] == 0


def test_cached_latest_tag_is_offline(app_module, monkeypatch):
    monkeypatch.setattr(app_module, "_latest_release_tag_via_web",
                        lambda: (_ for _ in ()).throw(AssertionError("rede!")))
    assert app_module.cached_latest_tag() is None      # cache frio, sem rede


# ── A página de update É quem consulta ────────────────────────────────────────

def test_update_page_checks_via_web(app_module, monkeypatch):
    client = app_module.app.test_client()
    client.post("/login", data={"username": ADMIN_USER, "password": ADMIN_PASS})
    monkeypatch.setattr(app_module, "_latest_release_tag_via_web", lambda: "v9.9.9")
    monkeypatch.setattr(app_module, "latest_release_notes", lambda: "")
    resp = client.get("/admin/update")
    assert resp.status_code == 200
    assert app_module._release_cache["tag"] == "9.9.9"


# ── Status do update (lido pela /admin/update p/ mostrar falha) ───────────────

def test_update_status_idle_when_no_file(app_module):
    import database as db
    (db.DB_PATH.parent / ".update-status").unlink(missing_ok=True)
    client = app_module.app.test_client()
    client.post("/login", data={"username": ADMIN_USER, "password": ADMIN_PASS})
    r = client.get("/admin/update/status")
    assert r.status_code == 200
    assert r.get_json()["state"] == "idle"


def test_update_status_reports_failure(app_module):
    import database as db
    (db.DB_PATH.parent / ".update-status").write_text(
        '{"state":"failed","message":"pyotp indisponivel","ts":"2026-06-09T00:00:00Z"}',
        encoding="utf-8",
    )
    client = app_module.app.test_client()
    client.post("/login", data={"username": ADMIN_USER, "password": ADMIN_PASS})
    data = client.get("/admin/update/status").get_json()
    assert data["state"] == "failed"
    assert "pyotp" in data["message"]
    (db.DB_PATH.parent / ".update-status").unlink(missing_ok=True)


def test_update_status_requires_admin(app_module):
    client = app_module.app.test_client()
    r = client.get("/admin/update/status")
    assert r.status_code in (302, 401, 403)   # sem login → barrado
