"""Web Push: VAPID keys, subscriptions, per-user preferences and the test button. Nothing leaves
the machine: `pywebpush.webpush` is replaced."""
import json
import os
import stat
import threading
from types import SimpleNamespace

import pytest
from werkzeug.security import generate_password_hash

from conftest import ADMIN_USER, ADMIN_PASS, VIEWER_USER

FCM = "https://fcm.googleapis.com/fcm/send/abc123"
SUB = {"endpoint": FCM, "keys": {"p256dh": "BPubKey_-1234", "auth": "authKey_-12"}}


@pytest.fixture()
def push(app_module):
    import push as mod
    return mod


@pytest.fixture()
def sent(push, monkeypatch):
    """Records every webpush call; the status each call answers is `sent.status`."""
    calls = []

    class Box(list):
        status = 201

    box = Box()

    def fake(info, data=None, vapid_private_key=None, vapid_claims=None, timeout=None, **kw):
        box.append({"endpoint": info["endpoint"], "data": json.loads(data),
                    "claims": dict(vapid_claims), "timeout": timeout})
        if box.status >= 400:
            raise push.pywebpush.WebPushException(
                "boom", response=SimpleNamespace(status_code=box.status))
        return SimpleNamespace(status_code=box.status)

    monkeypatch.setattr(push.pywebpush, "webpush", fake)
    return box


def _admin_id(db):
    return db.get_user_by_username(ADMIN_USER)["id"]


# ── VAPID keys ───────────────────────────────────────────────────────────────

def test_keys_generated_once_and_reused(push):
    path = push.vapid_path()
    assert not path.exists()
    first = push.vapid_keys()
    assert path.exists()
    assert push.vapid_keys() == first          # second call reads the same pair
    data = json.loads(path.read_text())
    assert data == {"private": first[0], "public": first[1]}
    if os.name == "posix":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    # no temp leftovers next to it
    assert not [p for p in path.parent.iterdir() if p.name.startswith(".vapid-")]


def test_public_key_is_an_uncompressed_p256_point(push):
    import base64
    raw = base64.urlsafe_b64decode(push.public_key() + "==")
    assert len(raw) == 65 and raw[0] == 4


def test_keys_not_in_database(push, db):
    push.vapid_keys()
    with open(db.DB_PATH, "rb") as f:
        blob = f.read()
    assert push.vapid_keys()[0].encode() not in blob


def test_page_exposes_only_the_public_key(auth_client, push):
    r = auth_client.get("/account/notifications")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    private, public = push.vapid_keys()
    assert public in body
    assert private not in body


def test_vapid_sub_https_has_no_trailing_slash(push, db):
    db.set_setting("app_base_url", "https://spool.example.com/")
    assert push.vapid_sub() == "https://spool.example.com"


def test_vapid_sub_falls_back_to_mailto_when_not_https(push, db):
    db.set_setting("app_base_url", "http://localhost:5000")
    assert push.vapid_sub().startswith("mailto:")


# ── Subscribe / unsubscribe ──────────────────────────────────────────────────

def test_requires_login(client):
    assert client.get("/account/notifications").status_code == 302
    assert client.post("/account/notifications/subscribe", json=SUB).status_code == 401
    assert client.post("/account/notifications/test", json={}).status_code == 401


def test_subscribe_and_list(auth_client, db):
    r = auth_client.post("/account/notifications/subscribe", json=SUB,
                         headers={"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0)"})
    assert r.status_code == 200 and r.get_json()["devices"] == 1
    page = auth_client.get("/account/notifications").get_data(as_text=True)
    assert "iPhone" in page
    # same endpoint again = still one row
    auth_client.post("/account/notifications/subscribe", json=SUB)
    assert len(db.list_push_subscriptions(_admin_id(db))) == 1


@pytest.mark.parametrize("bad", [
    {},
    {"endpoint": FCM},
    {"endpoint": "http://fcm.googleapis.com/x", "keys": SUB["keys"]},
    {"endpoint": "https://127.0.0.1/x", "keys": SUB["keys"]},
    {"endpoint": "https://evil.example.com/x", "keys": SUB["keys"]},
    {"endpoint": "https://fcm.googleapis.com.evil.com/x", "keys": SUB["keys"]},
    {"endpoint": FCM, "keys": {"p256dh": "bad key!", "auth": "ok"}},
])
def test_subscribe_rejects_bad_payload(auth_client, db, bad):
    r = auth_client.post("/account/notifications/subscribe", json=bad)
    assert r.status_code == 400
    assert db.list_push_subscriptions(_admin_id(db)) == []


def test_unsubscribe_removes_only_own(auth_client, viewer_client, db):
    auth_client.post("/account/notifications/subscribe", json=SUB)
    # another user cannot remove it by endpoint
    viewer_client.post("/account/notifications/unsubscribe", json={"endpoint": FCM})
    assert len(db.list_push_subscriptions(_admin_id(db))) == 1
    r = auth_client.post("/account/notifications/unsubscribe", json={"endpoint": FCM})
    assert r.status_code == 200 and r.get_json()["devices"] == 0


def test_device_delete_only_own(auth_client, viewer_client, db):
    auth_client.post("/account/notifications/subscribe", json=SUB)
    sub_id = db.list_push_subscriptions(_admin_id(db))[0]["id"]
    viewer_client.post(f"/account/notifications/devices/{sub_id}/delete")
    assert len(db.list_push_subscriptions(_admin_id(db))) == 1
    auth_client.post(f"/account/notifications/devices/{sub_id}/delete")
    assert db.list_push_subscriptions(_admin_id(db)) == []


def test_viewer_cannot_see_other_users_devices(auth_client, viewer_client):
    auth_client.post("/account/notifications/subscribe", json=SUB,
                     headers={"User-Agent": "Mozilla/5.0 (Linux; Android 14)"})
    page = viewer_client.get("/account/notifications").get_data(as_text=True)
    assert "Android" not in page.split("Aparelhos com notificações")[1].split("Avisos")[0]


# ── Preferences ──────────────────────────────────────────────────────────────

def test_prefs_default_off_and_threshold_from_setting(auth_client, db):
    prefs = db.get_notification_prefs(_admin_id(db))
    assert (prefs["low_stock_on"], prefs["last_spool_on"], prefs["weigh_reminder_on"]) == (0, 0, 0)
    assert prefs["low_stock_g"] == 200 and prefs["weigh_reminder_days"] == 7


def test_prefs_save(auth_client, db):
    r = auth_client.post("/account/notifications/prefs", data={
        "low_stock_on": "1", "low_stock_g": "350", "last_spool_on": "1",
        "weigh_reminder_on": "1", "weigh_reminder_days": "14"})
    assert r.status_code == 302
    p = db.get_notification_prefs(_admin_id(db))
    assert (p["low_stock_on"], p["low_stock_g"], p["last_spool_on"],
            p["weigh_reminder_on"], p["weigh_reminder_days"]) == (1, 350, 1, 1, 14)
    # unchecked boxes turn the switches off
    auth_client.post("/account/notifications/prefs",
                     data={"low_stock_g": "350", "weigh_reminder_days": "14"})
    p = db.get_notification_prefs(_admin_id(db))
    assert (p["low_stock_on"], p["last_spool_on"], p["weigh_reminder_on"]) == (0, 0, 0)


@pytest.mark.parametrize("field,value", [
    ("low_stock_g", "0"), ("low_stock_g", "5001"), ("low_stock_g", "abc"), ("low_stock_g", "-5"),
    ("weigh_reminder_days", "0"), ("weigh_reminder_days", "61"), ("weigh_reminder_days", "x"),
])
def test_prefs_validation_rejects_and_keeps_old(auth_client, db, field, value):
    data = {"low_stock_on": "1", "low_stock_g": "300", "weigh_reminder_days": "10"}
    data[field] = value
    auth_client.post("/account/notifications/prefs", data=data)
    p = db.get_notification_prefs(_admin_id(db))
    assert p["low_stock_on"] == 0 and p["low_stock_g"] == 200 and p["weigh_reminder_days"] == 7


def test_prefs_boundaries_accepted(auth_client, db):
    auth_client.post("/account/notifications/prefs",
                     data={"low_stock_g": "5000", "weigh_reminder_days": "60"})
    p = db.get_notification_prefs(_admin_id(db))
    assert p["low_stock_g"] == 5000 and p["weigh_reminder_days"] == 60


def test_read_only_user_has_no_reminder(viewer_client, db):
    page = viewer_client.get("/account/notifications").get_data(as_text=True)
    assert "weigh_reminder_on" not in page
    assert "low_stock_on" in page
    viewer_client.post("/account/notifications/prefs", data={
        "low_stock_on": "1", "low_stock_g": "250",
        "weigh_reminder_on": "1", "weigh_reminder_days": "5"})
    uid = db.get_user_by_username(VIEWER_USER)["id"]
    p = db.get_notification_prefs(uid)
    assert p["low_stock_on"] == 1 and p["low_stock_g"] == 250
    assert p["weigh_reminder_on"] == 0


def test_admin_sees_reminder(auth_client):
    assert "weigh_reminder_on" in auth_client.get("/account/notifications").get_data(as_text=True)


# ── Sending ──────────────────────────────────────────────────────────────────

def test_test_button_sends_to_own_devices(auth_client, db, sent):
    auth_client.post("/account/notifications/subscribe", json=SUB)
    r = auth_client.post("/account/notifications/test", json={})
    assert r.status_code == 200
    assert r.get_json()["results"][0]["result"] == "ok"
    assert len(sent) == 1 and sent[0]["endpoint"] == FCM
    assert sent[0]["timeout"] == 10
    assert sent[0]["data"]["title"] == "Spool"
    assert sent[0]["claims"]["sub"].startswith(("https://", "mailto:"))
    assert not sent[0]["claims"]["sub"].endswith("/")
    sub = db.list_push_subscriptions(_admin_id(db))[0]
    assert sub["last_ok_at"] != ""


def test_test_button_never_sends_to_other_users(auth_client, viewer_client, sent):
    viewer_client.post("/account/notifications/subscribe", json=SUB)
    r = auth_client.post("/account/notifications/test", json={})
    assert r.get_json()["results"] == [] and sent == []


@pytest.mark.parametrize("status", [404, 410])
def test_gone_subscription_is_deleted(auth_client, db, sent, status):
    auth_client.post("/account/notifications/subscribe", json=SUB)
    sent.status = status
    r = auth_client.post("/account/notifications/test", json={})
    assert r.get_json()["results"][0]["result"] == "expired"
    assert db.list_push_subscriptions(_admin_id(db)) == []


def test_other_failure_keeps_subscription_and_logs_only(auth_client, db, sent):
    auth_client.post("/account/notifications/subscribe", json=SUB)
    sent.status = 500
    r = auth_client.post("/account/notifications/test", json={})
    assert r.get_json()["results"][0]["result"] == "failed"
    assert len(db.list_push_subscriptions(_admin_id(db))) == 1


def test_send_async_runs_in_a_daemon_thread(auth_client, push, db, sent):
    auth_client.post("/account/notifications/subscribe", json=SUB)
    th = push.send_async(_admin_id(db), "T", "B", "/x")
    assert isinstance(th, threading.Thread) and th.daemon
    th.join(5)
    assert len(sent) == 1 and sent[0]["data"] == {"title": "T", "body": "B", "url": "/x"}


def test_send_async_swallows_errors(push, db, monkeypatch):
    monkeypatch.setattr(push, "send_to_user", lambda *a, **k: 1 / 0)
    push.send_async(1, "T", "B").join(5)   # must not raise


# ── Demo mode ────────────────────────────────────────────────────────────────

def test_demo_mode_blocks(auth_client, app_module, monkeypatch, db):
    import routes.notifications as mod
    monkeypatch.setattr(app_module, "DEMO_MODE", True)
    monkeypatch.setattr(mod, "DEMO_MODE", True)
    assert auth_client.get("/account/notifications").status_code == 302
    assert auth_client.post("/account/notifications/prefs", data={"low_stock_g": "10"}).status_code == 302
    assert auth_client.post("/account/notifications/subscribe", json=SUB).status_code == 403
    assert auth_client.post("/account/notifications/test", json={}).status_code == 403
    assert auth_client.post("/account/notifications/unsubscribe", json={"endpoint": FCM}).status_code == 403
    assert db.list_push_subscriptions(_admin_id(db)) == []


# ── Service worker ───────────────────────────────────────────────────────────

def test_sw_has_push_handlers_and_keeps_get_only_fetch():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sw = open(os.path.join(root, "static", "sw.js"), encoding="utf-8").read()
    assert 'addEventListener("push"' in sw and 'addEventListener("notificationclick"' in sw
    assert 'event.request.method !== "GET"' in sw
    assert "u.origin === self.location.origin" in sw
