"""API compatible with the subset of Spoolman 0.27 that SpoolmanScale uses.

Contract: https://github.com/SpoolmanScale/ssi (Part 1, inventory). Everything lives
under /api/v1/. Machine-to-machine: no session, no cookies, no CSRF, no redirects,
authenticated by the `spoolmanscale` integration key (Admin -> Integrations) sent as
X-API-Key, Authorization: Bearer, or HTTP Basic (the PASSWORD is the key; user ignored).

The tare reported in a spool object is the ONE tare the server subtracts on measure
(`effective_tare_g`), so the scale and the UI never show different weights.
Docs: docs/spoolmanscale.md.
"""
import base64
import json
import math
import re
from datetime import datetime, timezone

from flask import request, jsonify, redirect, url_for

import database as db
from app import app, csrf, current_version

INTEGRATION = "spoolmanscale"
RECORDED_BY = "SpoolmanScale"
_KEY_RE = re.compile(r"^[a-z0-9_]+$")
_HEX_RE = re.compile(r"^[0-9A-Fa-f]{6}([0-9A-Fa-f]{2})?$")


# ── Auth (every /api/v1 route except health) ─────────────────────────────────

def _presented_key():
    key = request.headers.get("X-API-Key", "").strip()
    if key:
        return key
    auth = request.headers.get("Authorization", "").strip()
    scheme, _, rest = auth.partition(" ")
    rest = rest.strip()
    if scheme.lower() == "bearer":
        return rest
    if scheme.lower() == "basic":
        try:
            decoded = base64.b64decode(rest, validate=False).decode("utf-8")
        except Exception:
            return ""
        return decoded.partition(":")[2]
    return ""


@app.before_request
def _v1_auth():
    path = request.path
    if path != "/api/v1" and not path.startswith("/api/v1/"):
        return None
    if path == "/api/v1/health":
        return None
    write = request.method not in ("GET", "HEAD", "OPTIONS")
    if db.verify_api_key(_presented_key(), need_write=write) != INTEGRATION:
        resp = jsonify(message="Invalid or missing API key")
        resp.status_code = 401
        resp.headers["WWW-Authenticate"] = 'Basic realm="spool-control"'
        return resp
    try:
        db.touch_api_key(INTEGRATION)
    except Exception:
        pass  # last_used is best-effort
    return None


def _route(rule, **kw):
    """app.route + CSRF exemption (the scale sends no token)."""
    def deco(fn):
        return app.route(rule, **kw)(csrf.exempt(fn))
    return deco


def _err(message, status):
    resp = jsonify(message=message)
    resp.status_code = status
    return resp


# ── Spool object ─────────────────────────────────────────────────────────────

def _num(x):
    """Whole numbers as ints, others rounded to 3 decimals (JSON numbers either way)."""
    x = round(float(x), 3)
    return int(x) if x == int(x) else x


def _hex(value):
    value = (value or "").lstrip("#")
    return value if _HEX_RE.match(value) else None


def _spool_objects(rows):
    ids = [r["id"] for r in rows]
    fids = sorted({r["filament_id"] for r in rows})
    tags = db.spool_tags_map(ids)
    extra = db.spool_extra_map(ids)
    fextra = db.filament_extra_map(fids)
    return [_spool_obj(r, tags[r["id"]], extra[r["id"]], fextra[r["filament_id"]]) for r in rows]


def _one(spool_id):
    row = db.get_spool(spool_id)
    return _spool_objects([row])[0] if row else None


def _spool_obj(r, tags, extra, fextra):
    hex1, hex2 = _hex(r["color_hex"]), _hex(r["color_hex2"])
    filament = {
        "id": r["filament_id"],
        "name": " ".join(x for x in (r["family"], r["color_name"]) if x).strip() or r["material"],
        "material": r["material"],
        "color_hex": hex1,
        "diameter": r["diameter_mm"],
        "extra": fextra,
    }
    if hex1 and hex2:
        filament["multi_color_hexes"] = f"{hex1},{hex2}"
        filament["multi_color_direction"] = "coaxial"
    if r["brand"]:
        filament["vendor"] = {"id": r["brand_id"] or 0, "name": r["brand"]}
    tare = float(r["effective_tare_g"] or 0)
    last_used = max(r["last_used_at"] or "", r["last_weighed_at"] or "") or None
    obj = {
        "id": r["id"],
        "archived": not r["active"],
        "registered": r["created_at"],
        "first_used": r["created_at"],
        "last_used": last_used,
        "remaining_weight": None if r["current_net_g"] is None else _num(r["current_net_g"]),
        "initial_weight": _num(r["nominal_weight_g"]),
        "spool_weight": _num(tare) if tare > 0 else None,
        "location": r["location"] or None,
        "extra": extra,
        "tags": tags,
        "filament": {k: v for k, v in filament.items() if v is not None},
    }
    return {k: v for k, v in obj.items() if v is not None}


# ── Input parsing ────────────────────────────────────────────────────────────

class _Invalid(Exception):
    def __init__(self, message, status=422):
        super().__init__(message)
        self.status = status


def _number(body, key, minimum=0.0, strict=False):
    """Value of a numeric field, None when absent or null. strict: must be > minimum."""
    v = body.get(key)
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        raise _Invalid(f"{key} must be a number")
    if v < minimum or (strict and v == minimum):
        raise _Invalid(f"{key} is out of range")
    return float(v)


def _utc_stamp(text):
    """Normalise an ISO 8601 date/datetime (date alone = midnight UTC) to ...Z."""
    s = str(text).strip()
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
            dt = datetime.fromisoformat(s + "T00:00:00")
        else:
            dt = datetime.fromisoformat(re.sub(r"[zZ]$", "+00:00", s))
    except ValueError:
        raise _Invalid("invalid date")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _extra_values(body):
    raw = body.get("extra")
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise _Invalid("extra must be an object")
    out = {}
    for key, value in raw.items():
        if not _KEY_RE.match(str(key)):
            raise _Invalid(f"invalid extra field key {key!r}", 400)
        out[key] = value if isinstance(value, str) else json.dumps(value)
    return out


def _json_body():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise _Invalid("body must be a JSON object", 400)
    return body


@app.errorhandler(_Invalid)
def _handle_invalid(e):
    return _err(str(e), e.status)


# ── Health / info ────────────────────────────────────────────────────────────

@_route("/api/v1/health", methods=["GET"])
def v1_health():
    return jsonify(status="healthy")


@_route("/api/v1/info", methods=["GET"])
def v1_info():
    return jsonify(version=current_version())


# ── Spool list / get ─────────────────────────────────────────────────────────

@_route("/api/v1/spool", methods=["GET"])
def v1_spool_list():
    args = request.args
    allow_archived = args.get("allow_archived", "false").lower() in ("true", "1")
    try:
        limit = int(args["limit"]) if "limit" in args else None
        offset = int(args.get("offset", 0))
    except ValueError:
        return _err("limit and offset must be integers", 422)
    if (limit is not None and limit < 0) or offset < 0:
        return _err("limit and offset must not be negative", 422)
    extra_filters = {k[len("extra."):]: v for k, v in args.items()
                     if k.startswith("extra.") and _KEY_RE.match(k[len("extra."):])}
    rows, total = db.api_list_spools(
        allow_archived=allow_archived, tag=args.get("tag"),
        extra_filters=extra_filters, sort=args.get("sort", "id:asc"),
        limit=limit, offset=offset)
    resp = jsonify(_spool_objects(rows))
    resp.headers["x-total-count"] = str(total)
    return resp


@_route("/api/v1/spool/<int:spool_id>", methods=["GET"])
def v1_spool_get(spool_id):
    obj = _one(spool_id)
    return jsonify(obj) if obj else _err(f"No spool with ID {spool_id} found.", 404)


# ── Writing a spool ──────────────────────────────────────────────────────────

def _apply_remaining(spool_id, net, tare):
    """Store `net` as the latest reading: gross = net + tare, so it reads back exactly."""
    db.add_weight_reading(spool_id, net + tare, tare, recorded_by=RECORDED_BY)


@_route("/api/v1/spool/<int:spool_id>", methods=["PATCH"])
def v1_spool_patch(spool_id):
    spool = db.get_spool(spool_id)
    if not spool:
        return _err(f"No spool with ID {spool_id} found.", 404)
    body = _json_body()

    # Validate everything first so a 422 never leaves a half-applied write.
    initial = _number(body, "initial_weight", strict=True)
    remaining = _number(body, "remaining_weight")
    archived = body.get("archived")
    if archived is not None and not isinstance(archived, bool):
        raise _Invalid("archived must be a boolean")
    fields = {}
    if initial is not None:
        fields["nominal_weight_g"] = initial
    if "spool_weight" in body:
        tare_in = _number(body, "spool_weight")
        fields["custom_tare_g"] = tare_in or None   # null / 0 = unset
    if "location" in body:
        loc = body["location"]
        if loc is not None and not isinstance(loc, str):
            raise _Invalid("location must be a string or null")
        fields["location"] = (loc or "").strip()
    if "last_used" in body:
        lu = body["last_used"]
        fields["last_used_at"] = "" if lu is None else _utc_stamp(lu)
    extra = _extra_values(body)

    db.update_spool_api_fields(spool_id, **fields)
    if extra:
        db.merge_extra("spool_extra", spool_id, extra)

    if remaining is not None:
        spool = db.get_spool(spool_id)
        nominal = float(spool["nominal_weight_g"] or 0)
        if remaining > nominal:   # above the full weight: the spool is simply bigger (4.5)
            db.update_spool_api_fields(spool_id, nominal_weight_g=remaining)
        _apply_remaining(spool_id, remaining, float(spool["effective_tare_g"] or 0))

    if archived is not None:
        active = bool(db.get_spool(spool_id)["active"])
        if archived and active:
            db.deactivate_spool(spool_id)
        elif not archived and not active:
            db.reactivate_spool(spool_id)
    return jsonify(_one(spool_id))


@_route("/api/v1/spool/<int:spool_id>/measure", methods=["PUT"])
def v1_spool_measure(spool_id):
    spool = db.get_spool(spool_id)
    if not spool:
        return _err(f"No spool with ID {spool_id} found.", 404)
    weight = _number(_json_body(), "weight")
    if weight is None:
        raise _Invalid("weight is required")
    tare = float(spool["effective_tare_g"] or 0)
    if weight < tare:
        raise _Invalid(f"Gross weight ({weight:g} g) is below the tare ({tare:g} g)")
    net = weight - tare
    if net > float(spool["nominal_weight_g"] or 0):
        db.update_spool_api_fields(spool_id, nominal_weight_g=net)
    db.update_spool_api_fields(spool_id, last_used_at=db.now_iso())
    db.add_weight_reading(spool_id, weight, tare, recorded_by=RECORDED_BY)
    return jsonify(_one(spool_id))


# ── Extra fields ─────────────────────────────────────────────────────────────

@_route("/api/v1/field/<entity>", methods=["GET"])
def v1_field_list(entity):
    if entity not in ("spool", "filament"):
        return _err("Unknown entity", 404)
    return jsonify(db.list_extra_fields(entity))


@_route("/api/v1/field/<entity>/<key>", methods=["POST"])
def v1_field_create(entity, key):
    if entity not in ("spool", "filament"):
        return _err("Unknown entity", 404)
    if not _KEY_RE.match(key):
        return _err("Field key must match [a-z0-9_]+", 400)
    body = request.get_json(silent=True)
    body = body if isinstance(body, dict) else {}
    db.upsert_extra_field(entity, key, str(body.get("name") or key),
                          str(body.get("field_type") or "text"),
                          str(body.get("default_value") or ""))
    return jsonify(db.list_extra_fields(entity))


# ── Tags ─────────────────────────────────────────────────────────────────────

@_route("/api/v1/tag/reader", methods=["GET"])
def v1_tag_reader():
    return jsonify([])   # probe: native tags are implemented; no hardware readers here


@_route("/api/v1/tag/scan", methods=["POST"])
def v1_tag_scan():
    uid = db.normalise_tag_uid(_json_body().get("uid"))
    owner = db.get_tag_owner(uid) if uid else None
    obj = _one(owner) if owner else None
    if not obj:
        return jsonify(matched_spool_id=None)
    return jsonify(matched_spool_id=owner, spool=obj)   # never writes (spec 5.1)


@_route("/api/v1/spool/<int:spool_id>/tag", methods=["POST"])
def v1_tag_link(spool_id):
    if not db.get_spool(spool_id):
        return _err(f"No spool with ID {spool_id} found.", 404)
    body = _json_body()
    uid = db.normalise_tag_uid(body.get("uid"))
    if not uid:
        raise _Invalid("uid must contain hex digits")
    owner = db.get_tag_owner(uid)
    if owner is not None and owner != spool_id:
        resp = jsonify(message=f"Tag {uid} is already linked to spool {owner}.", spool_id=owner)
        resp.status_code = 409
        return resp
    db.link_tag(spool_id, uid, body.get("format"))
    return jsonify(_one(spool_id))


def _decoded(value):
    try:
        v = json.loads(value)
    except (TypeError, ValueError):
        return str(value)
    return v if isinstance(v, str) else str(value)


def _clear_companion_fields(spool_id, uid):
    """Take `uid` out of every tag field of the spool that names it (spec 7.1)."""
    held = db.spool_extra_map([spool_id])[spool_id]
    changes = {}
    for key in ("tag", "nfc_id"):                 # single value: clear
        if key in held and db.normalise_tag_uid(_decoded(held[key])) == uid:
            changes[key] = '""'
    for key in ("card_uids", "rfid_tag"):         # comma list: drop that entry
        if key not in held:
            continue
        parts = [p for p in re.split(r"[,;\s]+", _decoded(held[key])) if p]
        kept = [p for p in parts if db.normalise_tag_uid(p) != uid]
        if len(kept) != len(parts):
            changes[key] = json.dumps(",".join(kept)) if kept else '""'
    if changes:
        db.merge_extra("spool_extra", spool_id, changes)


@_route("/api/v1/spool/<int:spool_id>/tag/<path:uid>", methods=["DELETE"])
def v1_tag_unlink(spool_id, uid):
    if not db.get_spool(spool_id):
        return _err(f"No spool with ID {spool_id} found.", 404)
    uid = db.normalise_tag_uid(uid)
    if not db.unlink_tag(spool_id, uid):
        return _err(f"Tag {uid} is not linked to spool {spool_id}.", 404)
    _clear_companion_fields(spool_id, uid)
    return jsonify(_one(spool_id))


# ── Locations / spool page ───────────────────────────────────────────────────

@_route("/api/v1/location", methods=["GET"])
def v1_location_list():
    return jsonify(db.list_locations())


@app.route("/spool/show/<int:spool_id>")
def v1_spool_show(spool_id):
    """Page the scale links to (labels, QR). Outside /api/v1: normal login applies."""
    return redirect(url_for("spools_detail", spool_id=spool_id))
