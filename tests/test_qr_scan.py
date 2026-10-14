"""In-page QR scanner: navbar button + modal markup, static assets, CSP-safe."""
import re
import shutil
import subprocess

import pytest

from tests.test_no_inline_handlers import INLINE_HANDLER


def test_scan_button_and_modal_for_logged_in_user(auth_client):
    html = auth_client.get("/").get_data(as_text=True)
    assert 'id="qrScanBtn"' in html
    assert "bi-qr-code-scan" in html
    assert 'data-bs-target="#qrScanModal"' in html
    assert 'id="qrScanModal"' in html
    assert 'id="qrScanVideo"' in html
    assert "playsinline" in html
    for attr in ("data-jsqr-src", "data-msg-unrecognized", "data-msg-no-camera",
                 "data-msg-denied", "data-msg-hint"):
        assert attr in html, attr
    assert "vendor/jsQR.js" in html
    assert "qr-scan.js" in html
    # The button sits in the bar itself, not inside the collapsed menu.
    nav = html.split('id="navMenu"')[0]
    assert 'id="qrScanBtn"' in nav
    assert INLINE_HANDLER.search(html) is None


def test_scan_absent_for_anonymous(client):
    html = client.get("/login").get_data(as_text=True)
    assert "qrScanBtn" not in html
    assert "qrScanModal" not in html
    assert "qr-scan.js" not in html


def test_scan_assets_served(auth_client):
    for url in ("/static/qr-scan.js", "/static/vendor/jsQR.js",
                "/static/vendor/jsQR.LICENSE.txt"):
        assert auth_client.get(url).status_code == 200, url


def test_no_permissions_policy_blocking_camera(auth_client):
    resp = auth_client.get("/")
    assert "camera" not in resp.headers.get("Permissions-Policy", "")


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_parse_spool_id_pure_function():
    script = (
        "const q=require('./static/qr-scan.js');"
        "console.log(JSON.stringify(["
        "q.parseSpoolId('https://other.example/spools/12'),"
        "q.parseSpoolId('/spools/12/'),"
        "q.parseSpoolId('https://x/filaments/3'),"
        "q.parseSpoolId('https://x/spools/12/weigh'),"
        "q.parseSpoolId('hello'),"
        "q.destination('12','weigh'),q.destination('12','detail')]))"
    )
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == '["12","12",null,null,null,"/spools/12/weigh","/spools/12"]'
