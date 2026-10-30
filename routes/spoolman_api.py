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
import hashlib
import json
import math
import re
from datetime import datetime, timezone

from flask import request, jsonify, redirect, url_for

import database as db
import filament_catalog
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


def _vendor_obj(brand_id, name, empty_spool_g):
    vendor = {"id": brand_id or 0, "name": name}
    if empty_spool_g:
        vendor["empty_spool_weight"] = _num(empty_spool_g)
    return vendor


def _filament_obj(d, fextra):
    """Spoolman filament object from a dict with the filament columns (+ brand_id,
    brand_empty_spool_g). Unknown values are omitted, never faked."""
    hex1, hex2 = _hex(d["color_hex"]), _hex(d["color_hex2"])
    filament = {
        "id": d["id"],
        "name": " ".join(x for x in (d["family"], d["color_name"]) if x).strip() or d["material"],
        "material": d["material"],
        "color_hex": hex1,
        "diameter": d["diameter_mm"],
        "density": d["density"],
        "weight": None if d["weight_g"] is None else _num(d["weight_g"]),
        "spool_weight": _num(d["spool_weight_g"]) if d["spool_weight_g"] else None,
        "article_number": d["article_number"] or None,
        "external_id": d["external_id"] or None,
        "settings_extruder_temp": d["extruder_temp"],
        "settings_bed_temp": d["bed_temp"],
        "comment": d.get("notes") or None,
        "extra": fextra,
    }
    if hex1 and hex2:
        filament["multi_color_hexes"] = f"{hex1},{hex2}"
        filament["multi_color_direction"] = "coaxial"
    if d["brand"]:
        filament["vendor"] = _vendor_obj(d["brand_id"], d["brand"], d["brand_empty_spool_g"])
    return {k: v for k, v in filament.items() if v is not None}


def _spool_obj(r, tags, extra, fextra):
    filament = _filament_obj({
        "id": r["filament_id"], "family": r["family"], "color_name": r["color_name"],
        "material": r["material"], "color_hex": r["color_hex"], "color_hex2": r["color_hex2"],
        "diameter_mm": r["diameter_mm"], "density": r["density"],
        "weight_g": r["filament_weight_g"], "spool_weight_g": r["filament_spool_weight_g"],
        "article_number": r["article_number"], "external_id": r["external_id"],
        "extruder_temp": r["extruder_temp"], "bed_temp": r["bed_temp"],
        "brand": r["brand"], "brand_id": r["brand_id"],
        "brand_empty_spool_g": r["brand_empty_spool_g"],
    }, fextra)
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
        "filament": filament,
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


# ── Filament database (spec 6.4, light form) ────────────────────────────────
# Served from the vendored SpoolmanDB snapshot (filament_catalog.py). The search route of
# the Spoolman form is deliberately absent (404): a server offers ONE form.

# Densities in g/cm3 for the plain materials only; composites (PLA-CF, PETG-GF...) differ
# and are left out rather than guessed. A trailing '+' is the same polymer.
_DENSITY = {"PLA": 1.24, "PETG": 1.27, "ABS": 1.04, "ASA": 1.07, "TPU": 1.21, "PC": 1.20,
            "PA": 1.14, "PVA": 1.23, "HIPS": 1.04, "PP": 0.90}


def _density(material):
    m = (material or "").strip().upper()
    return _DENSITY.get(m) or _DENSITY.get(m.rstrip("+"))


def _entry_id(e, hex6):
    raw = "|".join(str(x) for x in (e["brand"], e["material"], e.get("finish", ""),
                                    e.get("color", ""), hex6, e.get("diameter", "")))
    return "sdb-" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _catalog_entries(manufacturer=None, material=None, diameter=None):
    """Well formed entries of the snapshot, filtered (exact, case-insensitive) and
    ordered by name. Entries without a colour are not listed (6.4)."""
    maker = manufacturer.strip().lower() if manufacturer else None
    mat = material.strip().lower() if material else None
    seen, out = set(), []
    for e in filament_catalog.get_filaments():
        if maker and e["brand"].lower() != maker:
            continue
        if mat and e["material"].lower() != mat:
            continue
        dia = e.get("diameter") or 1.75
        if diameter is not None and abs(dia - diameter) > 1e-6:
            continue
        hex6 = (e.get("color_hex") or "").lstrip("#")
        if not re.fullmatch(r"[0-9A-Fa-f]{6}", hex6):
            continue
        eid = _entry_id(e, hex6)
        if eid in seen:
            continue
        seen.add(eid)
        finish, color = (e.get("finish") or "").strip(), (e.get("color") or "").strip()
        name = color if (not finish or finish.lower() in color.lower()) else f"{finish} {color}"
        entry = {"id": eid, "manufacturer": e["brand"], "material": e["material"],
                 "name": name, "color_hex": hex6.upper(), "diameter": dia}
        density = _density(e["material"])
        if density:
            entry["density"] = density
        out.append(entry)
    out.sort(key=lambda x: (x["manufacturer"].lower(), x["material"].lower(), x["name"].lower(), x["id"]))
    return out


def _diameter_arg():
    raw = request.args.get("diameter")
    try:
        return float(raw) if raw not in (None, "") else None
    except ValueError:
        return None


@_route("/api/v1/external/manufacturer", methods=["GET"])
def v1_external_manufacturer():
    if not filament_catalog.available():
        return _err("No filament database", 404)
    makers = {}
    for e in _catalog_entries(diameter=_diameter_arg()):
        m = makers.setdefault(e["manufacturer"], {})
        m[e["material"]] = m.get(e["material"], 0) + 1
    return jsonify([
        {"name": name, "count": sum(mats.values()),
         "materials": [{"name": k, "count": v} for k, v in sorted(mats.items())]}
        for name, mats in sorted(makers.items(), key=lambda kv: kv[0].lower())])


@_route("/api/v1/external/filament", methods=["GET"])
def v1_external_filament():
    if not filament_catalog.available():
        return _err("No filament database", 404)
    return jsonify(_catalog_entries(request.args.get("manufacturer"), request.args.get("material"),
                                    _diameter_arg()))


@_route("/api/v1/external/filament/search", methods=["GET"])
def v1_external_filament_search():
    return _err("Search is not offered; use /external/manufacturer and /external/filament", 404)


@_route("/api/v1/external/material", methods=["GET"])
def v1_external_material():
    names = {m for m in filament_catalog.get_materials() if _density(m)} | set(_DENSITY)
    return jsonify([{"material": m, "density": _density(m)} for m in sorted(names)])


# ── Creating vendor, filament, spool (spec 6.5, 7.2) ────────────────────────

def _unquote(value):
    """Spoolman's exact-match quoting: ?name="Polymaker". Bare text matches exactly too."""
    if value is None:
        return None
    v = value.strip()
    return v[1:-1] if len(v) >= 2 and v[0] == v[-1] == '"' else v


def _text(body, key, required=False, limit=200):
    v = body.get(key)
    if v is None:
        if required:
            raise _Invalid(f"{key} is required")
        return None
    if not isinstance(v, str):
        raise _Invalid(f"{key} must be a string")
    v = v.strip()
    if required and not v:
        raise _Invalid(f"{key} is required")
    if len(v) > limit:
        raise _Invalid(f"{key} is too long")
    return v


def _integer(body, key):
    v = _number(body, key)
    return None if v is None else int(round(v))


def _vendor_row_obj(row):
    return _vendor_obj(row["id"], row["name"], row["empty_spool_g"])


@_route("/api/v1/vendor", methods=["GET"])
def v1_vendor_list():
    return jsonify([_vendor_row_obj(r) for r in db.api_list_brands(_unquote(request.args.get("name")))])


@_route("/api/v1/vendor", methods=["POST"])
def v1_vendor_create():
    body = _json_body()
    name = _text(body, "name", required=True, limit=100)
    empty = _number(body, "empty_spool_weight")
    db.create_brand(name)   # INSERT OR IGNORE: an existing maker is returned, not duplicated
    if empty is not None:
        db.set_brand_empty_spool(name, empty)
    resp = jsonify(_vendor_row_obj(db.api_list_brands(name)[0]))
    resp.status_code = 201
    return resp


@_route("/api/v1/vendor/<int:vendor_id>", methods=["GET"])
def v1_vendor_get(vendor_id):
    row = db.get_brand_by_id(vendor_id)
    return jsonify(_vendor_row_obj(row)) if row else _err(f"No vendor with ID {vendor_id} found.", 404)


@_route("/api/v1/vendor/<int:vendor_id>", methods=["PATCH"])
def v1_vendor_patch(vendor_id):
    row = db.get_brand_by_id(vendor_id)
    if not row:
        return _err(f"No vendor with ID {vendor_id} found.", 404)
    body = _json_body()
    if "empty_spool_weight" in body:
        db.set_brand_empty_spool(row["name"], _number(body, "empty_spool_weight"))
    return jsonify(_vendor_row_obj(db.get_brand_by_id(vendor_id)))


@_route("/api/v1/vendor/<int:vendor_id>", methods=["DELETE"])
def v1_vendor_delete(vendor_id):
    row = db.get_brand_by_id(vendor_id)
    if not row:
        return _err(f"No vendor with ID {vendor_id} found.", 404)
    try:
        db.delete_brand(row["name"])
    except ValueError:
        return _err("Vendor still has filaments", 409)
    return jsonify({})


def _filament_response(filament_id):
    return _filament_obj(dict(db.api_get_filament(filament_id)),
                         db.filament_extra_map([filament_id])[filament_id])


@_route("/api/v1/filament", methods=["GET"])
def v1_filament_list():
    a = request.args
    rows = db.api_list_filaments(
        article_number=_unquote(a.get("article_number")), external_id=_unquote(a.get("external_id")),
        vendor_name=_unquote(a.get("vendor.name")), material=_unquote(a.get("material")),
        color_hex=_unquote(a.get("color_hex")))
    fextra = db.filament_extra_map([r["id"] for r in rows])
    return jsonify([_filament_obj(dict(r), fextra[r["id"]]) for r in rows])


@_route("/api/v1/filament/<int:filament_id>", methods=["GET"])
def v1_filament_get(filament_id):
    if not db.api_get_filament(filament_id):
        return _err(f"No filament with ID {filament_id} found.", 404)
    return jsonify(_filament_response(filament_id))


def _colour_columns(body):
    """(color_hex, color_hex2, translucent) from multi_color_hexes / color_hex, or None
    when the body names no colour. RRGGBBAA keeps the RGB; an alpha below FF = translucent."""
    multi = body.get("multi_color_hexes")
    if multi:
        parts = [p.strip().lstrip("#") for p in str(multi).split(",") if p.strip()]
        if not parts or not all(_HEX_RE.match(p) for p in parts):
            raise _Invalid("multi_color_hexes must be a comma list of RRGGBB")
        second = "#" + parts[1][:6] if len(parts) > 1 else ""
        return "#" + parts[0][:6], second, False
    if "color_hex" not in body:
        return None
    raw = body["color_hex"]
    if raw in (None, ""):
        return "", "", False
    raw = str(raw).lstrip("#")
    if not _HEX_RE.match(raw):
        raise _Invalid("color_hex must be RRGGBB or RRGGBBAA")
    return "#" + raw[:6], "", len(raw) == 8 and raw[6:].upper() != "FF"


def _filament_columns(body):
    """Validated API-only columns present in the body (null / 0 / '' = clear)."""
    cols = {}
    for key in ("article_number", "external_id"):
        if key in body:
            cols[key] = _text(body, key) or ""
    for key, col in (("density", "density"), ("weight", "weight_g"), ("spool_weight", "spool_weight_g")):
        if key in body:
            cols[col] = _number(body, key) or None
    for key, col in (("settings_extruder_temp", "extruder_temp"), ("settings_bed_temp", "bed_temp")):
        if key in body:
            cols[col] = _integer(body, key) or None
    if "comment" in body:
        cols["notes"] = _text(body, "comment", limit=2000) or ""
    return cols


@_route("/api/v1/filament", methods=["POST"])
def v1_filament_create():
    body = _json_body()
    name = _text(body, "name", required=True, limit=150)
    material = _text(body, "material", limit=50) or ""
    vendor_id = body.get("vendor_id")
    if isinstance(vendor_id, bool) or not isinstance(vendor_id, int):
        raise _Invalid("vendor_id is required")
    brand = db.get_brand_by_id(vendor_id)
    if not brand:
        return _err(f"No vendor with ID {vendor_id} found.", 404)
    diameter = _number(body, "diameter", strict=True) or 1.75
    colour = _colour_columns(body) or ("", "", False)
    cols = _filament_columns(body)
    extra = _extra_values(body)
    # Spoolman's `name` is product line + colour; ours is family (+ colour_name, left empty).
    fid = db.create_filament(brand["name"], material, name, color_hex=colour[0], color_name="",
                             diameter_mm=diameter, notes=cols.pop("notes", ""),
                             translucent=colour[2], color_hex2=colour[1])
    db.update_filament_api_fields(fid, **cols)
    if extra:
        db.merge_extra("filament_extra", fid, extra)
    resp = jsonify(_filament_response(fid))
    resp.status_code = 201
    return resp


@_route("/api/v1/filament/<int:filament_id>", methods=["PATCH"])
def v1_filament_patch(filament_id):
    if not db.api_get_filament(filament_id):
        return _err(f"No filament with ID {filament_id} found.", 404)
    body = _json_body()
    cols = _filament_columns(body)
    extra = _extra_values(body)
    db.update_filament_api_fields(filament_id, **cols)
    if extra:
        db.merge_extra("filament_extra", filament_id, extra)
    return jsonify(_filament_response(filament_id))


@_route("/api/v1/filament/<int:filament_id>", methods=["DELETE"])
def v1_filament_delete(filament_id):
    if not db.api_get_filament(filament_id):
        return _err(f"No filament with ID {filament_id} found.", 404)
    try:
        db.delete_filament(filament_id)
    except ValueError:
        return _err("Filament still has spools", 409)
    return jsonify({})


@_route("/api/v1/spool", methods=["POST"])
def v1_spool_create():
    body = _json_body()
    fid = body.get("filament_id")
    if isinstance(fid, bool) or not isinstance(fid, int):
        raise _Invalid("filament_id is required")
    filament = db.api_get_filament(fid)
    if not filament:
        return _err(f"No filament with ID {fid} found.", 404)
    initial = _number(body, "initial_weight", strict=True)
    remaining = _number(body, "remaining_weight")
    tare_in = _number(body, "spool_weight")
    location = body.get("location")
    if location is not None and not isinstance(location, str):
        raise _Invalid("location must be a string or null")
    last_used = _utc_stamp(body["last_used"]) if body.get("last_used") else ""
    comment = _text(body, "comment", limit=2000) or ""
    extra = _extra_values(body)
    if initial is None:   # spec 4.4: filament weight, else 1000 g
        initial = float(filament["weight_g"] or 1000)
    if remaining is not None and remaining > initial:
        initial = remaining
    spool_id = db.create_spool(fid, None, tare_in or None, initial, (location or "").strip(),
                               "", None, comment)
    if last_used:
        db.update_spool_api_fields(spool_id, last_used_at=last_used)
    if extra:
        db.merge_extra("spool_extra", spool_id, extra)
    if remaining is not None:
        tare = float(db.get_spool(spool_id)["effective_tare_g"] or 0)
        _apply_remaining(spool_id, remaining, tare)
    if body.get("archived") is True:
        db.deactivate_spool(spool_id)
    resp = jsonify(_one(spool_id))
    resp.status_code = 201
    return resp


@_route("/api/v1/spool/<int:spool_id>", methods=["DELETE"])
def v1_spool_delete(spool_id):
    if not db.get_spool(spool_id):
        return _err(f"No spool with ID {spool_id} found.", 404)
    db.delete_spool(spool_id)
    return jsonify({})


# ── Locations / spool page ───────────────────────────────────────────────────

@_route("/api/v1/location", methods=["GET"])
def v1_location_list():
    return jsonify(db.list_locations())


@app.route("/spool/show/<int:spool_id>")
def v1_spool_show(spool_id):
    """Page the scale links to (labels, QR). Outside /api/v1: normal login applies."""
    return redirect(url_for("spools_detail", spool_id=spool_id))
