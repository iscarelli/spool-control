#!/usr/bin/env python3
"""
seed-demo-data.py — Popula o banco com dados de demonstração.
Roda após reset do DB; idempotente (usa INSERT OR IGNORE).
"""
import sys
import os
import sqlite3
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash

DB_PATH = os.environ.get("DB_PATH", "/opt/spool-control/data/spool.db")
APP_DIR = os.environ.get("APP_DIR", "/opt/spool-control")
sys.path.insert(0, APP_DIR)

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
conn.execute("PRAGMA journal_mode=WAL")
conn.execute("PRAGMA foreign_keys=ON")
cur = conn.cursor()

now = datetime.utcnow().isoformat()


def ts(days_ago=0, hours_ago=0):
    return (datetime.utcnow() - timedelta(days=days_ago, hours=hours_ago)).isoformat()


# ── Marcas ────────────────────────────────────────────────────────────────────
brands = [
    ("Bambu Lab",   "bambulab.com"),
    ("Polymaker",   "polymaker.com"),
    ("eSUN",        "esun3d.com"),
    ("Prusament",   "prusa3d.com"),
    ("Hatchbox",    "hatchbox3d.com"),
    ("Sunlu",       "sunlu.com"),
]
for name, domain in brands:
    cur.execute("INSERT OR IGNORE INTO brands (name, domain, updated_at) VALUES (?,?,?)",
                (name, domain, now))

# ── Modelos de carretel ───────────────────────────────────────────────────────
models = [
    ("Standard 1kg",  210.0, "Carretel padrão de 1 kg"),
    ("Light 500g",    140.0, "Carretel leve de 500 g"),
    ("Bambu Lab 1kg", 215.0, "Carretel original Bambu Lab"),
]
for name, tare, notes in models:
    cur.execute("""INSERT OR IGNORE INTO spool_models (name, tare_weight_g, notes, created_at)
                   VALUES (?,?,?,?)""", (name, tare, notes, now))

model_ids = {r["name"]: r["id"] for r in cur.execute("SELECT id, name FROM spool_models")}

# ── Filamentos ────────────────────────────────────────────────────────────────
filaments = [
    ("Bambu Lab",  "PLA",  "PLA Basic", "#FFFFFF", 1.75, "Branco Arctic"),
    ("Bambu Lab",  "PLA",  "PLA Basic", "#000000", 1.75, "Preto"),
    ("Bambu Lab",  "PETG", "PETG HF",   "#2563EB", 1.75, "Azul"),
    ("Polymaker",  "PLA",  "PolyLite",  "#EF4444", 1.75, "Vermelho"),
    ("Polymaker",  "PETG", "PolyLite",  "#10B981", 1.75, "Verde"),
    ("Polymaker",  "TPU",  "PolyFlex",  "#F59E0B", 1.75, "Amarelo"),
    ("eSUN",       "ABS",  "ABS+",      "#6B7280", 1.75, "Cinza"),
    ("eSUN",       "PLA",  "PLA+",      "#8B5CF6", 1.75, "Roxo"),
    ("Prusament",  "PLA",  "Prusament", "#F97316", 1.75, "Laranja Galaxy"),
    ("Hatchbox",   "PLA",  "PLA",       "#EC4899", 1.75, "Rosa"),
    ("Sunlu",      "SILK", "Silk PLA",  "#D4AF37", 1.75, "Dourado Silk"),
    ("Bambu Lab",  "ABS",  "ABS",       "#1F2937", 1.75, "Preto Mate"),
]
for brand, material, family, color, diam, notes in filaments:
    cur.execute("""INSERT OR IGNORE INTO filaments
                   (brand, material, family, color_hex, diameter_mm, notes, created_at)
                   VALUES (?,?,?,?,?,?,?)""",
                (brand, material, family, color, diam, notes, now))

fil = {r["notes"]: r["id"] for r in cur.execute("SELECT id, notes FROM filaments")}

# ── Spools ────────────────────────────────────────────────────────────────────
spools = [
    # (filament_notes, model_name, nominal_g, location, purchase_date, active, gross_readings)
    ("Branco Arctic",   "Bambu Lab 1kg", 1000, "Prateleira A",  "2026-01-10", 1, [1180, 950, 720]),
    ("Preto",           "Bambu Lab 1kg", 1000, "Prateleira A",  "2026-01-10", 1, [1210, 1050]),
    ("Azul",            "Standard 1kg",  1000, "Prateleira B",  "2026-02-05", 1, [1195, 800, 400]),
    ("Vermelho",        "Standard 1kg",  1000, "Prateleira B",  "2026-02-15", 1, [1205, 600]),
    ("Verde",           "Standard 1kg",  1000, "Prateleira C",  "2026-03-01", 1, [1190]),
    ("Amarelo",         "Light 500g",     500, "Gaveta 1",      "2026-03-10", 1, [690, 520, 310]),
    ("Cinza",           "Standard 1kg",  1000, "Prateleira C",  "2026-01-20", 1, [1215, 900, 200]),
    ("Roxo",            "Standard 1kg",  1000, "Prateleira D",  "2026-04-01", 1, [1200, 1100, 950]),
    ("Laranja Galaxy",  "Standard 1kg",  1000, "Prateleira D",  "2026-04-15", 1, [1195, 750]),
    ("Rosa",            "Light 500g",     500, "Gaveta 1",      "2026-05-01", 1, [685]),
    ("Dourado Silk",    "Light 500g",     500, "Gaveta 2",      "2026-05-10", 1, [695, 480, 120]),
    ("Preto Mate",      "Standard 1kg",  1000, "Prateleira A",  "2026-05-20", 1, [1210]),
    # Spools finalizados
    ("Branco Arctic",   "Bambu Lab 1kg", 1000, "Arquivo",       "2025-10-01", 0, [1180, 210]),
    ("Vermelho",        "Standard 1kg",  1000, "Arquivo",       "2025-11-15", 0, [1205, 215]),
]

for fil_notes, model_name, nominal, location, pdate, active, readings in spools:
    fil_id = fil.get(fil_notes)
    model_id = model_ids.get(model_name)
    if not fil_id:
        continue
    cur.execute("""INSERT INTO spools
                   (filament_id, spool_model_id, nominal_weight_g, location,
                    purchase_date, active, created_at)
                   VALUES (?,?,?,?,?,?,?)""",
                (fil_id, model_id, nominal, location, pdate, active, ts(days_ago=180)))
    spool_id = cur.lastrowid
    tare = models[list(model_ids.keys()).index(model_name)][1] if model_name in model_ids else 210.0
    for i, gross in enumerate(readings):
        cur.execute("""INSERT INTO weight_readings
                       (spool_id, gross_weight_g, tare_weight_g, ts, recorded_by)
                       VALUES (?,?,?,?,?)""",
                    (spool_id, gross, tare, ts(days_ago=len(readings)-i-1), "demo"))

conn.commit()
conn.close()
print("Seed concluído.")
