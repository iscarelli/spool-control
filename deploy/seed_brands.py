#!/usr/bin/env python3
"""Download logos for known 3D printing brands via Clearbit and populate DB."""
import sys
import re
import urllib.request
import sqlite3
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
BRANDS_DIR = APP_DIR / "static" / "brands"
DB_PATH = APP_DIR / "data" / "spool.db"

KNOWN_BRANDS = {
    "3D Fuel":            "3dfuel.com",
    "3DXTech":            "3dxtech.com",
    "Addnorth":           "addnorth.com",
    "Bambu Lab":          "bambulab.com",
    "ColorFabb":          "colorfabb.com",
    "Creality":           "creality.com",
    "Das Filament":       "dasfilament.de",
    "Elegoo":             "elegoo.com",
    "ERYONE":             "eryone3d.com",
    "eSUN":               "esun3d.com",
    "Fiberlogy":          "fiberlogy.com",
    "Filamentum":         "filamentum.com",
    "Flashforge":         "flashforge.com",
    "FormFutura":         "formfutura.com",
    "Hatchbox":           "hatchbox3d.com",
    "MatterHackers":      "matterhackers.com",
    "NinjaTek":           "ninjatek.com",
    "Overture":           "overture3d.com",
    "Polymaker":          "polymaker.com",
    "Proto-pasta":        "proto-pasta.com",
    "Prusament":          "prusa3d.com",
    "Raise3D":            "raise3d.com",
    "Sakata3D":           "sakata3d.com",
    "Spectrum Filaments": "spectrumfilaments.com",
    "SUNLU":              "sunlu.com",
    "Taulman3D":          "taulman3d.com",
    "Ultimaker":          "ultimaker.com",
    "Verbatim":           "verbatim.com",
    "ZIRO":               "ziro3d.com",
}


def _slug(name: str) -> str:
    return re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')


def fetch_logo(name: str, domain: str) -> str | None:
    dest = BRANDS_DIR / f"{_slug(name)}.png"
    url = (
        f"https://t3.gstatic.com/faviconV2"
        f"?client=SOCIAL&type=FAVICON&fallback_opts=TYPE,SIZE,URL"
        f"&url=https://{domain}&size=256"
    )
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            ct = resp.headers.get('Content-Type', '')
            if resp.status == 200 and ('image' in ct or 'octet' in ct):
                dest.write_bytes(resp.read())
                return f"brands/{_slug(name)}.png"
    except Exception:
        pass
    return None


def update_db(name: str, domain: str, logo_path: str):
    if not DB_PATH.exists():
        return
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute(
        """INSERT INTO brands (name, domain, logo_path) VALUES (?,?,?)
           ON CONFLICT(name) DO UPDATE SET
               domain    = CASE WHEN excluded.domain    != '' THEN excluded.domain    ELSE domain    END,
               logo_path = CASE WHEN excluded.logo_path != '' THEN excluded.logo_path ELSE logo_path END""",
        (name, domain, logo_path),
    )
    conn.commit()
    conn.close()


def main():
    BRANDS_DIR.mkdir(parents=True, exist_ok=True)
    ok = fail = 0
    for name, domain in sorted(KNOWN_BRANDS.items()):
        print(f"  {name:<24} ({domain})... ", end="", flush=True)
        logo_path = fetch_logo(name, domain)
        if logo_path:
            update_db(name, domain, logo_path)
            print("OK")
            ok += 1
        else:
            update_db(name, domain, "")
            print("sem logo")
            fail += 1
    print(f"\nConcluído: {ok} logos, {fail} sem resultado.")


if __name__ == "__main__":
    main()
