"""Web Push: VAPID keys, subscription validation and the sender.

The VAPID key pair is generated the first time it is needed and kept in `data/vapid.json`
(mode 0600), next to the database but NOT in it: the backup zip carries `spool.db`, so a restore
on a fresh install does not bring the keys and the users simply enable notifications again. The
private key is never logged and never returned; only the public key leaves this module (the page
needs it to subscribe).

`send_to_user` is the only sender. `send_async` runs it in a daemon thread so a request (a weighing,
say) never waits on a push service. `pywebpush.webpush` is looked up on the module at call time so
tests can replace it.
"""
import base64
import ipaddress
import json
import os
import re
import tempfile
import threading
from urllib.parse import urlsplit

import pywebpush
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

import database as db
import logger as log_cfg

log = log_cfg.get_logger()

SEND_TIMEOUT = 10  # seconds; pywebpush has no default worth trusting

# The endpoint comes from the client and becomes a server-side POST (SSRF on the internal network
# otherwise): only the browsers' push services are accepted, exact host or a dot-anchored suffix.
PUSH_HOSTS = ("fcm.googleapis.com", "web.push.apple.com", "updates.push.services.mozilla.com")
PUSH_SUFFIXES = (".push.apple.com", ".notify.windows.com")

_B64URL = re.compile(r"^[A-Za-z0-9_-]+$")
_key_lock = threading.Lock()


class Invalid(ValueError):
    """The subscription the browser sent is not acceptable."""


def vapid_path():
    return db.DB_PATH.parent / "vapid.json"


def _b64url(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _read_keys(path):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        private, public = data["private"], data["public"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if isinstance(private, str) and isinstance(public, str) and private and public:
        return private, public
    return None


def vapid_keys():
    """(private, public), generating and saving the pair on first use. Race-safe between the
    gunicorn workers: the file is written to a temp name and hard-linked into place, which fails
    if another worker got there first (then that worker's pair is the one read back)."""
    path = vapid_path()
    keys = _read_keys(path)
    if keys:
        return keys
    with _key_lock:
        keys = _read_keys(path)
        if keys:
            return keys
        key = ec.generate_private_key(ec.SECP256R1())
        private = _b64url(key.private_numbers().private_value.to_bytes(32, "big"))
        public = _b64url(key.public_key().public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint))
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".vapid-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(json.dumps({"private": private, "public": public}))
            try:
                os.chmod(tmp, 0o600)
            except OSError:
                pass  # filesystems without POSIX modes
            try:
                os.link(tmp, path)
            except FileExistsError:
                pass
            except OSError:  # no hard links on this filesystem
                if not path.exists():
                    os.replace(tmp, path)
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass
        keys = _read_keys(path)
        if keys is None:
            raise RuntimeError("could not write the VAPID keys")
        log.info("push.vapid_generated")
        return keys


def public_key():
    """The public key (not secret; the page needs it to subscribe)."""
    return vapid_keys()[1]


def vapid_sub():
    """Identifies the sender to the push service (RFC 8292). The installation's public URL when it
    is https, WITHOUT a trailing slash or path (py_vapid's `_check_sub` anchors `$` right after the
    host and refuses "https://host/"); otherwise a `mailto:`."""
    # Same rule as app.public_base_url, repeated here so the hourly cron can send without
    # importing the whole Flask app.
    base = (db.get_setting("app_base_url", "") or "").strip()
    if not base or base == "http://localhost:5000":
        base = (os.environ.get("APP_BASE_URL", "") or "").strip() or base or "http://localhost:5000"
    parts = urlsplit(base)
    if parts.scheme == "https" and parts.netloc:
        return f"https://{parts.netloc}"
    return f"mailto:admin@{parts.hostname or 'localhost'}"


def _is_ip(host):
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


def parse_subscription(data):
    """(endpoint, p256dh, auth) from the JSON of the browser's `PushSubscription.toJSON()`."""
    if not isinstance(data, dict):
        raise Invalid("invalid subscription")
    keys = data.get("keys")
    endpoint = data.get("endpoint")
    p256dh = keys.get("p256dh") if isinstance(keys, dict) else None
    auth = keys.get("auth") if isinstance(keys, dict) else None
    if not all(isinstance(v, str) and v for v in (endpoint, p256dh, auth)):
        raise Invalid("incomplete subscription")
    parts = urlsplit(endpoint)
    if len(endpoint) > 2048 or parts.scheme != "https" or not parts.hostname:
        raise Invalid("endpoint must be https")
    host = parts.hostname.rstrip(".").lower()
    try:
        port = parts.port
    except ValueError:
        raise Invalid("unknown push service")
    if (parts.username is not None or parts.password is not None or port not in (None, 443)
            or _is_ip(host) or not (host in PUSH_HOSTS or host.endswith(PUSH_SUFFIXES))):
        raise Invalid("unknown push service")
    if len(p256dh) > 200 or len(auth) > 100 or not _B64URL.match(p256dh) or not _B64URL.match(auth):
        raise Invalid("unexpected key format")
    return endpoint, p256dh, auth


def device_kind(user_agent):
    """"Android" / "iPhone" / "computer" from a stored user agent (display only)."""
    ua = (user_agent or "").lower()
    if "android" in ua:
        return "Android"
    if "iphone" in ua or "ipad" in ua or "ipod" in ua:
        return "iPhone"
    return "computer"


def _send_one(sub, payload, private_key, sub_claim):
    """Outcome of one send: ok / expired / failed / error. Never returns the response body, the
    exception text or any key."""
    info = {"endpoint": sub["endpoint"], "keys": {"p256dh": sub["p256dh"], "auth": sub["auth"]}}
    claims = {"sub": sub_claim}  # fresh dict: pywebpush writes `aud` and `exp` into it
    try:
        resp = pywebpush.webpush(info, data=payload, vapid_private_key=private_key,
                                 vapid_claims=claims, timeout=SEND_TIMEOUT)
        status = getattr(resp, "status_code", 201)
    except pywebpush.WebPushException as e:
        status = getattr(getattr(e, "response", None), "status_code", None)
        if status is None:
            return {"result": "error", "detail": type(e).__name__}
    except Exception as e:  # connection error, timeout, bad key: only the class is reported
        return {"result": "error", "detail": type(e).__name__}
    if 200 <= status < 300:
        return {"result": "ok", "status": status}
    if status in (404, 410):
        return {"result": "expired", "status": status}
    return {"result": "failed", "status": status}


def send_to_user(user_id, title, body, url="/"):
    """Send the notification to every subscription of the user. One result per subscription, in
    order of creation: `{"kind", "result", "status"/"detail"}`. Expired ones (404/410) are deleted.
    Failures only log."""
    subs = db.list_push_subscriptions(user_id)
    if not subs:
        return []
    private_key, _ = vapid_keys()
    sub_claim = vapid_sub()
    payload = json.dumps({"title": title, "body": body, "url": url}, ensure_ascii=False)
    results = []
    for sub in subs:
        out = _send_one(sub, payload, private_key, sub_claim)
        if out["result"] == "ok":
            db.touch_push_subscription(sub["id"])
        elif out["result"] == "expired":
            db.drop_push_subscription(sub["id"])
        if out["result"] != "ok":
            log.warning("push.send_failed", user_id=user_id, host=urlsplit(sub["endpoint"]).hostname,
                        result=out["result"], status=out.get("status"), detail=out.get("detail"))
        out["kind"] = device_kind(sub["user_agent"])
        results.append(out)
    return results


def _safe_send(user_id, title, body, url):
    try:
        send_to_user(user_id, title, body, url)
    except Exception as e:
        log.warning("push.send_crashed", user_id=user_id, error=type(e).__name__)


def send_async(user_id, title, body, url="/"):
    """Fire and forget: runs `send_to_user` in a daemon thread. Returns the thread (tests join it)."""
    th = threading.Thread(target=_safe_send, args=(user_id, title, body, url), daemon=True)
    th.start()
    return th
