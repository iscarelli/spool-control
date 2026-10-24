"""Scanner stays on the page: in-modal result (summary.json), in-modal weighing
(weigh.json) and a single camera stream per page load."""
import pytest

from tests.test_no_inline_handlers import INLINE_HANDLER


# ── Static behaviour of the script / modal ───────────────────────────────────

def test_scan_js_never_navigates_and_requests_camera_once():
    js = open("static/qr-scan.js", encoding="utf-8").read()
    assert "location.assign" not in js and "location.href" not in js
    assert js.count("getUserMedia(") == 1            # the only request, inside acquireStream()
    assert "audio: false" in js and "facingMode: 'environment'" in js
    # Closing the modal must not stop the tracks; only pagehide releases the stream.
    assert "hidden.bs.modal" in js and "pagehide', releaseStream" in js
    assert js.count(".stop()") == 1


def test_scan_modal_has_result_panel_and_typed_fallback(auth_client):
    html = auth_client.get("/").get_data(as_text=True)
    for el in ('id="qrScanResult"', 'id="qrWeighForm"', 'id="qrScanManual"',
               'id="qrScanNext"', 'id="qrScanOpen"', 'inputmode="numeric"'):
        assert el in html, el
    assert INLINE_HANDLER.search(html) is None


# ── GET /spools/<id>/summary.json ────────────────────────────────────────────

def _mk(db, tare=200.0, nominal=1000.0):
    fid = db.create_filament("MarcaQR", "PETG", "Basic", "#ff8800")
    return db.create_spool(filament_id=fid, spool_model_id=None, custom_tare_g=tare,
                           nominal_weight_g=nominal, location="", purchase_date="",
                           purchase_price=None, notes="")


def test_summary_requires_login(client, db):
    sid = _mk(db)
    assert client.get(f"/spools/{sid}/summary.json").status_code == 401


def test_summary_404_json(auth_client):
    r = auth_client.get("/spools/9999/summary.json")
    assert r.status_code == 404 and r.get_json()["ok"] is False


def test_summary_fields_unweighed_then_weighed(auth_client, db):
    sid = _mk(db)
    d = auth_client.get(f"/spools/{sid}/summary.json").get_json()
    assert d["ok"] and d["id"] == sid and d["code"] == f"SP-{sid:04d}"
    assert (d["material"], d["brand"], d["family"]) == ("PETG", "MarcaQR", "Basic")
    assert d["color_hex"] == "#ff8800"
    assert d["weighed"] is False and d["remaining_g"] == 1000 and d["pct"] == 100
    assert d["last_weighed_at"] == ""
    db.add_weight_reading(sid, 700, 200)      # net 500
    d = auth_client.get(f"/spools/{sid}/summary.json").get_json()
    assert d["weighed"] is True and d["remaining_g"] == 500 and d["pct"] == 50
    assert d["last_weighed_at"]


def test_summary_readable_by_viewer(viewer_client, db):
    sid = _mk(db)
    assert viewer_client.get(f"/spools/{sid}/summary.json").status_code == 200


# ── POST /spools/<id>/weigh.json ─────────────────────────────────────────────

def test_weigh_json_success_writes_reading(auth_client, db):
    sid = _mk(db)
    r = auth_client.post(f"/spools/{sid}/weigh.json", json={"gross_weight_g": 650})
    assert r.status_code == 200
    d = r.get_json()
    assert d["ok"] and d["remaining_g"] == 450 and d["weighed"] is True
    rows = db.list_weight_readings(spool_id=sid)
    assert len(rows) == 1 and rows[0]["gross_weight_g"] == 650 and rows[0]["tare_weight_g"] == 200
    assert rows[0]["recorded_by"] == "admin"


def test_weigh_json_matches_form_route(auth_client, db):
    """Same validation and same stored row as the HTML form route."""
    a, b = _mk(db), _mk(db)
    auth_client.post(f"/spools/{a}/weigh", data={"gross_weight_g": "650"})
    auth_client.post(f"/spools/{b}/weigh.json", json={"gross_weight_g": 650})
    ra, rb = db.list_weight_readings(spool_id=a)[0], db.list_weight_readings(spool_id=b)[0]
    for k in ("gross_weight_g", "tare_weight_g", "net_weight_g", "recorded_by", "notes"):
        assert ra[k] == rb[k], k


@pytest.mark.parametrize("payload", [{}, {"gross_weight_g": "abc"}, {"gross_weight_g": None},
                                     {"gross_weight_g": "nan"}, {"gross_weight_g": "inf"}])
def test_weigh_json_invalid_value(auth_client, db, payload):
    sid = _mk(db)
    r = auth_client.post(f"/spools/{sid}/weigh.json", json=payload)
    assert r.status_code == 400 and r.get_json()["ok"] is False
    assert db.list_weight_readings(spool_id=sid) == []


def test_weigh_json_below_tare_rejected(auth_client, db):
    sid = _mk(db)
    r = auth_client.post(f"/spools/{sid}/weigh.json", json={"gross_weight_g": 100})
    assert r.status_code == 422 and r.get_json()["error"]
    assert db.list_weight_readings(spool_id=sid) == []


def test_weigh_json_404(auth_client):
    assert auth_client.post("/spools/9999/weigh.json", json={"gross_weight_g": 500}).status_code == 404


def test_weigh_json_forbidden_for_viewer(viewer_client, db):
    sid = _mk(db)
    r = viewer_client.post(f"/spools/{sid}/weigh.json", json={"gross_weight_g": 650})
    assert r.status_code == 403
    assert db.list_weight_readings(spool_id=sid) == []


def test_weigh_json_requires_login(client, db):
    sid = _mk(db)
    assert client.post(f"/spools/{sid}/weigh.json", json={"gross_weight_g": 650}).status_code == 401
