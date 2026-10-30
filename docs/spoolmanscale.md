Código: routes/spoolman_api.py, database.py, routes/integrations.py, templates/admin/integrations.html, tests/test_spoolman_api.py

# SpoolmanScale integration (Spoolman-compatible API)

Spool Control answers the subset of the Spoolman 0.27 REST API that the
[SpoolmanScale](https://github.com/SpoolmanScale/ssi) scale uses (contract v1, "Part 1: inventory").
Everything lives under `/api/v1/` in `routes/spoolman_api.py`. Part 2 of the contract (AMS source) is
not implemented.

## Setup

1. Admin > Integrations > "SpoolmanScale": copy the key (Reveal / Copy).
2. On the scale: backend **Spoolman**, base URL = this server's public URL, API key = the key.

## Authentication

- Integration key `spoolmanscale`, scope write, created at boot (`app.py`, next to the other keys).
- Accepted as `X-API-Key`, `Authorization: Bearer <key>`, or HTTP Basic where the **password** is the
  key (user ignored): `routes/spoolman_api.py:33-49`.
- Every `/api/v1` route except `GET /api/v1/health` answers `401` JSON without it; a disabled or
  regenerated key stops working at once. No cookies, no CSRF, no redirects under `/api/v1`.
- `GET /spool/show/<id>` (outside `/api/v1`) redirects to the spool page and uses the normal login.

## What is served

- Inventory: `health`, `info`, `spool` (list with `allow_archived`, `limit`, `offset`, `sort`, `tag`,
  `extra.<key>`; `x-total-count` header), `spool/{id}` GET/PATCH/DELETE, `spool/{id}/measure`,
  `field/{spool|filament}`, `tag/reader` (always `[]`), `tag/scan`, `spool/{id}/tag` POST/DELETE,
  `location`.
- Filament database (light form only): `external/manufacturer`, `external/filament`,
  `external/material`, built from the vendored SpoolmanDB snapshot (`docs/spoolmandb.md`).
  `external/filament/search` answers `404`: a server offers one form. If the snapshot is
  unavailable, the discovery routes answer `404`.
- Create flow: `vendor`, `filament`, `spool` (GET/POST/PATCH/DELETE as applicable).

## Mapping and decisions where the contract was silent

- **Remaining weight is never faked.** `remaining_weight` is the latest weighing, or absent when the
  spool was never weighed (the UI shows such a spool as nominal; the API does not).
- **One tare.** The tare chain is custom tare, then spool model, then filament `spool_weight`, then
  maker `empty_spool_weight`, then 0 (`database.py` `EFFECTIVE_TARE_SQL`). The API reports it as
  `spool_weight` and subtracts the same value on `measure`, so the UI and the scale never disagree.
- **Writes become weighings.** `PATCH remaining_weight=N` stores a reading with the effective tare,
  `recorded_by = "SpoolmanScale"`, and reads back exactly `N`. `PUT measure` takes the gross weight.
- **Above the full weight, the spool is bigger.** A remaining or measured net above `initial_weight`
  raises the nominal weight to that value.
- **Archive = finish.** `archived=true` finishes the spool like the UI does; `false` reactivates it.
- **Status codes.** `422` for invalid values (negative or non-numeric weights, `limit`/`offset`,
  gross weight below the tare, same as `/api/weigh`); `400` for malformed bodies and bad extra-field
  keys (`[a-z0-9_]+`); `404` for unknown ids; `409` for a tag already linked (body carries
  `spool_id`) and for deleting a vendor with filaments or a filament with spools. Validation runs
  before any write, so a `422` never leaves a half-applied PATCH.
- **Extra fields.** Any key is accepted on PATCH and is listed by `field/spool` once held (contract
  7.1, option b). Values are JSON-encoded strings; `"\"\""` clears a key. Unlinking a tag also clears
  that UID from the companion keys `tag`, `nfc_id`, `card_uids` (comma list) and `rfid_tag`.
- **Tags** are stored in `spool_tags` (UID normalised to uppercase hex).
- **Vendor ids** come from `brands.vendor_id`, not `rowid`: `brands` has a text primary key, so rowids
  can renumber on VACUUM or restore, and the scale caches vendor ids. Backfilled once from rowid;
  a trigger gives every new brand `max(vendor_id)+1`; unique index `idx_brands_vendor_id`.
- **Vendor POST dedupes by name** (case-insensitive): an existing maker is returned, not duplicated.
- **Filament POST** maps `name` to the family, leaves the colour name empty, and takes the first two
  `multi_color_hexes` as `color_hex` / `color_hex2`. **Spool POST**: `initial_weight` defaults to the
  filament weight, else 1000 g; `remaining_weight` becomes the first reading.
- **Filament database entries.** Ids are stable strings, `sdb-` plus the first 16 hex of a SHA-1 over
  maker, material, finish, colour, hex and diameter. Density comes from a small table of plain
  materials (PLA 1.24, PETG 1.27, ABS 1.04, ASA 1.07, TPU 1.21, PC 1.20, PA 1.14, PVA 1.23, HIPS 1.04,
  PP 0.90 g/cm3); composites are left out rather than guessed.

## Schema (automatic, idempotent)

`spools.last_used_at`, tables `spool_tags`, `spool_extra`, `filament_extra`, `extra_fields`;
`filaments` gains `article_number`, `external_id`, `density`, `weight_g`, `spool_weight_g`,
`extruder_temp`, `bed_temp`; `brands` gains `empty_spool_g` and `vendor_id`. All through the ALTER
try/except list in `database.py` `init_db`, so installations update from the web with no console.

## Checking it

The contract ships a checker (`check/check_inventory.py` in the ssi repo). With a local server and
two spools:

```
python check_inventory.py http://127.0.0.1:5000 --key <key> --write --spool A --spool-b B
```

Tests: `tests/test_spoolman_api.py`.
