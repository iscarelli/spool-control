# Study: Autonomous weighing station (ESP32 + GM861-LED serial reader)

> **Status:** the **Flask side is implemented and validated** (API + public-URL guarantee,
> v1.13.x — see *Validation performed*). The **hardware** (GM861-LED + ESP32 + HX711) and
> the firmware are still pending purchase/build.
> Last updated: 2026-06-04.

## Context

Today spool weighing is manual: the operator opens `/weigh` (or `/spools/<id>/weigh`) in
the browser, scans/types the code and types the weight. The goal is a **physical autonomous
station**: the operator just **places the spool on the scale**. The presence of weight
triggers the QR read by the serial reader; the ESP32 extracts the `spool_id`, waits for the
weight to stabilize and `POST`s to Flask, which records the weighing. No computer needed.

The QR is generated in `labels.py` (`{app_base_url}/spools/{id}`). Chosen format: **the full
public URL (the domain) + higher ECC** (see *QR / label*).

> **Hardware decision (confirmed):** the **GM861-LED** reader — M25 thread (trivial rigid
> mounting in an enclosure), 3.3V (connects directly to the ESP32, no level shifter) and a
> fill light that helps read glossy labels. Triggered by **Command Triggered Mode** (serial
> command), not by camera.

---

## Hardware

| Component | Model | Notes |
|---|---|---|
| Microcontroller | **ESP32 DevKit (WROOM)** | free UART + spare GPIOs; no ESP32-CAM restriction |
| QR reader | **GM861-LED** | Serial TTL 3.3V @9600 8N1, M25 thread, fill light |
| ADC amplifier | **HX711** | 24-bit, for the load cell |
| Load cell | **TAL220B 5kg** | 4 wires → HX711 |
| Display (optional) | **SSD1306 OLED 0.96" I²C** | visual feedback to the operator |

### Wiring (ESP32 WROOM)

| Peripheral | Signal | ESP32 GPIO | Note |
|---|---|---|---|
| GM861-LED | VCC / GND | 3V3 / GND | module is 3.3V — no level shifter |
| GM861-LED | module TXD → ESP32 **RX2** | GPIO16 | UART2 |
| GM861-LED | module RXD ← ESP32 **TX2** | GPIO17 | UART2 |
| HX711 | DT / SCK | GPIO32 / GPIO33 | bit-bang via the `HX711` lib |
| OLED | SDA / SCL | GPIO21 / GPIO22 | standard I²C |

> UART0 (GPIO1/3, USB) stays free for debug; the GM861 is isolated on **UART2**.
> Pins 5 (D-) and 6 (D+) of the GM861 connector are USB — **do not use**; wire TTL only.

---

## QR / label (decided: URL + ECC, base = public domain)

The firmware only needs the `spool_id`. There's a trade-off between **human use** (scanning
with a phone opens the spool page) and **reader reliability** (shorter payload = QR with
fewer modules = larger modules at the same physical size = more robust reading at
distance/curvature/glare).

| Payload option | Phone opens page? | QR at the reader | Parsing on the ESP32 |
|---|---|---|---|
| **Full URL** (current) `https://spool.lojinharacer.com.br/spools/42` | ✅ | denser | regex `/spools/(\d+)` |
| **Bare ID** `42` | ❌ | more robust | direct `atoi` |
| **Prefixed** `SP42` / `s/42` | ❌ | robust | strip the prefix |

**Decision (confirmed):** the QR uses the **full public URL** — base
**`https://<your-domain>`** (the domain, never the internal IP or `localhost`, otherwise the
phone won't open the spool) — with **ECC** raised to M/Q. Parsing cost on the ESP32 is nil.

> ✅ **Public URL guaranteed at install time (implemented in v1.13.0):** `app_base_url` is
> seeded from the `APP_BASE_URL` env var at `init_db`, and `public_base_url()` falls back to
> that env var if the setting is empty/`localhost`. The installers no longer default to a
> third-party domain; without a domain they use the internal IP and warn it's LAN-only. It's
> editable in **Admin → Settings** (saving applies everywhere). (The `/spools/<id>` path is
> unchanged — only the base differs.)

> **Address (decided):** the **QR** and the **station's POST** use the same public domain
> (via Traefik). ESP32 implications:
> - `WiFiClientSecure` + `HTTPClient` over HTTPS;
> - on first bring-up, `client.setInsecure()` (skip cert validation); in production, pin the
>   **Let's Encrypt ISRG Root X1** CA via `setCACert()` (valid until ~2035);
> - ✅ **LAN reachability (confirmed):** the network has **split-DNS/hairpin**, so the domain
>   resolves to the Traefik node from inside the LAN and HTTPS works at the station.
>   (*Fallback* only if it ever stops: `SERVER` = `http://<LXC_IP>:8001`, plain HTTP on
>   Gunicorn, no TLS.)

> ✅ **Robust parsing:** the ESP32 must match `/spools/(\d+)` **anchored**, not "the first
> number in the string" (a URL with numbers in the host/port, e.g. `http://10.1.0.29:8001`,
> would otherwise yield `10`). The reference parser is in `tools/validate_qr_autoweigh.py`.

---

## Part 1 — Flask: JSON API endpoint (implemented)

No `database.py` changes needed. Reuses what already exists:
- `db.get_spool(spool_id)` — returns `brand`, `material`, `family`, `effective_tare_g`,
  `nominal_weight_g`, `current_net_g`, `last_weighed_at`.
- `db.add_weight_reading(spool_id, gross_weight_g, tare_weight_g, recorded_by, notes)`.
- `db.get_setting(key, default)`.

The logic mirrors the existing `/weigh` route — including the `gross < tare` check — but
responds with **JSON** and authenticates by **API key** instead of a session.

### Route: `POST /api/weigh` (in `app.py`)

```
Headers: Content-Type: application/json
         X-API-Key: <key>

Body: { "spool_id": 42, "gross_weight_g": 347.5 }

200: {
  "ok": true,
  "spool_id": 42,
  "filament": "eSUN PLA+ Vermelho",   // f"{brand} {material} {family}"
  "gross_weight_g": 347.5,
  "tare_g": 185.0,                     // effective_tare_g
  "net_weight_g": 162.5,
  "nominal_weight_g": 1000.0,
  "remaining_pct": 16.25
}

4xx: { "ok": false, "error": "message" }   // 401 key, 404 spool, 422 gross<tare, 400 body
```

### Route: `GET /api/spools/<id>`
Returns `filament`, `effective_tare_g`, `nominal_weight_g`, `current_net_g`,
`last_weighed_at` — for the OLED to show the spool **before** recording (visual confirmation).

### Implementation details (`app.py`)
- Reads the key from `os.environ.get("SPOOL_API_KEY", "")`. If empty, accepts without auth
  (eases local dev). Generated by default at install in `spool.env`.
- `recorded_by="estação"` (distinguishes station weighings from manual ones in the history).
- `nominal_weight_g` may be `None`/0 → guard the `remaining_pct` computation.
- **Not** `@login_required` (machine-to-machine, authenticated by key); CSRF-exempt.

---

## Part 2 — ESP32 firmware (the scale is the trigger)

### Libraries
`WiFi.h`, `WiFiClientSecure.h`, `HTTPClient.h`, `ArduinoJson`, `bogde/HX711`,
`Adafruit_SSD1306` (optional). GM861 reader: **no lib** — it's pure UART (`Serial2`).

### Configure the GM861-LED once
By default the module may come in automatic/continuous mode. Configure it to
**Command Triggered Mode** (manual §3.4) — by scanning the **configuration code** from the
manual or sending the setup command. From then on, each read is triggered by:

```
Trigger 1 read:    7E 00 08 01 00 02 01 AB CD
Module response:   02 00 00 01 00 33 31   (ack, then scans and returns the payload)
```

### State machine (main loop)

```
BOOT → connect WiFi → HX711.tare() (zero the empty scale)

STATE IDLE:
  - read HX711 (average of ~10 samples)
  - if weight > THRESHOLD (e.g. 50g)  → debounce ~300ms → state READING_QR

STATE READING_QR:
  - send 7E 00 08 01 00 02 01 AB CD on Serial2
  - wait for the payload up to a 10s timeout
  - extract spool_id (regex anchored on "/spools/(\d+)" — see QR section)
  - failed? → OLED "QR not read" → WAIT_REMOVAL

STATE WEIGHING:
  - wait for stability: |sample - average| ≤ 2g for 500ms
  - gross_weight_g = stable average

STATE SENDING:
  - HTTPS POST /api/weigh { spool_id, gross_weight_g } + X-API-Key header (via Traefik)
  - OLED shows "PLA+ Vermelho / 162.5g (16%)" from the response
  - network/TLS error → OLED "Network fail" → retry 1x

STATE WAIT_REMOVAL:
  - wait for weight < THRESHOLD (spool removed) → back to IDLE
  - (avoids re-triggering on the same spool)
```

### Firmware config (hardcoded or NVS)
```cpp
const char* WIFI_SSID = "...";
const char* WIFI_PASS = "...";
const char* SERVER    = "https://<your-domain>";   // POST via Traefik (HTTPS). LAN fallback: http://<LXC_IP>:8001
const char* API_KEY   = "...";                      // == SPOOL_API_KEY on the server
const float THRESHOLD_G = 50.0;
float SCALE_FACTOR    = 2280.0;   // calibrate with a known weight
```

---

## Implementation order

1. ~~**QR** — raise the ECC in `labels.py` (keeping `app_base_url` = public domain).~~ ✅ **done in v1.2.1** — `ERROR_CORRECT_M` → `ERROR_CORRECT_Q`
2. ~~**Flask** — add `POST /api/weigh` (+ `GET /api/spools/<id>`) in `app.py`.~~ ✅ **implemented (v1.13.0)** — CSRF-exempt, auth by `X-API-Key`==`SPOOL_API_KEY`, `recorded_by="estação"`; 400/401/404/422. **Public URL guaranteed at install:** `public_base_url()` + env seeding + installers with no third-party domain default (no domain → internal IP, "local network only" warning) + `SPOOL_API_KEY` generated in `spool.env`. Hardware-free validation: `tools/validate_qr_autoweigh.py`.
3. ~~**Test the API** via `curl` before touching hardware.~~ ✅ **done** — see *Validation performed*.
4. **ESP32** — wire HX711 + cell, calibrate (`SCALE_FACTOR`), validate weight reading.
5. **ESP32** — wire the GM861 on UART2, set Command Triggered Mode, test trigger+read.
6. **ESP32** — assemble the state machine; test with a real printed label.
7. **Deploy** — `SPOOL_API_KEY` is already in the server `spool.env`; rotate as needed.

---

## Validation performed (no hardware) — 2026-06-04

Everything validated in software, before buying the hardware (GM861-LED / ESP32 / HX711).

**QR — automated round-trip** (`tools/validate_qr_autoweigh.py`): generates the QR with the
same function as the label → decodes it (`cv2`, a proxy for the reader) → extracts the
`spool_id` anchored on `/spools/(\d+)`. Tested with **small and large codes** (SP-0001 …
SP-9999999) and with adversarial payloads — the parser is proof against numbers in the
host/port, querystring, route suffix and garbage (returns `None`, never a wrong id).

**Real label (printed PDF)** — QRs from actually exported labels (`spool-*.pdf`) decoded
with `pymupdf`+`cv2`:
- install **without a domain** → `http://<IP>:8001/spools/1`
- install **with a domain** → `https://spoolteste.lojinharacer.com.br/spools/1`
Layout checked visually (logo/brand, SP code, Material/Family/Color, "Local:").

**Weighing API** — `POST /api/weigh` and `GET /api/spools/<id>` validated:
`200` (ok), `401` (missing/wrong key), `404` (nonexistent spool), `422` (gross<tare),
`400` (invalid body). **Full round-trip simulating the ESP32** (QR from the real PDF →
extract id → `POST /api/weigh` with `X-API-Key` → `ok:true` with net/%), tested **via IP on
the LAN** and **via the domain (HTTPS/Traefik)**.

**Clean install** — install from scratch on a temporary LXC (Debian 12): service active,
`/health` 200, `app_base_url` **seeded from the environment** (IP/domain, never localhost),
`SPOOL_API_KEY` generated, "local network only" warning when there's no domain.
> **Bug found and fixed (v1.13.1):** `setup-inside.sh` copied a fixed file list and was
> missing `niimbot_registry.py` → a fresh install broke with `ModuleNotFoundError`. It now
> uses `git archive` of the whole tree.

**Traefik (domain route)** — validated after fixing a **router name collision**: the `spool`
name is **global** in Traefik, so the test LXC needs a unique name (e.g. `spooltest`). With
a unique name + non-indented labels, `https://<test-domain>/health` → 200, TLS OK.

---

## Reference manuals (in the `docs/` folder)

- `GM861 GM861-LED Barcode reader module User Manual-V1.2.4.pdf`
- `GM861S GM861S-LED Barcode reader module User Manual-V1.2.4.pdf`
- `GM861XS Barcode reader module User Manual-V1.1.2.pdf`
- `GM861XS-0 Barcode reader module User Manual-V1.1.2.pdf`

> All four support hardware trigger (§3.3.1, Level/Edge) **and** serial command trigger
> (§3.4, *Command Triggered Mode*). The **GM861-LED** was chosen for the M25 mount + 3.3V +
> fill light.
