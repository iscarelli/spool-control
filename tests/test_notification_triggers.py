"""Push triggers: low stock, last spool and the weighing reminder. `pywebpush.webpush` is replaced
and `send_async` runs inline, so nothing leaves the machine and nothing races."""
import json
from contextlib import closing
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from werkzeug.security import generate_password_hash

from conftest import ADMIN_USER, VIEWER_USER

FCM = "https://fcm.googleapis.com/fcm/send/abc123"
FCM2 = "https://fcm.googleapis.com/fcm/send/other"
ISO = "%Y-%m-%dT%H:%M:%SZ"
NOW = datetime(2026, 10, 24, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture()
def sent(app_module, monkeypatch):
    import push
    box = []

    def fake(info, data=None, **kw):
        box.append({"endpoint": info["endpoint"], **json.loads(data)})
        return SimpleNamespace(status_code=201)

    monkeypatch.setattr(push.pywebpush, "webpush", fake)
    monkeypatch.setattr(push, "send_async", lambda *a, **k: push.send_to_user(*a, **k))
    return box


@pytest.fixture()
def notify(app_module):
    import notify as mod
    return mod


def _uid(db, name=ADMIN_USER):
    return db.get_user_by_username(name)["id"]


def _subscribe(db, uid, endpoint=FCM):
    db.save_push_subscription(uid, endpoint, "BPubKey_-1234", "authKey_-12", "UA")


def _prefs(db, uid, low=False, grams=200, last=False, rem=False, days=7):
    db.save_notification_prefs(uid, low, grams, last, rem, days)


def _spool(db, material="PLA", tare=200, filament_id=None):
    if filament_id is None:
        filament_id = db.create_filament("Acme", material, "Basic", "#ff0000", "Red")
    return db.create_spool(filament_id, None, tare, 1000, "", "", None, ""), filament_id


def _weigh(db, spool_id, net):
    db.add_weight_reading(spool_id, 200 + net, 200)


def _setup_low(db, grams=200):
    uid = _uid(db)
    _subscribe(db, uid)
    _prefs(db, uid, low=True, grams=grams)
    return uid


def _viewer(db):
    db.create_user(VIEWER_USER, generate_password_hash("viewer-test-pass"), role="viewer",
                   must_change=False)
    return _uid(db, VIEWER_USER)


# ── Low stock ────────────────────────────────────────────────────────────────

def test_low_stock_fires_on_crossing_with_text_and_url(db, sent):
    _setup_low(db)
    sid, _f = _spool(db)
    _weigh(db, sid, 250)
    assert sent == []
    _weigh(db, sid, 150)
    assert len(sent) == 1
    n = sent[0]
    assert n["title"] == "Rolo acabando"
    assert n["body"] == f"Acme PLA Basic Red (SP-{sid:04d}): 150 g restantes"
    assert n["url"] == f"/spools/{sid}"


def test_low_stock_boundary_exactly_n_is_not_below(db, sent):
    _setup_low(db, 200)
    sid, _f = _spool(db)
    _weigh(db, sid, 200)
    assert sent == []
    _weigh(db, sid, 199)
    assert len(sent) == 1


def test_low_stock_once_per_crossing_then_reset_on_correction(db, sent):
    _setup_low(db)
    sid, _f = _spool(db)
    _weigh(db, sid, 150)
    _weigh(db, sid, 140)   # still below: no second alert
    assert len(sent) == 1
    _weigh(db, sid, 400)   # corrected weighing clears the mark
    _weigh(db, sid, 100)   # crosses again
    assert len(sent) == 2


def test_low_stock_first_ever_reading_below_counts(db, sent):
    _setup_low(db)
    sid, _f = _spool(db)
    _weigh(db, sid, 50)
    assert len(sent) == 1


def test_low_stock_per_user_threshold_and_switch(db, sent):
    admin = _uid(db)
    _subscribe(db, admin)
    _prefs(db, admin, low=True, grams=100)
    viewer = _viewer(db)
    _subscribe(db, viewer, FCM2)
    _prefs(db, viewer, low=True, grams=300)
    sid, _f = _spool(db)
    _weigh(db, sid, 250)          # below 300 only
    assert [n["endpoint"] for n in sent] == [FCM2]
    _prefs(db, viewer, low=False, grams=300)
    sid2, _f = _spool(db)
    _weigh(db, sid2, 250)         # switched off: nobody; admin's 100 not crossed
    assert len(sent) == 1


def test_low_stock_not_for_finished_spool(db, sent):
    _setup_low(db)
    sid, _f = _spool(db)
    db.deactivate_spool(sid)
    _weigh(db, sid, 10)
    assert sent == []


def test_low_stock_demo_mode_sends_nothing(db, sent, monkeypatch):
    _setup_low(db)
    monkeypatch.setenv("DEMO_MODE", "1")
    sid, _f = _spool(db)
    _weigh(db, sid, 10)
    assert sent == []


# Every weight write path ends in db.add_weight_reading, so each must trigger the alert.

def test_low_stock_via_weigh_form(db, sent, auth_client):
    _setup_low(db)
    sid, _f = _spool(db)
    auth_client.post(f"/spools/{sid}/weigh", data={"gross_weight_g": "350"})
    assert len(sent) == 1


def test_low_stock_via_weigh_json(db, sent, auth_client):
    _setup_low(db)
    sid, _f = _spool(db)
    r = auth_client.post(f"/spools/{sid}/weigh.json", json={"gross_weight_g": 350})
    assert r.status_code == 200
    assert len(sent) == 1


def test_low_stock_via_quick_weigh(db, sent, auth_client):
    _setup_low(db)
    sid, _f = _spool(db)
    auth_client.post("/weigh", data={"spool_code": f"SP-{sid:04d}", "gross_weight_g": "350"})
    assert len(sent) == 1


def test_low_stock_via_scale_api(db, sent, client):
    _setup_low(db)
    sid, _f = _spool(db)
    key = db.get_api_key("scale")["key"]
    r = client.post("/api/weigh", json={"spool_id": sid, "gross_weight_g": 350},
                    headers={"X-API-Key": key})
    assert r.status_code == 200
    assert len(sent) == 1


def test_every_weight_writer_goes_through_the_hook():
    """Guard for new code: add_weight_reading is the only INSERT into weight_readings (deploy/seed-demo-data.py seeds demo data, where sends are off)."""
    import pathlib
    root = pathlib.Path(__file__).resolve().parent.parent
    hits = [str(p.relative_to(root)) for p in root.rglob("*.py")
            if not {".venv", "tests", "private", ".claude", "deploy"} & set(p.relative_to(root).parts)
            and "INSERT INTO weight_readings" in p.read_text(encoding="utf-8")]
    assert hits == ["database.py"]


# ── Last spool ───────────────────────────────────────────────────────────────

def _setup_last(db):
    uid = _uid(db)
    _subscribe(db, uid)
    _prefs(db, uid, last=True)
    return uid


def test_last_spool_fires_when_one_remains(db, sent):
    _setup_last(db)
    a, fid = _spool(db)
    _spool(db, filament_id=fid)
    db.deactivate_spool(a)
    assert len(sent) == 1
    n = sent[0]
    assert n["title"] == "Último rolo"
    assert n["body"] == "Só resta 1 rolo de Acme PLA Basic Red"
    assert n["url"] == f"/filaments/{fid}"


def test_last_spool_not_with_zero_or_two_remaining(db, sent):
    _setup_last(db)
    a, fid = _spool(db)
    b, _f = _spool(db, filament_id=fid)
    c, _f = _spool(db, filament_id=fid)
    db.deactivate_spool(a)        # two remain
    assert sent == []
    db.deactivate_spool(b)        # one remains
    assert len(sent) == 1
    db.deactivate_spool(c)        # zero remain
    assert len(sent) == 1


def test_last_spool_ignores_other_filaments_and_pref_off(db, sent):
    uid = _setup_last(db)
    a, fid = _spool(db)
    _spool(db, filament_id=fid)
    _spool(db, material="PETG")   # other filament does not count
    _prefs(db, uid, last=False)
    db.deactivate_spool(a)
    assert sent == []


def test_last_spool_via_deactivate_routes(db, sent, auth_client):
    _setup_last(db)
    a, fid = _spool(db)
    b, _f = _spool(db, filament_id=fid)
    _spool(db, filament_id=fid)
    auth_client.post(f"/spools/{a}/deactivate")
    assert sent == []
    auth_client.post("/spools/deactivate-bulk", data={"ids": [str(b)]})
    assert len(sent) == 1


def test_last_spool_demo_mode(db, sent, monkeypatch):
    _setup_last(db)
    monkeypatch.setenv("DEMO_MODE", "1")
    a, fid = _spool(db)
    _spool(db, filament_id=fid)
    db.deactivate_spool(a)
    assert sent == []


# ── Weigh reminder ───────────────────────────────────────────────────────────

def _age_reading(db, spool_id, days):
    ts = (NOW - timedelta(days=days)).strftime(ISO)
    with closing(db.get_db()) as c:
        c.execute("UPDATE weight_readings SET ts=? WHERE spool_id=?", (ts, spool_id))
        c.commit()


def _setup_rem(db, days=7):
    uid = _uid(db)
    _subscribe(db, uid)
    _prefs(db, uid, rem=True, days=days)
    return uid


def test_reminder_sends_and_advances_timestamp(db, sent, notify):
    uid = _setup_rem(db)
    a, _f = _spool(db)
    _spool(db)                               # never weighed: overdue
    c, _f = _spool(db)
    _weigh(db, a, 500)
    _age_reading(db, a, 10)                  # overdue
    _weigh(db, c, 500)
    _age_reading(db, c, 1)                   # fresh
    assert notify.run_weigh_reminders(NOW, 12) == [uid]
    n = sent[0]
    assert n["title"] == "Hora de pesar"
    assert n["body"] == "2 rolos sem pesagem há mais de 7 dias"
    assert n["url"] == "/spools"
    assert db.get_notification_prefs(uid)["weigh_reminder_last_at"] == NOW.strftime(ISO)


def test_reminder_singular(db, sent, notify):
    _setup_rem(db)
    _spool(db)
    notify.run_weigh_reminders(NOW, 12)
    assert sent[0]["body"] == "1 rolo sem pesagem há mais de 7 dias"


def test_reminder_interval(db, sent, notify):
    uid = _setup_rem(db, days=7)
    _spool(db)
    notify.run_weigh_reminders(NOW, 12)
    assert notify.run_weigh_reminders(NOW + timedelta(days=6, hours=23), 12) == []
    assert notify.run_weigh_reminders(NOW + timedelta(days=7), 12) == [uid]
    assert len(sent) == 2


def test_reminder_time_window(db, sent, notify):
    _setup_rem(db)
    _spool(db)
    for hour in (0, 8, 21, 23):
        assert notify.run_weigh_reminders(NOW, hour) == []
    assert db.get_notification_prefs(_uid(db))["weigh_reminder_last_at"] == ""
    assert notify.run_weigh_reminders(NOW, 9)          # first hour is inside
    assert sent


def test_reminder_window_last_hour_inside(db, sent, notify):
    _setup_rem(db)
    _spool(db)
    assert notify.run_weigh_reminders(NOW, 20)


def test_reminder_no_overdue_is_a_noop(db, sent, notify):
    uid = _setup_rem(db)
    a, _f = _spool(db)
    _weigh(db, a, 500)
    _age_reading(db, a, 2)
    assert notify.run_weigh_reminders(NOW, 12) == []
    assert sent == []
    assert db.get_notification_prefs(uid)["weigh_reminder_last_at"] == ""


def test_reminder_finished_spools_not_counted(db, sent, notify):
    _setup_rem(db)
    a, _f = _spool(db)
    db.deactivate_spool(a)
    assert notify.run_weigh_reminders(NOW, 12) == []


def test_reminder_needs_write_role_and_subscription(db, sent, notify):
    viewer = _viewer(db)                     # read-only, pref forced on in the DB
    _subscribe(db, viewer, FCM2)
    _prefs(db, viewer, rem=True)
    _prefs(db, _uid(db), rem=True)           # admin, but no subscription
    _spool(db)
    assert notify.run_weigh_reminders(NOW, 12) == []
    assert sent == []


def test_reminder_pref_off(db, sent, notify):
    uid = _uid(db)
    _subscribe(db, uid)
    _prefs(db, uid, rem=False)
    _spool(db)
    assert notify.run_weigh_reminders(NOW, 12) == []


def test_reminder_demo_mode(db, sent, notify, monkeypatch):
    _setup_rem(db)
    _spool(db)
    monkeypatch.setenv("DEMO_MODE", "1")
    assert notify.run_weigh_reminders(NOW, 12) == []


# ── Plumbing ─────────────────────────────────────────────────────────────────

def test_write_roles_match_the_app(app_module, notify):
    assert notify.WRITE_ROLES == app_module.WRITE_ROLES


def test_new_strings_have_en_and_es():
    import translations as i18n
    keys = ["Rolo acabando", "{name} (SP-{id}): {g} g restantes", "Último rolo",
            "Só resta 1 rolo de {name}", "Hora de pesar",
            "{n} rolos sem pesagem há mais de {days} dias",
            "1 rolo sem pesagem há mais de {days} dias"]
    assert all(k in i18n._EN and k in i18n._ES for k in keys)
    assert not [k for k in i18n._EN if k not in i18n._ES]


def test_cron_has_the_reminder_step():
    import pathlib
    src = (pathlib.Path(__file__).resolve().parent.parent / "deploy" / "backup-cron.py").read_text(
        encoding="utf-8")
    assert "notify.run_weigh_reminders()" in src and "weigh_reminder_step_failed" in src
