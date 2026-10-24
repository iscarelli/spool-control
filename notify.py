"""Push notification triggers: who gets which alert, and when.

Delivery (keys, subscriptions, the sender) is in push.py; this module decides. Three alerts, each
switchable per user in `notification_prefs`:

- low stock   (`after_weighing`): a weighing takes a spool's remaining filament from >= N g to < N g.
- last spool  (`after_finish`):   finishing a spool leaves exactly one active spool of the filament.
- weigh reminder (`run_weigh_reminders`): hourly, from deploy/backup-cron.py.

Imports nothing from Flask or app.py so the cron can use it. Request-time alerts go through
`push.send_async` (a request never waits on a push service); the cron uses the synchronous sender.
Users have no stored language, so texts are Portuguese; `_tr` takes the language so a future
column only needs to pass it. Every trigger swallows its own errors: an alert must never break a
weighing or a finish.
"""
import os
from datetime import datetime, timedelta, timezone

import database as db
import logger as log_cfg
import push
from translations import get_translator

log = log_cfg.get_logger()

# Same as app.WRITE_ROLES (a test keeps them equal); repeated because app.py cannot be imported here.
WRITE_ROLES = ("admin",)

REMINDER_FIRST_HOUR, REMINDER_LAST_HOUR = 9, 21  # local server time: 09:00 <= now < 21:00


def _demo():
    return os.environ.get("DEMO_MODE", "0") == "1"


def _tr(lang=None):
    return get_translator(lang or "pt")


def _filament_name(row):
    parts = [row["brand"], row["material"], row["family"], (row["color_name"] or "")]
    return " ".join(p.strip() for p in parts if p and p.strip())


def _grams(value):
    return f"{float(value):.0f}"


def after_weighing(spool_id):
    """Low-stock alert, called by `database.add_weight_reading` after the reading is stored."""
    if _demo():
        return
    try:
        spool = db.get_spool(spool_id)
        if not spool or not spool["active"] or spool["current_net_g"] is None:
            return
        remaining = float(spool["current_net_g"])
        for pref in db.list_notification_recipients("low_stock_on"):
            uid = pref["user_id"]
            if remaining < pref["low_stock_g"]:
                if db.mark_low_stock_notified(uid, spool_id):
                    _ = _tr()
                    push.send_async(
                        uid, _("Rolo acabando"),
                        _("{name} (SP-{id}): {g} g restantes").format(
                            name=_filament_name(spool), id=f"{spool_id:04d}", g=_grams(remaining)),
                        f"/spools/{spool_id}")
            else:
                db.clear_low_stock_notified(uid, spool_id)
    except Exception as e:
        log.warning("notify.low_stock_failed", spool_id=spool_id, error=type(e).__name__)


def after_finish(spool_id):
    """Last-spool alert, called by `database.deactivate_spool` after the spool is finished."""
    if _demo():
        return
    try:
        spool = db.get_spool(spool_id)
        if not spool:
            return
        if db.count_active_spools_of_filament(spool["filament_id"]) != 1:
            return
        _ = _tr()
        title = _("Último rolo")
        body = _("Só resta 1 rolo de {name}").format(name=_filament_name(spool))
        for pref in db.list_notification_recipients("last_spool_on"):
            push.send_async(pref["user_id"], title, body, f"/filaments/{spool['filament_id']}")
    except Exception as e:
        log.warning("notify.last_spool_failed", spool_id=spool_id, error=type(e).__name__)


def _parse_iso(ts):
    try:
        return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def run_weigh_reminders(now_utc=None, local_hour=None):
    """Hourly step. Returns the user ids that were notified. `now_utc` / `local_hour` are for tests."""
    if _demo():
        return []
    now = now_utc or datetime.now(timezone.utc)
    hour = datetime.now().hour if local_hour is None else local_hour
    if not (REMINDER_FIRST_HOUR <= hour < REMINDER_LAST_HOUR):
        return []
    sent = []
    for pref in db.list_notification_recipients("weigh_reminder_on"):
        uid, days = pref["user_id"], pref["weigh_reminder_days"]
        if pref["role"] not in WRITE_ROLES or not db.list_push_subscriptions(uid):
            continue
        last = _parse_iso(pref["weigh_reminder_last_at"])
        if last and now - last < timedelta(days=days):
            continue
        cutoff = (now - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
        n = db.count_spools_unweighed_since(cutoff)
        if not n:
            continue
        _ = _tr()
        body = (_("1 rolo sem pesagem há mais de {days} dias") if n == 1
                else _("{n} rolos sem pesagem há mais de {days} dias")).format(n=n, days=days)
        push.send_to_user(uid, _("Hora de pesar"), body, "/spools")
        db.set_weigh_reminder_last_at(uid, now.strftime("%Y-%m-%dT%H:%M:%SZ"))
        sent.append(uid)
    return sent
