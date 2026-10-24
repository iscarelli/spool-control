"""PWA service worker: iOS only treats the home-screen app as installed (and remembers the
camera permission) when a service worker is registered."""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


def test_sw_served_with_scope_and_no_immutable(client):
    r = client.get("/static/sw.js")
    assert r.status_code == 200
    assert "javascript" in r.headers["Content-Type"]
    assert r.headers["Service-Worker-Allowed"] == "/"
    assert "immutable" not in r.headers.get("Cache-Control", "")
    assert r.headers["Cache-Control"] == "no-cache"


def test_sw_skips_non_get():
    assert 'event.request.method !== "GET"' in _read("static/sw.js")


def test_spool_js_registers_worker_with_fixed_path():
    assert "serviceWorker.register('/static/sw.js'" in _read("static/spool.js")
