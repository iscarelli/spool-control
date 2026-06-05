# Spool Control

Web app for managing 3D-printing filaments.

Register filaments, catalog spools, weigh them with automatic tare subtraction,
print 60×40mm thermal labels with a QR code, and get stock reports.

## Features

- Filament registry (material, brand, family, color) with automatic brand logos
- Multiple spools per filament with a full weighing history
- Quick weigh: enter the spool code and the gross weight — the system subtracts the tare
- 60×40mm PDF labels with a QR code (points to the spool page — login required)
- Batch label print queue
- Reports: by material, by location, low stock, weight history
- Search and sorting on listings
- Authentication with access control (admin / viewer)
- Multi-language UI: **Portuguese, English and Spanish** (see [Languages (i18n)](#languages-i18n))
- Weighing API for automatic stations (`POST /api/weigh`) — see [Weighing API](#weighing-api)

## Stack

| Layer | Technology |
|---|---|
| Backend | Flask 3.x + Gunicorn |
| Database | SQLite (WAL mode) |
| Frontend | Bootstrap 5.3 + Bootstrap Icons |
| Labels | ReportLab + qrcode + Pillow |
| Deploy | Systemd + Traefik |

## Structure

```
spool-control/
├── app.py              # Flask routes
├── database.py         # SQLite schema and helpers
├── labels.py           # Label PDF / thermal PNG generation
├── translations.py     # UI translations (i18n: PT/EN/ES)
├── requirements.txt
├── static/
│   ├── spool.css
│   ├── spool.js        # Client-side filter and sorting
│   ├── spool-icon.svg
│   └── brands/         # Brand logos (generated at deploy)
├── templates/
├── tools/
│   └── validate_qr_autoweigh.py  # Validate the QR/auto-weigh flow without hardware
└── deploy/
    ├── proxmox-deploy.sh   # Proxmox LXC installer (creates the container + installs)
    ├── spool-control.service
    ├── setup-inside.sh     # Install inside the LXC (public clone + venv + systemd)
    ├── update-lxc.sh       # Update via git archive
    └── seed_brands.py      # Download brand logos
```

`data/spool.db` and `spool.env` live outside git (generated on the server).

## Public URL / domain (important)

The label **QR code encodes `<app_base_url>/spools/<id>`**, so `app_base_url` must be the
URL that will actually be reached when the QR is scanned (phone, or the automatic weighing
station). Each install runs on **its own server**, so this is per-install:

- **With a public domain** (behind an HTTPS proxy): the QR uses `https://your.domain` and
  works from anywhere.
- **Without a domain**: the install falls back to the internal IP (`http://IP:8001`) and
  the installer warns that it works on the **local network only** — QR codes won't open
  from outside the LAN.

You can change it anytime in **Admin → Settings → "Base URL"**; saving applies everywhere
(QR codes, labels, links). On a fresh install the value is seeded from the `APP_BASE_URL`
set by the installer — never `localhost`.

## Languages (i18n)

The UI is available in **Portuguese (PT-BR)**, **English (EN)** and **Spanish (ES)**,
selectable from the flag at the top. Translations live in **`translations.py`** (tables
`_EN`/`_ES`/`_PT`).

The step-by-step to **add a new language** is in [`docs/i18n.md`](docs/i18n.md).

## Weighing API

Machine-to-machine endpoints for an automatic weighing station (e.g. a scale + QR reader +
ESP32 — see [`docs/estudo_balanca_qrcode.md`](docs/estudo_balanca_qrcode.md)).
Authenticated by `X-API-Key` (== the `SPOOL_API_KEY` env var, generated at install; if
empty the API is open — dev/LAN only). CSRF-exempt.

- `POST /api/weigh` — body `{"spool_id": 1, "gross_weight_g": 532}` → records the weighing
  (`net = gross − tare`) and returns JSON with `net_weight_g` and `remaining_pct`.
- `GET /api/spools/<id>` — spool data (read-only) for confirmation before recording.

```bash
curl -X POST https://your.domain/api/weigh \
  -H "X-API-Key: <key>" -H "Content-Type: application/json" \
  -d '{"spool_id":1,"gross_weight_g":532}'
```

The station reads the QR, extracts the spool id (anchored on `/spools/(\d+)`) and POSTs.
The full flow can be validated without hardware via `tools/validate_qr_autoweigh.py`.

## Deploy — Proxmox LXC

### Automatic install (recommended)

Run it **on the Proxmox VE host** (PVE 7+). The installer creates a Debian 12 LXC and
configures the whole system, asking for CTID, hostname, network, resources and URL:

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/iscarelli/spool-control/main/deploy/proxmox-deploy.sh)"
```

At the end it prints the IP, the access URL and the **initial admin password**. The
repository is public — no GitHub credentials needed.

> If you provide a **domain** (behind an HTTPS proxy) it enables `SECURE_COOKIES=1` and the
> QR uses `https://your.domain`. **Without a domain** it uses the internal IP
> (`http://IP:8001`) — **local network only** (see [Public URL / domain](#public-url--domain-important)).

### Manual install (alternative)

On an existing Debian 12 LXC, as root:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/iscarelli/spool-control/main/deploy/setup-inside.sh)
```

Optional variables: `DOMAIN`, `APP_BASE_URL`, `SECURE_COOKIES`, `USE_BR_MIRROR`,
`ADMIN_DEFAULT_PASS`. The script installs dependencies, clones the repository
(anonymously), creates the virtualenv, configures the systemd service and prints the
initial admin password. It also generates a `SPOOL_API_KEY`.

### Configure HTTPS via Traefik (Proxmox Provider)

Traefik reads the LXC **Notes** field via the Proxmox API. Configure it like this:

```bash
pct set <VMID> -description $'traefik.enable=true
traefik.http.routers.spool.rule: Host(`spool.example.com`)
traefik.http.routers.spool.entrypoints=websecure
traefik.http.routers.spool.tls.certresolver=letsencrypt
traefik.http.services.spool.loadbalancer.server.url: http://<LXC_IP>:8001'
```

> **Label format:** use `=` for simple values and `: ` (with a space) when the value
> contains `:` (URLs and Host rules).
>
> **Unique names:** the router/service name (`spool` above) is **global** in Traefik —
> if you run more than one instance, give each a unique name (e.g. `spool`, `spooltest`),
> otherwise the routers collide and one of them returns 404.

Wait ~30s for Traefik to pick up the route. Check it at `https://spool.example.com/health`.

### Future updates

**Via the web UI (recommended):** in **Admin → Updates** (`/admin/update`), the admin sees
the current version vs. the latest release and updates with one click. A menu badge signals
when a new version is available.

**Via the command line** (alternative / recovery):

```bash
pct exec <VMID> -- bash /opt/spool-control/deploy/update-lxc.sh
# roll back to a specific tag/branch:
pct exec <VMID> -- bash /opt/spool-control/deploy/update-lxc.sh --ref v1.5.0
```

### Download brand logos

After the first access, run this to download logos for the best-known brands:

```bash
pct exec <VMID> -- /opt/spool-control/.venv/bin/python3 /opt/spool-control/deploy/seed_brands.py
```

Logos are saved to `static/brands/` and shown automatically in the filament listing. New
logos can be added in **Admin → Brands / Logos**.

## Initial credentials

- User: `admin`
- Password: randomly generated by `setup-inside.sh` (shown at the end of the install)

Change it immediately in **Admin → Users**.

## Environment variables (`spool.env`)

Generated automatically by `setup-inside.sh`. Example:

```env
SECRET_KEY=<random hex>
ADMIN_DEFAULT_PASS=<initial password>
APP_BASE_URL=https://spool.example.com
SECURE_COOKIES=1
SPOOL_API_KEY=<random hex>
```

> `spool.env` is in `.gitignore` and must never be committed.
