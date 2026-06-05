# Changelog

Versioning follows [SemVer](https://semver.org/): **MAJOR.MINOR.PATCH**

| Digit | When to bump |
|---|---|
| **MAJOR** | Breaking change — incompatible schema change, route removal, deploy restructuring |
| **MINOR** | New backward-compatible feature — new route, new report, new integration |
| **PATCH** | Bug fix, visual tweak, copy improvement, dependency update |

---

## [1.17.0] — 2026-06-05

### Security
- **XSS (Stored) — confirm() dialogs**: 7 templates trocaram `onsubmit="return confirm('{{ var }}')"` por `data-sc-confirm="{{ var }}"` lido via `dataset` em JS — Jinja2 escapa o atributo HTML corretamente; o JS nunca recebe string injetada.
- **CSP sem `unsafe-inline`**: script CSRF movido para `static/csrf.js`; toast + theme toggle movidos para `static/spool.js`; único script inline restante (anti-flash de tema) recebe nonce por request — `script-src` usa `'nonce-{n}'` em vez de `'unsafe-inline'`.
- **Open redirect**: helper `_safe_next()` valida que o parâmetro `next` começa com `/` e não com `//` — aplicado em `filaments_edit`, `label_queue_add/remove/add-all/remove-all`.
- **Credencial admin padrão**: fallback `admin123` removido. Quando `ADMIN_DEFAULT_PASS` não está definido no env, gera senha aleatória (`secrets.token_urlsafe(12)`) e a loga em `WARNING` no startup — nunca usa senha conhecida.

### Added
- `static/csrf.js`: CSRF token injection (forms + fetch) extraído de `base.html`.

## [1.16.1] — 2026-06-05

### Fixed
- **API key fechado por padrão**: `SPOOL_API_KEY` ausente agora retorna 401 (antes abria sem auth). `update-lxc.sh` passa a gerar a chave no `spool.env` de fallback.
- **Timing attack**: comparação da API key migrada para `secrets.compare_digest()`.

## [1.16.0] — 2026-06-05

### Added
- **Structured JSON logging** (`structlog`): every log line is a JSON object with `event`, `level`, `logger`, `timestamp`, `request_id`, `method`, `path`, `ip`, `user`, and `duration_ms`. Captured by journald and parseable by Loki/ELK.
- **Request ID middleware**: each HTTP request generates an 8-char `X-Request-ID` header (returned to the client and bound to every log line in that request).
- **Data masking**: fields named `password`, `token`, `secret`, `api_key`, `authorization`, `cookie`, `spool_api_key`, and `password_hash` are replaced with `***` before any log is written.
- **Gunicorn config file** (`deploy/gunicorn.conf.py`): all gunicorn parameters migrated from the service file; access log now emits JSON.
- **Enhanced `/health` endpoint**: checks DB connectivity and data directory; returns `{"status":"ok"|"degraded","version":"...","checks":{...}}` with HTTP 503 on failure.
- **Missing HTTP error handlers**: 400, 422, 500, and a catch-all `Exception` handler — all log at the appropriate level and return JSON for API requests.

### Fixed
- 8 silent `except Exception: pass` blocks replaced with `log.warning/error(exc_info=True)` so no failure goes unnoticed.
- `is_valid_backup_db` now logs the exception detail before returning `False`.
- Logo rendering failures in PDF and PNG labels now log a warning instead of silently degrading.

## [1.15.0] — 2026-06-05

### Added
- **Language selector on the login page**: the PT/EN/ES flag dropdown (same as the main nav) now sits in the top-right corner of the login screen, so the language can be switched before signing in. Works logged-out and returns to the login page.
- **Prominent label-queue shortcut in the main menu**: when the print queue has items, a highlighted **yellow** entry (matching the spools page "print" action) appears in the navbar right after **Reports**, with the item count. It disappears automatically once the queue is emptied. The queue was moved out of the Reports dropdown into this conditional top-level shortcut.

## [1.14.0] — 2026-06-05

### Added
- **"Keep me signed in" on the login page**: a checkbox that controls session persistence. **Unchecked (default)** the session is a browser cookie that ends when the browser closes; **checked** it persists for **30 days**. Translated (PT/EN/ES). Previously every login was forced to a fixed 12 h with no choice. Cookie hardening unchanged (`HttpOnly`, `SameSite=Lax`, `Secure` via `SECURE_COOKIES`).

## [1.13.1] — 2026-06-04

### Fixed
- **Broken clean install** (`setup-inside.sh`): the script copied a **fixed list** of files and `niimbot_registry.py` was missing from it — a fresh install came up with `ModuleNotFoundError: No module named 'niimbot_registry'`. It now copies the **entire versioned tree** via `git archive` (same mechanism as `update-lxc.sh`), with no list to maintain. (Production via `update-lxc.sh` was never affected.) Caught while validating a clean install on a temporary LXC.

## [1.13.0] — 2026-06-04

### Added
- **New label layout** (60×40mm PDF + Niimbot thermal PNG): top with **logo + brand name** on the left and the **spool code** on the right; thick horizontal divider; left block with **Material** (large), **Family**, **Color** (name classified from the hex) and **Local:** anchored at the bottom; **larger QR on the right**. The color name is **translated** to the session language (PT/EN/ES). The brand logo is included on the thermal label too (flattened onto white for 1-bit). `get_spool` now returns `brand_logo`.
- **Automatic weighing station API**: `POST /api/weigh` (`{spool_id, gross_weight_g}`) and `GET /api/spools/<id>` (read-only, for the OLED to confirm before recording). Machine-to-machine: CSRF-exempt, authenticated by `X-API-Key` (== `SPOOL_API_KEY`), `recorded_by="estação"`, JSON responses with 400/401/404/422. Foundation for the ESP32 + serial reader station (see `docs/estudo_balanca_qrcode.md`).
- **`tools/validate_qr_autoweigh.py`** — validates, without hardware, the QR round-trip (generate → decode → extract the id anchored on `/spools/(\d+)`) and the weighing arithmetic, with small and large codes; optional live (read-only) check against the API.

### Changed
- **Public URL guaranteed at install time** (each user runs on their own server): new `public_base_url()` uses the DB setting and falls back to the `APP_BASE_URL` env var when it is empty/`localhost`; the setting is now **seeded from the environment** in `init_db`. The installers (`setup-inside.sh`/`proxmox-deploy.sh`) **no longer** default to a third-party domain — without a domain they use the **internal IP** with a **"local network only" warning** and generate `SPOOL_API_KEY` in `spool.env`. The **Settings** screen pre-fills the effective URL (saving applies everywhere).

### Security
- `POST /api/weigh` requires `X-API-Key` when `SPOOL_API_KEY` is set (generated by default at install). With no key configured the API is open — dev/LAN only.

## [1.12.0] — 2026-06-04

### Added
- **Spanish (ES) language** — third language, with a **100%** translated UI. Language-selector flags became **SVG** (`static/flags/`), since flag emojis don't render on Windows.
- **100% i18n** — every visible string (templates + server flash/error messages) now goes through translation (`_()` in templates, `t()` helper in `app.py`). `translations.py` with complete `_EN`/`_ES` and `_PT` overrides only. "How to add a language" documented in `CLAUDE.md`.
- **Inventory report** (`/reports/inventory`) — visual grid with one donut per physical spool, instant filter and a detail modal on click (logo, material, color, remaining, diameter, location, notes, **QR** and link). New endpoint `GET /spools/<id>/qr.png`.
- **Statistics report** (`/reports/stats`) — horizontal bars by **Brand**, **Material** and **Color**. Color is classified from the hex (`classify_color`, groups all greens/reds/etc.). Each bar is **clickable** and leads to the filtered list (`?q=` for brand/material, `?color=` for color).
- Color **hex code** shown on the spool detail (below the family, with the color dot before it).
- **Print** button on the spool list (next to "All", when there are items in the queue).

### Changed
- **PT-BR: "Spool" → "Rolo(s)"** across the UI (keeping the "SP-" code; EN stays "Spool", ES "Bobina").
- In the label queue, **"Print All" → "Print PDF"**, matching the "Print Niimbot" visual style.

---

## [1.11.3] — 2026-06-03

### Fixed
- **Availability donut now shows on the spool detail page** (`/spools/<id>`). It only existed in the listing before; the detail showed just the family color dot. The donut (% remaining, in the filament color) was added to the header, next to `SP-XXXX`, with the same logic and tooltip as the listing.

### Changed (internal)
- `donut` macro extracted to the shared partial `templates/spools/_macros.html` and imported in the listing and the detail (single source).

---

## [1.11.2] — 2026-06-03

### Fixed (deploy robustness)
- **`update-lxc.sh` no longer takes the service down due to a missing file.** Cause of the crash loop / random 404: the script copied `.py` files by name, and forgetting a new module (it happened with `niimbot_registry.py`) made `app.py` fail to import and the service restart in a loop. Two layers of fix:
  1. **Applies the whole versioned tree via `git archive`** — no file list to forget; whatever is in git gets applied. Does not delete items outside git (`data/`, `spool.env`, `.venv`, `static/brands/`).
  2. **Smoke test (`import app`) before restarting** — if the new code doesn't import (missing module, syntax error, etc.), the deploy **aborts and keeps the current service running** instead of restarting into a crash loop.

---

## [1.11.1] — 2026-06-03

### Fixed
- The Niimbot label divider line (between family and ID) was almost invisible in thermal printing — now it is **thicker** (proportional to the height).

### Changed (internal)
- Web Bluetooth driver extracted to the dedicated **private** repository `iscarelli/niimbot` (generic driver + V4 protocol docs + registry + standalone demo). spool-control now **vendors** a copy of the driver (`static/niimbot.js`) and adds the adapter `static/niimbot-spool.js` (fetches the registry + wires the buttons). No behavior change.
- New usage docs: `docs/niimbot.md`.

---

## [1.11.0] — 2026-06-03

### Added
- **Direct Niimbot printing from the browser** (Web Bluetooth): new **Print Niimbot** button on the spool detail page and the label queue, next to the PDF. Prints on a **Niimbot B1 Pro** (300 dpi, V4 protocol) with no intermediary app — protocol ported from the ESP32-Telemetria-Suite firmware.
- Label rendered server-side as a **1-bit PNG** (`GET /spools/<id>/label.png`); the browser only thresholds and sends over Bluetooth. Same layout as the PDF (QR + brand/material/family/ID).
- **Extensible registry** of printer models and label sizes (`niimbot_registry.py`, exposed at `GET /api/niimbot/registry`). Today: B1 Pro + 50×30 mm label.
- Settings (Admin): selection of **printer model** and **label size** for direct printing.

### Notes
- Requires **Chrome or Edge over HTTPS** (or localhost) — Web Bluetooth doesn't exist in Firefox/Safari. The PDF remains available as before.

---

## [1.10.4] — 2026-06-03

### Documentation
- Added a screenshot of the statistics screen (`stats.png`) to the docs.

---

## [1.10.3] — 2026-06-03

### Fixed
- "Blue background" on the tab favicon: it came from the PNG/`.ico` (the browser uses the raster, not the SVG). The tab favicons (`favicon-16x16`, `favicon-32x32`, `favicon.ico`) are now **transparent** — a cut-out blue spool, no tile — visible on light and dark tabs. The full-bleed blue tile was kept only on `apple-touch-icon` and the PWA icons (`android-chrome-*`), which need a background. Note: favicons are heavily cached — you may need a hard reload or to reopen the tab.

---

## [1.10.2] — 2026-06-03

### Changed
- The tab SVG favicon (`spool-icon.svg`) is now fully transparent (background and holes) and the spool color follows the browser scheme via `prefers-color-scheme` (dark on light tabs, light on dark tabs) instead of a fixed color — visible in both cases using the browser color. The blue `.ico`/PNG remains a fallback for browsers without SVG favicon support.

---

## [1.10.1] — 2026-06-03

### Fixed
- Tab favicon: removed the tile rounding (`rx`) — the transparent corners showed white on light tab bars — and the spool now fills the whole tile (it was small before, with too much padding). Favicon/PWA set regenerated from the square, full-bleed `app-icon.svg`.

---

## [1.10.0] — 2026-06-03

### Added
- New visual identity: redesigned spool icon (thicker flange with holes) and a "Spool Control" wordmark logo, both *themeable* (inline SVG via `currentColor`). Applied to the navbar (`base.html`) and the login screen.
- Full favicon set + PWA support: `favicon.ico`, 16/32 PNGs, 180×180 `apple-touch-icon`, 192/512 icons, `site.webmanifest` (`display: standalone`, `theme_color #0d6efd`) and `theme-color` in the `<head>`. Master in `static/icons/app-icon.svg`.

### Fixed
- UTC timestamps ending in `Z` (e.g. weighing logs) were shown as raw ISO strings, with seconds and the wrong mask, in both languages. `_parse_dt` now strips the `Z` suffix before parsing; `localdt`/`localdate` format correctly again on the dashboard, weight history and spool detail.

---

## [1.9.1] — 2026-06-03

### Added
- Dates shown in the selected language format (`localdt`/`localdate` filters): PT `dd/mm/yyyy`, EN `mm/dd/yyyy`. Applied on the dashboard, weight history, spool detail and user list.

### Fixed
- Rounded white corner at the top of tables inside cards with a header (e.g. "Recent Weighings"). Root cause: `.card .table-responsive { border-radius:10px }` rounded all 4 corners; now the top only rounds when the table is the first child of the card (no header).

---

## [1.9.0] — 2026-06-03

### Added
- Material and Brand in the filament form are now **searchable fields** (`input` + `datalist`): filter as you type and still accept a new value (replaces the select + "— New…" option).
- Flags (🇧🇷/🇺🇸) in the language selector.

### Changed
- Dashboard fully translated (cards, Low Stock and Recent Weighings tables); filament form translated.
- Top-right items (search, theme, language, logout) with the same height (`2rem`).

### Fixed
- Rounded corners of tables inside cards (dashboard and users): `overflow-hidden` on the card removes the "hairline" at the corners.

---

## [1.8.4] — 2026-06-02

### Fixed
- Dashboard: the 4th card (buttons) was taller than the others. The four cards now have the same height (`h-100`) with content vertically centered.

---

## [1.8.3] — 2026-06-02

### Changed
- Dashboard: the "Spool" and "Filament" buttons now have the same width.
- Spool list: "View finished"/"Active only" and the printer button ("All") no longer wrap (`text-nowrap`); the header controls (Filter, View finished, All, + Spool) all got the same height (`2rem`).

---

## [1.8.2] — 2026-06-02

### Changed
- The two creation buttons that **already existed** in the dashboard card (`+ New Spool` / `+ Filament`) now use the internal pages' "pill primary" style.

### Fixed
- Reverted the two extra buttons that 1.8.1 mistakenly added to the dashboard header (the intent was to change the existing ones, not duplicate them).

---

## [1.8.1] — 2026-06-02

### Added
- "+ Spool" and "+ Filament" buttons in the dashboard header, in the same style as the internal pages (shortcut to create without navigating to the lists).

---

## [1.8.0] — 2026-06-02

### Added
- **Backup and restore from the web UI** (`Admin → Backup`, `/admin/backup`, admin only):
  - **Download backup**: generates a `.zip` with the database (`spool.db`, consistent snapshot via the SQLite Online Backup API — includes the WAL) and the brand logos (`static/brands/`).
  - **Restore backup**: uploads the `.zip`, **validates** the database before applying and replaces all data; logos restored with sanitization (basename + image extension only, anti zip-slip). No root and no service restart needed.
  - Designed to reinstall and recover everything. `spool.env` (secrets) is **not** in the backup — after reinstalling, just log in again (passwords come from the DB).

### Changed
- `MAX_CONTENT_LENGTH` 4 MB → 64 MB (headroom for the restore zip upload).

---

## [1.7.2] — 2026-06-02

### Added
- `proxmox-deploy.sh` now asks **where to store the template** (vztmpl storage) via a radiolist when there's more than one option — same behavior as the rootfs storage selection. Auto-selects if there's only one; falls back to `local` if none.

### Changed
- README: "Future updates" highlights the web UI update (`/admin/update`) as recommended; CLI becomes the alternative/recovery path.

---

## [1.7.1] — 2026-06-02

### Changed
- Version bump to validate the web UI self-update (`/admin/update`) end to end. No functional change.

---

## [1.7.0] — 2026-06-02

### Added
- **Self-update from the web UI** (`/admin/update`, admin only): shows the current version vs. the latest GitHub release and updates with one click. A badge in the Admin menu signals a new version. The page tracks progress (polling `/admin/update/status`) and reloads on completion.
  - Isolated privileged execution: the app (user `spool`, non-root) only triggers `sudo systemctl start --no-block spool-update.service` — **a fixed command, no browser-supplied arguments**. The oneshot runs as root and calls `update-lxc.sh --latest-release`, which resolves the latest tag **on the server**. Minimal `sudoers` rule in `/etc/sudoers.d/spool-update`.
  - New files: `deploy/spool-update.service`, `deploy/sudoers-spool-update`.
- `update-lxc.sh --latest-release`: resolves and installs the latest published release (aborts if the GitHub API fails, without falling back to `main`).

### Changed
- `setup-inside.sh` and `update-lxc.sh` provision the oneshot + sudoers (idempotent) and install the `sudo` package.

---

## [1.6.3] — 2026-06-02

### Fixed
- **Root cause** of the install returning to the prompt: the `pick_template_storage` function ended with `[ -z "$TMPL_STORAGE" ] && TMPL_STORAGE="local"`. When the storage **was found** (success path) the test returned 1, the function returned 1, and `set -e` aborted the script — right after the domain step. Replaced with an `if`. Same pattern fixed in `pick_storage` (`&& die` on the last line).

---

## [1.6.2] — 2026-06-02

### Fixed
- `proxmox-deploy.sh` died silently (returned to the prompt with no message) when any command failed under `set -e`. There's now a global error handler (`set -E` + `trap ... ERR`) that prints **the failing line and command** and offers to destroy a half-created container. This makes the cause visible for diagnosis.

---

## [1.6.1] — 2026-06-02

### Fixed
- `proxmox-deploy.sh` aborted silently right after the host checks (returned to the prompt) when run via `curl ... | bash`: `stdin` was the script pipe and the first `whiptail` dialog failed under `set -e`. It now reconnects `stdin` to `/dev/tty` when available, working both with `bash -c "$(curl ...)"` and `curl ... | bash`.

### Changed
- `proxmox-deploy.sh` translated to English (comments, `whiptail` dialogs, messages and final summary). Logic unchanged.

---

## [1.6.0] — 2026-06-02

### Added
- **Proxmox installer** (`deploy/proxmox-deploy.sh`) in the Proxmox Helper Scripts style: runs on the PVE host, asks CTID/hostname/network/resources/URL via whiptail, creates the Debian 12 LXC (unprivileged, nesting) and installs everything. One-liner:
  ```bash
  bash -c "$(curl -fsSL https://raw.githubusercontent.com/iscarelli/spool-control/main/deploy/proxmox-deploy.sh)"
  ```
  No domain → direct access `http://IP:8001` (`SECURE_COOKIES=0`); with a domain → `SECURE_COOKIES=1`.

### Fixed
- `setup-inside.sh` didn't copy `VERSION` or `translations.py` — a fresh install broke at boot (`app.py` reads both). Now it copies the full set (same as `update-lxc.sh`).

### Changed
- `setup-inside.sh` parameterizable by environment: `DOMAIN`, `APP_BASE_URL`, `SECURE_COOKIES`, `USE_BR_MIRROR`, `ADMIN_DEFAULT_PASS`. Can run via `bash <(curl -fsSL .../setup-inside.sh)`.
- README: deploy rewritten around the automatic installer; GitHub token references removed.

---

## [1.5.0] — 2026-06-02

### Security (hardening for internet exposure)
- **CSRF**: global protection (Flask-WTF) on all POSTs. Token delivered via `<meta>`/hidden input and the `X-CSRFToken` header in fetch.
- **SECRET_KEY required**: the app refuses to start in production without `SECRET_KEY` (prevents session forgery with a default key).
- **Spool detail now requires login** (`/spools/<id>`): it was public before and, with sequential IDs, allowed enumerating the whole stock (prices, locations, history). The QR redirects to login when needed.
- **Login throttle**: per-IP block after 10 failures in 15 min (anti brute-force), with a `login_failures` table.
- **Security headers**: Content-Security-Policy, X-Frame-Options, X-Content-Type-Options, Referrer-Policy and HSTS (over HTTPS).
- **ProxyFix**: real client IP behind Traefik (correct auditing/throttling).
- **MAX_CONTENT_LENGTH** of 4 MB and SVG removed from logo uploads (prevents stored XSS).
- **Open redirect protection** on the login `next` parameter.

### Infrastructure
- Deploy without a GitHub token — the repository is public, anonymous clone; `.gh_token` removed from the server.
- Firewall (nftables) on the LXC: port `:8001` reachable only by Traefik and locally (no longer exposed on the LAN over plain HTTP).
- VMID 117 added to the CasaMMD1 node backup job.

---

## [1.4.8] — 2026-06-02

### Fixed
- Queue message uses correct singular/plural: "1 spool added" vs "N spools added/removed".

---

## [1.4.7] — 2026-06-02

### Added
- The "All" button on the spool list becomes a toggle: if all visible ones are already queued, remove all; otherwise add all.
- Success flash now shows as a top-center toast that auto-dismisses in 3 seconds.

---

## [1.4.6] — 2026-06-02

### Added
- "New material..." option in the filament form's material dropdown — allows registering types not listed (same pattern already used for brands).

---

## [1.4.1] — 2026-06-02

### Fixed
- The navbar spool icon disappeared in light mode — replaced the inline `filter:invert(0.9)` with a `.brand-icon` class controlled by theme via CSS.
- Even thicker donuts: stroke-width 15, viewBox 50×50, cx/cy 25 — inner hole ~36% of the outer diameter, closer to the visual reference.

---

## [1.4.0] — 2026-06-02

### Added
- **Dark/Light mode**: navbar toggle, preference saved in localStorage, no flash on load.
- **i18n PT/BR → EN**: translation infrastructure in `translations.py`, PT|EN switcher in the navbar, `/lang/pt` and `/lang/en` routes, navigation and list strings translated.
- CSS design tokens for light mode (`[data-bs-theme="light"]`).

### Changed
- Even thicker donuts: stroke-width 9, viewBox 44×44, cx/cy 22 — outer diameter kept.
- Donut track adapts to the theme via the `.donut-track` class and `var(--sc-border)`.
- "+ New Filament" and "+ New Spool" buttons: `btn-outline-primary` (outlined green) — more subtle.
- Inline weighing button: `btn-outline-secondary` instead of `btn-outline-dark`.
- Reusable Jinja donut macro across the 3 main templates.

---

## [1.3.1] — 2026-06-02

### Added
- Stock donut in the filament detail page title (`/filaments/<id>`).
- Per-spool donuts in the spool listing within the filament detail.
- Clicking anywhere on the row opens the detail (filaments and spools).
- Inline weighing modal in the spool listing: records weight without leaving the page, updates the donut and weight instantly.
- "Queue: All" button in the spool listing: adds all visible spools to the print queue.
- `POST /label-queue/add-all` route to enqueue multiple spools at once.
- AJAX support on the weighing endpoint (`X-Requested-With: XMLHttpRequest` → JSON response).

### Changed
- Removed the aggregate donut from the filament listing title (now shown on each filament's detail).
- Donuts with thicker stroke (stroke-width 6, viewBox 40×40) — outer diameter kept.
- Removed the progress bar from the spool listing in the filament detail (replaced by a donut).

---

## [1.3.0] — 2026-06-02

### Added
- Full design system: native Bootstrap 5.3 dark mode (`data-bs-theme="dark"`) with a slate/green palette.
- Inter font (Google Fonts) for the whole UI; Fira Code for the version badge.
- CSS design tokens (`--sc-bg`, `--sc-surface`, `--sc-accent`, etc.) as the theming base.
- Navbar with an active-page indicator (`.sc-active`) per Flask endpoint.

### Changed
- Navbar: refined layout, gap between items, dropdowns with rounded borders and shadow.
- Tables: header with uppercase 0.7rem typography + letter-spacing; `#111827` background.
- Buttons: revised palette — green primary, slate secondary, subtle danger/warning.
- Alerts: translucent colored background instead of solid.
- Cards: `#1E293B` surface, `#334155` border, 10px border-radius.
- Version badge: monospaced, fixed at the bottom-right corner.
- "+ New Filament" and "+ New Spool" buttons: `btn-primary` (green) instead of `btn-dark`.

---

## [1.2.1] — 2026-06-02

### Changed
- Label QR code: ECC raised from M (15%) to Q (25%) — more robust scanning for the future physical station with the GM861-LED.

---

## [1.2.0] — 2026-06-02

### Added
- Donut chart (SVG) in the filament list: shows remaining vs. nominal stock across all active spools, using the filament color.
- Aggregate donut in the filament list title, showing the total available-stock percentage across all filaments.
- Donut chart (SVG) in the spool list: shows each spool's remaining ratio, using the filament color.
- The deploy script (`update-lxc.sh`) now copies `CHANGELOG.md` to the server on each update.

### Changed
- Filament list: removed the color swatch before Family (replaced by the donut).
- Spool list: removed the color swatch and progress bar (replaced by the donut).

---

## [1.1.0] — 2026-06-02

### Added
- Global navbar search (`/search`) + instant client-side filter on the filament and spool lists.
- Sortable columns on the lists (click the header, ⇅/↑/↓ icon).
- Label print queue: add/remove spools, count badge in the menu, print all to PDF, clear queue.
- Automatic queue prompt when creating a spool or changing location.
- Quick weigh (`/weigh`): SP-XXXX code + gross weight → net computed automatically.
- Brand logos: download via the Google Favicon API + manual upload (Admin → Brands).
- Brand dropdown in the filament form ordered by usage (in-use first, then others, + new brand).
- Configurable label size (width × height mm) in Admin → Settings.
- Color preview + direct "Edit color / filament" link in the spool edit form.
- The filament can be changed when editing a spool (changes material, color, brand).
- Filament list: Material, Brand and Family are links that filter the spool list.
- Spool list: print-queue button (shows state) + inline edit button.
- Duplicate-filament button (copies fields only, no spools, opens editing).
- Remove-filament button (enabled only with no spools; tooltip explains when disabled).
- `?next=` flow in filament editing: saving the color returns to the spool screen.
- SP-XXXX code shown in the spool edit form title.
- Custom kitchen-scale SVG icon (Bootstrap Icons has no scale).
- Spool SVG icon as favicon and navbar logo.
- Version badge fixed at the bottom-right corner.

### Fixed
- `bi-balance-scale` doesn't exist in Bootstrap Icons 1.11.3 — replaced with a custom SVG.
- `cp -r templates` created `templates/templates/` in update-lxc.sh — fixed to `cp -r templates/.`.
- Tooltip on a `disabled` button — the native `title` doesn't fire; replaced with a Bootstrap tooltip (`data-bs-toggle`).
- `d-flex` in `<td>` caused a white bar in the filament list — removed.
- `--preload` added to gunicorn to avoid a bootstrap race condition with 2 workers.
- `INSERT OR IGNORE` in the admin bootstrap to avoid errors with multiple workers.
- Sort icons invisible in the dark header — `color:inherit` instead of `text-muted`.

## [1.0.0] — 2026-06-02

First production release.

### Features
- Filament registry (material, brand, family, color, diameter).
- Brand dropdown with automatic logos (Google Favicon API) and manual upload.
- Expanded material list (~45 types), ordered by the ones registered in the system.
- Multiple spools per filament with tare by spool model or custom.
- Weighing workflow: gross − tare = net, with history.
- Quick weigh (`/weigh`): SP-XXXX code + gross weight, without navigating to the spool.
- 60×40mm thermal PDF labels with QR code (no weight printed).
- Batch label print queue with a count badge in the menu.
- Automatic queue prompt when creating a spool or changing location.
- Reports: by material, by location, low stock, weight history.
- Instant client-side filter and sortable columns on listings.
- Global navbar search (`/search`).
- Flask authentication with admin/viewer roles.
- Public per-spool page (`/spools/<id>`) — QR code target, no login.
- Admin: users, brands/logos, settings (base URL, stock thresholds).

### Deploy
- Debian 12 LXC on Proxmox.
- Gunicorn with `--preload` (2 workers, avoids a bootstrap race condition).
- Traefik via the Proxmox Provider (LXC Notes) + Let's Encrypt DNS challenge.
- Scripts: `setup-inside.sh` (install), `update-lxc.sh` (update), `seed_brands.py` (logos).
