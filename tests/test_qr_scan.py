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


def test_scanner_never_navigates_between_scans():
    """iPhone keeps the camera grant only for the page load: the scan handler must not
    navigate (WebKit bug 215884). Navigation is only the explicit 'Abrir rolo' link."""
    src = open("static/qr-scan.js", encoding="utf-8").read()
    assert "location.assign" not in src
    assert "location.href" not in src
    assert src.count("getUserMedia(") == 1


def test_modal_has_result_panel(auth_client):
    html = auth_client.get("/").get_data(as_text=True)
    for el in ("qrScanResult", "qrWeighForm", "qrNextBtn", "qrOpenBtn", 'inputmode="numeric"'):
        assert el in html, el


def _spool(db, tare=200.0):
    fid = db.create_filament(brand="Acme", material="PLA", family="Basic",
                             color_hex="#ff0000", color_name="Red")
    return db.create_spool(filament_id=fid, spool_model_id=None, custom_tare_g=tare,
                           nominal_weight_g=1000.0, location="", purchase_date="",
                           purchase_price=None, notes="")


def test_summary_requires_login(client, db):
    sid = _spool(db)
    resp = client.get(f"/spools/{sid}/summary.json")
    assert resp.status_code in (301, 302, 401)


def test_summary_404_json(auth_client):
    resp = auth_client.get("/spools/9999/summary.json")
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "not_found"


def test_summary_fields(auth_client, db):
    sid = _spool(db)
    d = auth_client.get(f"/spools/{sid}/summary.json").get_json()
    assert d["id"] == sid and d["code"] == f"SP-{sid:04d}"
    assert (d["material"], d["brand"], d["family"], d["color_name"]) == ("PLA", "Acme", "Basic", "Red")
    assert d["color_hex"] == "#ff0000"
    assert d["remaining_g"] is None and d["last_weighed"] == ""
    assert d["detail_url"] == f"/spools/{sid}"
    db.add_weight_reading(sid, 700.0, 200.0)
    d = auth_client.get(f"/spools/{sid}/summary.json").get_json()
    assert d["remaining_g"] == 500 and d["pct"] == 50 and d["last_weighed"]


def test_weigh_json_success_updates_reading(auth_client, db):
    sid = _spool(db)
    resp = auth_client.post(f"/spools/{sid}/weigh.json", json={"gross_weight_g": 800})
    assert resp.status_code == 200
    j = resp.get_json()
    assert j["ok"] and j["summary"]["remaining_g"] == 600
    assert db.get_spool(sid)["current_net_g"] == 600


@pytest.mark.parametrize("body", [{}, {"gross_weight_g": "abc"}, {"gross_weight_g": None},
                                  {"gross_weight_g": 50}])
def test_weigh_json_validation_errors(auth_client, db, body):
    sid = _spool(db)
    resp = auth_client.post(f"/spools/{sid}/weigh.json", json=body)
    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False
    assert db.get_spool(sid)["current_net_g"] is None


def test_weigh_json_404(auth_client):
    assert auth_client.post("/spools/9999/weigh.json", json={"gross_weight_g": 500}).status_code == 404


def test_weigh_json_forbidden_for_viewer(viewer_client, db):
    sid = _spool(db)
    resp = viewer_client.post(f"/spools/{sid}/weigh.json", json={"gross_weight_g": 800})
    assert resp.status_code == 403
    assert db.get_spool(sid)["current_net_g"] is None
    assert viewer_client.get(f"/spools/{sid}/summary.json").status_code == 200
