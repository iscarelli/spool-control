"""Spoolman-compatible API for SpoolmanScale (/api/v1, routes/spoolman_api.py).

Numbers in the docstrings refer to the checklist in section 9 of the contract
(inventory/spec.md of github.com/SpoolmanScale/ssi).
"""
import base64
import json

import pytest

UID = "04:A1:B2:C3:D4:E5:F6"


def _spool(db, tare=196.0, nominal=1000.0, location="Shelf A", brand="Bambu Lab",
           family="Matte", color_name="Black", color="#1a1a1a"):
    fid = db.create_filament(brand, "PLA", family, color, color_name=color_name)
    return db.create_spool(filament_id=fid, spool_model_id=None, custom_tare_g=tare,
                           nominal_weight_g=nominal, location=location, purchase_date="",
                           purchase_price=None, notes="")


@pytest.fixture()
def key(db):
    return db.get_api_key("spoolmanscale")["key"]


@pytest.fixture()
def api(client, key):
    """Tiny helper: authenticated calls under /api/v1."""
    class Api:
        h = {"X-API-Key": key}

        def get(self, path, **kw):
            return client.get("/api/v1" + path, headers=self.h, **kw)

        def post(self, path, body=None):
            return client.post("/api/v1" + path, json=body, headers=self.h)

        def patch(self, path, body):
            return client.patch("/api/v1" + path, json=body, headers=self.h)

        def put(self, path, body):
            return client.put("/api/v1" + path, json=body, headers=self.h)

        def delete(self, path):
            return client.delete("/api/v1" + path, headers=self.h)
    return Api()


# ── Auth and transport (checklist 1, 10, 11) ────────────────────────────────

def test_key_is_seeded_with_write_scope(db):
    row = db.get_api_key("spoolmanscale")
    assert row and row["scope"] == "write" and row["enabled"] == 1


def test_health_needs_no_key(client):
    assert client.get("/api/v1/health").status_code == 200


def test_info_reports_version(api):
    r = api.get("/info")
    assert r.status_code == 200 and r.get_json()["version"]


def test_no_key_is_401_on_every_route_except_health(client, db):
    sid = _spool(db)
    for method, path in [
        ("get", "/api/v1/info"), ("get", "/api/v1/spool"), ("get", f"/api/v1/spool/{sid}"),
        ("patch", f"/api/v1/spool/{sid}"), ("put", f"/api/v1/spool/{sid}/measure"),
        ("get", "/api/v1/field/spool"), ("get", "/api/v1/tag/reader"),
        ("post", "/api/v1/tag/scan"), ("post", f"/api/v1/spool/{sid}/tag"),
        ("delete", f"/api/v1/spool/{sid}/tag/AA"), ("get", "/api/v1/location"),
        ("get", "/api/v1/nonexistent"),
    ]:
        r = getattr(client, method)(path)
        assert r.status_code == 401, (method, path)
        assert r.is_json


def test_wrong_key_is_401(client):
    assert client.get("/api/v1/spool", headers={"X-API-Key": "nope"}).status_code == 401


def test_other_integrations_keys_do_not_open_v1(client, db):
    for slug in ("scale", "homeassistant"):
        k = db.get_api_key(slug)["key"]
        assert client.get("/api/v1/spool", headers={"X-API-Key": k}).status_code == 401


def test_disabled_key_is_401(client, db, key):
    db.set_api_key_enabled("spoolmanscale", False)
    assert client.get("/api/v1/spool", headers={"X-API-Key": key}).status_code == 401


def test_three_auth_forms(client, db, key):
    _spool(db)
    assert client.get("/api/v1/spool", headers={"X-API-Key": key}).status_code == 200
    assert client.get("/api/v1/spool",
                      headers={"Authorization": f"Bearer {key}"}).status_code == 200
    basic = base64.b64encode(f"anything:{key}".encode()).decode()
    assert client.get("/api/v1/spool",
                      headers={"Authorization": f"Basic {basic}"}).status_code == 200
    bad = base64.b64encode(f"{key}:wrong".encode()).decode()   # key as USER is not accepted
    assert client.get("/api/v1/spool", headers={"Authorization": f"Basic {bad}"}).status_code == 401


def test_writes_work_without_csrf_token_or_cookie(app_module, db, key):
    """CSRF is ON here (the shared fixtures turn it off); the scale sends no token."""
    app_module.app.config["WTF_CSRF_ENABLED"] = True
    sid = _spool(db)
    c = app_module.app.test_client()
    r = c.patch(f"/api/v1/spool/{sid}", json={"location": "X"}, headers={"X-API-Key": key})
    assert r.status_code == 200
    assert not r.headers.get_all("Set-Cookie")


def test_no_redirects_under_v1(client, db, key):
    sid = _spool(db)
    h = {"X-API-Key": key}
    for path in ["/api/v1/spool", "/api/v1/spool/", f"/api/v1/spool/{sid}", "/api/v1/info",
                 "/api/v1/location", "/api/v1/field/spool", "/api/v1/tag/reader",
                 "/api/v1/health", "/api/v1/"]:
        assert client.get(path, headers=h).status_code < 300 or \
            client.get(path, headers=h).status_code >= 400, path


# ── Spool list and object (2, 3, 4) ─────────────────────────────────────────

def test_spool_object_shape(api, db):
    sid = _spool(db)
    s = api.get(f"/spool/{sid}").get_json()
    assert s["id"] == sid and s["archived"] is False
    assert s["extra"] == {} and s["tags"] == []
    assert s["initial_weight"] == 1000 and s["spool_weight"] == 196
    assert "remaining_weight" not in s            # never weighed: not faked
    assert s["location"] == "Shelf A"
    assert s["registered"].endswith("Z")
    f = s["filament"]
    assert isinstance(f["id"], int)
    assert f["name"] == "Matte Black" and f["material"] == "PLA"
    assert f["color_hex"] == "1a1a1a"             # no '#'
    assert f["vendor"]["name"] == "Bambu Lab" and isinstance(f["vendor"]["id"], int)


def test_dual_color_exposes_multi_color_hexes(api, db):
    fid = db.create_filament("X", "PLA", "Silk", "#ff0000", color_hex2="#00ff00")
    sid = db.create_spool(fid, None, None, 1000, "", "", None, "")
    assert api.get(f"/spool/{sid}").get_json()["filament"]["multi_color_hexes"] == "ff0000,00ff00"


def test_spool_model_tare_is_the_reported_tare(api, db):
    db.create_spool_model("Plain", 220.0)
    mid = db.list_spool_models()[0]["id"]
    fid = db.create_filament("X", "PLA", "Basic", "#112233")
    sid = db.create_spool(fid, mid, None, 1000, "", "", None, "")
    assert api.get(f"/spool/{sid}").get_json()["spool_weight"] == 220


def test_list_active_vs_all(api, db):
    a, b = _spool(db), _spool(db)
    db.deactivate_spool(b)
    active = [s["id"] for s in api.get("/spool?allow_archived=false").get_json()]
    everything = api.get("/spool?allow_archived=true").get_json()
    assert active == [a]
    assert sorted(s["id"] for s in everything) == [a, b]
    assert {s["id"]: s["archived"] for s in everything} == {a: False, b: True}
    assert [s["id"] for s in api.get("/spool").get_json()] == [a]   # default = active only


def test_get_unknown_spool_404_archived_ok(api, db):
    assert api.get("/spool/999").status_code == 404
    sid = _spool(db)
    db.deactivate_spool(sid)
    assert api.get(f"/spool/{sid}").status_code == 200


def test_list_stamp_limit_sort_total_count(api, db):
    ids = [_spool(db) for _ in range(3)]
    r = api.get("/spool?allow_archived=false&limit=1&sort=id:desc")
    assert [s["id"] for s in r.get_json()] == [ids[-1]]
    assert r.headers["x-total-count"] == "3"
    r = api.get("/spool?allow_archived=false&limit=1")
    assert len(r.get_json()) == 1 and r.headers["x-total-count"] == "3"
    r = api.get("/spool?limit=1&offset=1")
    assert [s["id"] for s in r.get_json()] == [ids[1]]


def test_list_has_no_default_paging(api, db):
    for _ in range(130):
        _spool(db)
    assert len(api.get("/spool?allow_archived=true").get_json()) == 130


# ── Writing (5, 6) ───────────────────────────────────────────────────────────

def test_patch_remaining_reads_back_and_uses_effective_tare(api, db):
    sid = _spool(db, tare=196.0)
    r = api.patch(f"/spool/{sid}", {"remaining_weight": 500})
    assert r.status_code == 200 and r.get_json()["remaining_weight"] == 500
    assert api.get(f"/spool/{sid}").get_json()["remaining_weight"] == 500
    row = db.get_spool(sid)
    assert row["current_gross_g"] == 696 and row["current_net_g"] == 500
    reading = db.list_weight_readings(spool_id=sid)[0]
    assert reading["recorded_by"] == "SpoolmanScale"


def test_patch_decimal_remaining_reads_back(api, db):
    sid = _spool(db, tare=196.4)
    assert api.patch(f"/spool/{sid}", {"remaining_weight": 612.3}).get_json()["remaining_weight"] == 612.3


def test_patch_remaining_above_initial_makes_it_full(api, db):
    sid = _spool(db, nominal=1000)
    s = api.patch(f"/spool/{sid}", {"remaining_weight": 1250}).get_json()
    assert s["remaining_weight"] == 1250 and s["initial_weight"] == 1250


def test_patch_initial_and_remaining_together(api, db):
    sid = _spool(db)
    s = api.patch(f"/spool/{sid}", {"initial_weight": 750, "remaining_weight": 750}).get_json()
    assert s["initial_weight"] == 750 and s["remaining_weight"] == 750


def test_patch_spool_weight_then_remaining_uses_new_tare(api, db):
    sid = _spool(db, tare=196)
    s = api.patch(f"/spool/{sid}", {"spool_weight": 140, "remaining_weight": 600}).get_json()
    assert s["spool_weight"] == 140 and s["remaining_weight"] == 600
    assert db.get_spool(sid)["current_gross_g"] == 740


def test_patch_spool_weight_null_falls_back_to_model_tare(api, db):
    db.create_spool_model("Plain", 220.0)
    mid = db.list_spool_models()[0]["id"]
    fid = db.create_filament("X", "PLA", "Basic", "#112233")
    sid = db.create_spool(fid, mid, 150, 1000, "", "", None, "")
    assert api.get(f"/spool/{sid}").get_json()["spool_weight"] == 150
    assert api.patch(f"/spool/{sid}", {"spool_weight": None}).get_json()["spool_weight"] == 220


def test_patch_location_null_clears(api, db):
    sid = _spool(db, location="Dry box")
    assert api.patch(f"/spool/{sid}", {"location": "Shelf B"}).get_json()["location"] == "Shelf B"
    r = api.patch(f"/spool/{sid}", {"location": None})
    assert r.status_code == 200
    assert "location" not in api.get(f"/spool/{sid}").get_json()
    assert db.get_spool(sid)["location"] == ""


def test_patch_absent_keys_leave_fields_alone(api, db):
    sid = _spool(db, location="Keep")
    api.patch(f"/spool/{sid}", {"remaining_weight": 400})
    s = api.get(f"/spool/{sid}").get_json()
    assert s["location"] == "Keep" and s["spool_weight"] == 196


def test_patch_last_used_date_only_is_midnight_utc(api, db):
    sid = _spool(db)
    s = api.patch(f"/spool/{sid}", {"last_used": "2026-10-01"}).get_json()
    assert s["last_used"] == "2026-10-01T00:00:00Z"
    s = api.patch(f"/spool/{sid}", {"last_used": "2026-10-02T12:34:56.789Z"}).get_json()
    assert s["last_used"] == "2026-10-02T12:34:56Z"


def test_patch_archive_with_zero_finishes_like_the_ui(api, db):
    sid = _spool(db)
    s = api.patch(f"/spool/{sid}", {"remaining_weight": 0.0, "archived": True}).get_json()
    assert s["archived"] is True and s["remaining_weight"] == 0
    row = db.get_spool(sid)
    assert row["active"] == 0 and row["finished_at"]


def test_patch_unarchive_reactivates(api, db):
    sid = _spool(db)
    db.deactivate_spool(sid)
    s = api.patch(f"/spool/{sid}", {"archived": False, "remaining_weight": 540}).get_json()
    assert s["archived"] is False and s["remaining_weight"] == 540
    assert db.get_spool(sid)["finished_at"] == ""


def test_patch_validation_is_all_or_nothing(api, db):
    sid = _spool(db, location="Keep")
    assert api.patch(f"/spool/{sid}", {"location": "New", "remaining_weight": -5}).status_code == 422
    assert api.patch(f"/spool/{sid}", {"location": "New", "last_used": "garbage"}).status_code == 422
    assert api.get(f"/spool/{sid}").get_json()["location"] == "Keep"
    assert api.patch("/spool/999", {"location": "x"}).status_code == 404


def test_patch_extra_merges_per_key_and_empty_string_clears(api, db):
    sid = _spool(db)
    api.patch(f"/spool/{sid}", {"extra": {"last_dried": '"2026-10-01T12:34:56.000Z"'}})
    s = api.patch(f"/spool/{sid}", {"extra": {"note_x": '"hi"'}}).get_json()
    assert s["extra"] == {"last_dried": '"2026-10-01T12:34:56.000Z"', "note_x": '"hi"'}
    s = api.patch(f"/spool/{sid}", {"extra": {"last_dried": '""'}}).get_json()
    assert s["extra"] == {"note_x": '"hi"'}
    assert api.patch(f"/spool/{sid}", {"extra": {"Bad Key": '"x"'}}).status_code == 400


# ── Measure (12) ─────────────────────────────────────────────────────────────

def test_measure_subtracts_reported_tare_and_sets_last_used(api, db):
    sid = _spool(db, tare=196)
    r = api.put(f"/spool/{sid}/measure", {"weight": 1196})
    assert r.status_code == 200
    s = r.get_json()
    assert s["remaining_weight"] == 1000 and s["spool_weight"] == 196 and s["last_used"]
    assert api.get(f"/spool/{sid}").get_json()["remaining_weight"] == 1000


def test_measure_above_initial_raises_initial(api, db):
    sid = _spool(db, tare=196, nominal=1000)
    s = api.put(f"/spool/{sid}/measure", {"weight": 1396}).get_json()
    assert s["remaining_weight"] == 1200 and s["initial_weight"] == 1200


def test_measure_below_tare_is_422_and_stores_nothing(api, db):
    sid = _spool(db, tare=196)
    assert api.put(f"/spool/{sid}/measure", {"weight": 100}).status_code == 422
    assert api.put(f"/spool/{sid}/measure", {"weight": "abc"}).status_code == 422
    assert "remaining_weight" not in api.get(f"/spool/{sid}").get_json()
    assert api.put("/spool/999/measure", {"weight": 500}).status_code == 404


def test_api_weighing_shows_in_the_ui_data(api, db):
    sid = _spool(db, tare=196)
    api.patch(f"/spool/{sid}", {"remaining_weight": 612})
    row = db.get_spool(sid)
    assert row["current_net_g"] == 612 and row["effective_tare_g"] == 196


# ── Extra fields (7) ─────────────────────────────────────────────────────────

def test_field_list_is_an_array_and_lists_held_keys(api, db):
    assert api.get("/field/spool").get_json() == []
    sid = _spool(db)
    api.patch(f"/spool/{sid}", {"extra": {"last_dried": '"x"'}})
    assert [f["key"] for f in api.get("/field/spool").get_json()] == ["last_dried"]


def test_field_create(api):
    r = api.post("/field/spool/drying_note",
                 {"name": "Drying", "field_type": "text", "default_value": '""'})
    assert r.status_code == 200
    got = {f["key"]: f for f in api.get("/field/spool").get_json()}
    assert got["drying_note"]["name"] == "Drying" and got["drying_note"]["field_type"] == "text"
    assert api.post("/field/filament/drying", {"name": "Drying"}).status_code == 200
    assert api.post("/field/bogus/x", {}).status_code == 404
    assert api.post("/field/spool/Bad-Key", {}).status_code == 400


# ── Tags (8, 9) ──────────────────────────────────────────────────────────────

def test_tag_reader_probe_is_200(api):
    assert api.get("/tag/reader").status_code == 200


def test_tag_link_scan_conflict_unlink(api, db):
    a, b = _spool(db), _spool(db)
    r = api.post(f"/spool/{a}/tag", {"uid": UID, "format": "ntag"})
    assert 200 <= r.status_code < 300
    assert api.get(f"/spool/{a}").get_json()["tags"] == [{"uid": "04A1B2C3D4E5F6", "format": "ntag"}]
    # same spool again: still 2xx
    assert 200 <= api.post(f"/spool/{a}/tag", {"uid": "04a1b2c3d4e5f6"}).status_code < 300

    scan = api.post("/tag/scan", {"uid": "04a1b2c3d4e5f6", "reader_id": "x", "format": "ntag"})
    assert scan.status_code == 200
    body = scan.get_json()
    assert body["matched_spool_id"] == a and body["spool"]["id"] == a

    clash = api.post(f"/spool/{b}/tag", {"uid": UID, "format": "ntag"})
    assert clash.status_code == 409 and clash.get_json()["spool_id"] == a

    unknown = api.post("/tag/scan", {"uid": "FF:EE:DD:CC"})
    assert unknown.status_code == 200 and unknown.get_json()["matched_spool_id"] is None

    # unlink with a different spelling, then the other spool can take it
    assert api.delete(f"/spool/{a}/tag/04a1b2c3d4e5f6").status_code == 200
    assert api.get(f"/spool/{a}").get_json()["tags"] == []
    assert api.delete(f"/spool/{a}/tag/04a1b2c3d4e5f6").status_code == 404
    assert api.post(f"/spool/{b}/tag", {"uid": UID}).status_code == 200


def test_tag_scan_changes_nothing(api, db):
    a = _spool(db)
    api.post(f"/spool/{a}/tag", {"uid": UID})
    before = api.get(f"/spool/{a}").get_json()
    api.post("/tag/scan", {"uid": UID})
    assert api.get(f"/spool/{a}").get_json() == before


def test_tag_scan_matches_archived(api, db):
    a = _spool(db)
    api.post(f"/spool/{a}/tag", {"uid": UID})
    db.deactivate_spool(a)
    body = api.post("/tag/scan", {"uid": UID}).get_json()
    assert body["matched_spool_id"] == a and body["spool"]["archived"] is True


def test_tag_search_filter(api, db):
    a, b = _spool(db), _spool(db)
    api.post(f"/spool/{a}/tag", {"uid": UID})
    hits = api.get("/spool?allow_archived=false&tag=04%3AA1%3AB2%3AC3%3AD4%3AE5%3AF6").get_json()
    assert [s["id"] for s in hits] == [a]
    assert api.get("/spool?allow_archived=false&tag=AABBCC").get_json() == []
    db.deactivate_spool(a)
    assert api.get(f"/spool?allow_archived=false&tag={UID}").get_json() == []
    assert [s["id"] for s in api.get(f"/spool?allow_archived=true&tag={UID}").get_json()] == [a]
    assert b


def test_several_tags_and_tray_uuid(api, db):
    a = _spool(db)
    tray = "0123456789abcdef0123456789ABCDEF"
    api.post(f"/spool/{a}/tag", {"uid": UID, "format": "bambu"})
    api.post(f"/spool/{a}/tag", {"uid": tray, "format": "bambu"})
    uids = sorted(t["uid"] for t in api.get(f"/spool/{a}").get_json()["tags"])
    assert uids == sorted(["04A1B2C3D4E5F6", tray.upper()])


def test_tag_link_validation(api, db):
    a = _spool(db)
    assert api.post(f"/spool/{a}/tag", {"uid": ""}).status_code == 422
    assert api.post("/spool/999/tag", {"uid": UID}).status_code == 404


def test_unlink_clears_companion_extra_fields(api, db):
    a = _spool(db)
    api.post(f"/spool/{a}/tag", {"uid": UID})
    api.patch(f"/spool/{a}", {"extra": {
        "tag": json.dumps("04A1B2C3D4E5F6"),
        "nfc_id": json.dumps("04A1B2C3D4E5F6"),
        "card_uids": json.dumps("04A1B2C3D4E5F6,AABBCCDD"),
        "rfid_tag": json.dumps("04:a1:b2:c3:d4:e5:f6"),
        "last_dried": json.dumps("keep"),
    }})
    s = api.delete(f"/spool/{a}/tag/{UID}").get_json()
    assert s["extra"] == {"card_uids": json.dumps("AABBCCDD"), "last_dried": json.dumps("keep")}


def test_extra_filter_for_the_fallback_lookup(api, db):
    a, b = _spool(db), _spool(db)
    api.patch(f"/spool/{a}", {"extra": {"tag": json.dumps("04A1B2C3D4E5F6")}})
    api.patch(f"/spool/{b}", {"extra": {"tag": json.dumps("FFFF")}})
    hits = api.get("/spool?allow_archived=false&extra.tag=04A1B2C3D4E5F6").get_json()
    assert [s["id"] for s in hits] == [a]


# ── Locations and the spool page (14, 7.3) ───────────────────────────────────

def test_location_list(api, db):
    _spool(db, location="Shelf A")
    _spool(db, location="Dry box")
    _spool(db, location="Shelf A")
    _spool(db, location="")
    assert api.get("/location").get_json() == ["Dry box", "Shelf A"]


def test_spool_show_redirects_to_detail_page(auth_client, db):
    sid = _spool(db)
    r = auth_client.get(f"/spool/show/{sid}")
    assert r.status_code == 302 and r.headers["Location"].endswith(f"/spools/{sid}")


# ── Housekeeping ─────────────────────────────────────────────────────────────

def test_deleting_a_spool_removes_tags_and_extra(api, db):
    a = _spool(db)
    api.post(f"/spool/{a}/tag", {"uid": UID})
    api.patch(f"/spool/{a}", {"extra": {"k": '"v"'}})
    db.delete_spool(a)
    assert api.post("/tag/scan", {"uid": UID}).get_json()["matched_spool_id"] is None


def test_init_db_is_idempotent(db):
    db.init_db()
    db.init_db()


# ── Task B: tare chain ───────────────────────────────────────────────────────

def test_tare_chain_filament_then_vendor_then_zero(api, db):
    """custom -> model -> filament.spool_weight -> vendor.empty_spool_weight -> 0, API and UI alike."""
    fid = db.create_filament("Chain Co", "PLA", "Basic", "#112233")
    sid = db.create_spool(fid, None, None, 1000, "", "", None, "")
    assert db.get_spool(sid)["effective_tare_g"] == 0
    assert "spool_weight" not in api.get(f"/spool/{sid}").get_json()

    db.set_brand_empty_spool("Chain Co", 140)
    assert db.get_spool(sid)["effective_tare_g"] == 140
    assert api.get(f"/spool/{sid}").get_json()["spool_weight"] == 140

    db.update_filament_api_fields(fid, spool_weight_g=180)
    assert db.get_spool(sid)["effective_tare_g"] == 180
    assert api.get(f"/spool/{sid}").get_json()["spool_weight"] == 180

    db.update_spool_api_fields(sid, custom_tare_g=200)
    assert db.get_spool(sid)["effective_tare_g"] == 200


def test_inventory_query_uses_the_same_tare_chain(db):
    fid = db.create_filament("Inv Co", "PLA", "Basic", "#112233")
    db.create_spool(fid, None, None, 1000, "", "", None, "")
    db.set_brand_empty_spool("Inv Co", 111)
    rows = db.list_inventory()
    rows = rows if isinstance(rows, list) else next(v for v in rows.values() if isinstance(v, list) and v)
    assert rows[0]["effective_tare_g"] == 111


def test_spool_object_carries_filament_and_vendor_extras(api, db):
    fid = db.create_filament("Bambu Lab", "PLA", "Matte", "#000000", color_name="Black")
    db.update_filament_api_fields(fid, article_number="A-1", external_id="x1", density=1.24,
                                  weight_g=1000, spool_weight_g=250, extruder_temp=210, bed_temp=55)
    db.set_brand_empty_spool("Bambu Lab", 100)
    sid = db.create_spool(fid, None, None, 1000, "", "", None, "")
    f = api.get(f"/spool/{sid}").get_json()["filament"]
    assert (f["weight"], f["spool_weight"], f["article_number"], f["external_id"]) == (1000, 250, "A-1", "x1")
    assert f["vendor"]["empty_spool_weight"] == 100 and f["vendor"]["id"] > 0
    assert (f["density"], f["settings_extruder_temp"], f["settings_bed_temp"]) == (1.24, 210, 55)


# ── Filament database (15, 16) ───────────────────────────────────────────────

def test_external_index_and_filtered_list(api):
    r = api.get("/external/manufacturer?diameter=1.75")
    assert r.status_code == 200
    index = r.get_json()
    names = [m["name"].lower() for m in index]
    assert index and len(names) == len(set(names))
    maker = next(m for m in index if m["materials"])
    mat = maker["materials"][0]
    entries = api.get("/external/filament", query_string={
        "manufacturer": maker["name"], "material": mat["name"], "diameter": "1.75"}).get_json()
    assert len(entries) == mat["count"] > 0
    ids = [e["id"] for e in entries]
    assert len(ids) == len(set(ids))
    for e in entries:
        assert e["manufacturer"] == maker["name"] and e["material"] == mat["name"]
        assert e["name"] and len(e["id"]) <= 79 and len(e["color_hex"]) == 6 and "#" not in e["color_hex"]
        assert e["diameter"] == 1.75
    again = api.get("/external/filament", query_string={
        "manufacturer": maker["name"].upper(), "material": mat["name"].lower(), "diameter": "1.75"}).get_json()
    assert [e["id"] for e in again] == ids


def test_external_ids_are_stable(api):
    a = api.get("/external/filament?manufacturer=Polymaker&material=PLA").get_json()
    b = api.get("/external/filament?manufacturer=Polymaker&material=PLA").get_json()
    assert a and a == b


def test_external_search_is_404_and_catalog_missing_is_404(api, monkeypatch):
    assert api.get("/external/filament/search?limit=1&query=PLA").status_code == 404
    import filament_catalog
    monkeypatch.setattr(filament_catalog, "available", lambda: False)
    assert api.get("/external/manufacturer").status_code == 404
    assert api.get("/external/filament").status_code == 404


def test_external_material_has_numeric_density(api):
    items = api.get("/external/material").get_json()
    assert items and all(isinstance(i["density"], (int, float)) and i["material"] for i in items)
    assert {"PLA", "PETG"} <= {i["material"] for i in items}


def test_external_routes_need_the_key(client):
    assert client.get("/api/v1/external/manufacturer").status_code == 401


# ── Creating a maker, a filament and a spool (17, 7.2) ───────────────────────

def test_create_flow_like_the_checker(api, db):
    v = api.post("/vendor", {"name": "SpoolmanScale check", "empty_spool_weight": 140})
    assert v.status_code in (200, 201)
    vid = v.get_json()["id"]
    assert v.get_json()["empty_spool_weight"] == 140
    assert [x["id"] for x in api.get('/vendor?name="spoolmanscale CHECK"').get_json()] == [vid]
    assert api.get('/vendor?name="nobody"').get_json() == []

    fil = {"name": "Check Blue", "vendor_id": vid, "material": "PLA", "density": 1.24, "diameter": 1.75,
           "color_hex": "0055AA", "weight": 1000, "spool_weight": 140, "settings_extruder_temp": 210,
           "settings_bed_temp": 55, "external_id": "sms-1", "article_number": "SMS-1"}
    r = api.post("/filament", fil)
    assert r.status_code in (200, 201)
    f = r.get_json()
    fid = f["id"]
    assert (f["name"], f["external_id"], f["article_number"]) == ("Check Blue", "sms-1", "SMS-1")
    assert f["vendor"]["name"] == "SpoolmanScale check" and f["color_hex"].lower() == "0055aa"
    for q in ('external_id="sms-1"', 'article_number="SMS-1"', 'external_id=sms-1',
              'vendor.name="spoolmanscale check"&material="pla"&color_hex=0055AA&color_similarity_threshold=0'):
        assert [x["id"] for x in api.get("/filament?" + q).get_json()] == [fid], q
    assert api.get('/filament?external_id="nothing"').get_json() == []

    s = api.post("/spool", {"filament_id": fid, "initial_weight": 1000, "spool_weight": 140,
                            "remaining_weight": 850})
    assert s.status_code in (200, 201)
    spool = s.get_json()
    assert spool["remaining_weight"] == 850 and spool["initial_weight"] == 1000
    assert spool["spool_weight"] == 140 and spool["filament"]["id"] == fid
    sid = spool["id"]
    assert db.get_spool(sid)["current_net_g"] == 850

    assert api.delete(f"/vendor/{vid}").status_code == 409
    assert api.delete(f"/filament/{fid}").status_code == 409
    assert api.delete(f"/spool/{sid}").status_code == 200
    assert api.delete(f"/filament/{fid}").status_code == 200
    assert api.delete(f"/vendor/{vid}").status_code == 200
    assert api.get(f"/spool/{sid}").status_code == 404
    assert api.delete(f"/vendor/{vid}").status_code == 404


def test_vendor_patch_and_duplicate_create(api, db):
    a = api.post("/vendor", {"name": "Dup Co"}).get_json()
    assert "empty_spool_weight" not in a
    assert api.post("/vendor", {"name": "Dup Co"}).get_json()["id"] == a["id"]
    r = api.patch(f"/vendor/{a['id']}", {"empty_spool_weight": 196})
    assert r.status_code == 200 and r.get_json()["empty_spool_weight"] == 196
    assert api.patch(f"/vendor/{a['id']}", {"empty_spool_weight": None}).get_json().get("empty_spool_weight") is None
    assert api.patch("/vendor/9999", {}).status_code == 404
    assert api.post("/vendor", {"name": ""}).status_code == 422


def test_filament_validation(api):
    vid = api.post("/vendor", {"name": "V"}).get_json()["id"]
    assert api.post("/filament", {"vendor_id": vid}).status_code == 422
    assert api.post("/filament", {"name": "x"}).status_code == 422
    assert api.post("/filament", {"name": "x", "vendor_id": 9999}).status_code == 404
    assert api.post("/filament", {"name": "x", "vendor_id": vid, "color_hex": "zz"}).status_code == 422
    assert api.post("/filament", {"name": "x", "vendor_id": vid, "density": "heavy"}).status_code == 422
    assert api.get("/filament").get_json() == []


def test_filament_multicolor_and_rgba(api, db):
    vid = api.post("/vendor", {"name": "V"}).get_json()["id"]
    f = api.post("/filament", {"name": "Duo", "vendor_id": vid, "material": "PLA",
                               "multi_color_hexes": "FF0000,00FF00,0000FF",
                               "multi_color_direction": "coaxial"}).get_json()
    assert f["multi_color_hexes"].lower() == "ff0000,00ff00" and f["color_hex"].lower() == "ff0000"
    g = api.post("/filament", {"name": "Glass", "vendor_id": vid, "material": "PETG",
                               "color_hex": "11223380"}).get_json()
    assert g["color_hex"].lower() == "112233" and db.get_filament(g["id"])["translucent"] == 1


def test_filament_patch_tare_and_extra(api, db):
    vid = api.post("/vendor", {"name": "V"}).get_json()["id"]
    fid = api.post("/filament", {"name": "Plain", "vendor_id": vid, "material": "PLA"}).get_json()["id"]
    sid = api.post("/spool", {"filament_id": fid, "initial_weight": 1000}).get_json()["id"]
    r = api.patch(f"/filament/{fid}", {"spool_weight": 196, "extra": {"drying": '"55 C, 8 h"'}})
    assert r.status_code == 200 and r.get_json()["extra"] == {"drying": '"55 C, 8 h"'}
    assert api.get(f"/spool/{sid}").get_json()["spool_weight"] == 196
    assert api.patch(f"/filament/{fid}", {"extra": {"drying": '""'}}).get_json()["extra"] == {}
    assert api.patch(f"/filament/{fid}", {"spool_weight": None}).status_code == 200
    assert "spool_weight" not in api.get(f"/spool/{sid}").get_json()
    assert api.patch("/filament/9999", {}).status_code == 404


def test_spool_create_defaults_and_validation(api, db):
    vid = api.post("/vendor", {"name": "V"}).get_json()["id"]
    fid = api.post("/filament", {"name": "W", "vendor_id": vid, "material": "PLA", "weight": 750,
                                 "spool_weight": 120}).get_json()["id"]
    s = api.post("/spool", {"filament_id": fid, "location": "Shelf B"}).get_json()
    assert s["initial_weight"] == 750 and s["spool_weight"] == 120 and s["location"] == "Shelf B"
    assert "remaining_weight" not in s
    big = api.post("/spool", {"filament_id": fid, "remaining_weight": 900}).get_json()
    assert big["initial_weight"] == 900 and big["remaining_weight"] == 900
    zero = api.post("/spool", {"filament_id": fid, "remaining_weight": 0}).get_json()
    assert zero["remaining_weight"] == 0
    assert api.post("/spool", {}).status_code == 422
    assert api.post("/spool", {"filament_id": 9999}).status_code == 404
    assert api.post("/spool", {"filament_id": fid, "initial_weight": -1}).status_code == 422
    assert api.delete("/spool/9999").status_code == 404


# ── API-created rows render in the UI ────────────────────────────────────────

def test_api_created_rows_render_in_the_ui(auth_client, api, db):
    vid = api.post("/vendor", {"name": "UI Co", "empty_spool_weight": 130}).get_json()["id"]
    fid = api.post("/filament", {"name": "Render Me", "vendor_id": vid, "material": "PLA",
                                 "color_hex": "FF8800", "density": 1.24, "weight": 1000}).get_json()["id"]
    sid = api.post("/spool", {"filament_id": fid, "remaining_weight": 700}).get_json()["id"]
    bare = api.post("/filament", {"name": "Bare", "vendor_id": vid}).get_json()["id"]
    bare_spool = api.post("/spool", {"filament_id": bare}).get_json()["id"]
    for path in ("/filaments", f"/filaments/{fid}", f"/filaments/{fid}/edit", f"/filaments/{bare}",
                 "/spools", f"/spools/{sid}", f"/spools/{sid}/edit", f"/spools/{sid}/weigh",
                 f"/spools/{bare_spool}", "/reports/inventory", "/admin/brands"):
        r = auth_client.get(path)
        assert r.status_code == 200, (path, r.status_code)
    assert b"Render Me" in auth_client.get("/filaments").data
    assert b"UI Co" in auth_client.get(f"/spools/{sid}").data


# ── Stable vendor ids ────────────────────────────────────────────────────────

def test_vendor_ids_survive_vacuum_and_new_brands_get_fresh_ids(api, db):
    import database
    a = api.post("/vendor", {"name": "Vid Alpha"}).get_json()["id"]
    b = api.post("/vendor", {"name": "Vid Beta"}).get_json()["id"]
    c = api.post("/vendor", {"name": "Vid Gamma"}).get_json()["id"]
    assert len({a, b, c}) == 3 and a < b < c
    # A brand created through the UI path also gets an id (trigger), above all others.
    database.create_brand("Vid Delta")
    d = api.get('/vendor?name="Vid Delta"').get_json()[0]["id"]
    assert d > c
    # Drop a middle brand and VACUUM: rowids may renumber, vendor ids must not.
    database.delete_brand("Vid Beta")
    with database.get_db() as conn:
        conn.isolation_level = None
        conn.execute("VACUUM")
    ids = {v["name"]: v["id"] for v in api.get("/vendor").get_json()}
    assert ids["Vid Alpha"] == a and ids["Vid Gamma"] == c and ids["Vid Delta"] == d
    assert api.get(f"/vendor/{c}") is not None
    assert api.patch(f"/vendor/{c}", {"empty_spool_weight": 120}).status_code == 200
