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


def ts(days_ago=0):
    return (datetime.utcnow() - timedelta(days=days_ago)).isoformat()


# ── Senha demo ────────────────────────────────────────────────────────────────
cur.execute("UPDATE users SET password_hash=? WHERE username='admin'",
            (generate_password_hash("demo"),))

# ── Marcas ────────────────────────────────────────────────────────────────────
for name, domain in [
    ("Bambu Lab",   "bambulab.com"),
    ("Polymaker",   "polymaker.com"),
    ("eSUN",        "esun3d.com"),
    ("Prusament",   "prusa3d.com"),
    ("Hatchbox",    "hatchbox3d.com"),
    ("Sunlu",       "sunlu.com"),
]:
    cur.execute("INSERT OR IGNORE INTO brands (name, domain, updated_at) VALUES (?,?,?)",
                (name, domain, now))

# ── Modelos de carretel ───────────────────────────────────────────────────────
MODELS = {
    "Standard 1kg":  (210.0, "Carretel padrão de 1 kg"),
    "Light 500g":    (140.0, "Carretel leve de 500 g"),
    "Bambu Lab 1kg": (215.0, "Carretel original Bambu Lab"),
}
for name, (tare, notes) in MODELS.items():
    cur.execute("INSERT OR IGNORE INTO spool_models (name, tare_weight_g, notes, created_at) VALUES (?,?,?,?)",
                (name, tare, notes, now))

model_ids  = {r["name"]: r["id"]           for r in cur.execute("SELECT id, name FROM spool_models")}
model_tare = {r["name"]: r["tare_weight_g"] for r in cur.execute("SELECT name, tare_weight_g FROM spool_models")}

# ── Filamentos (15) ───────────────────────────────────────────────────────────
# (brand, material, family, color_hex, diameter_mm, notes)
FILAMENTS = [
    ("Bambu Lab",  "PLA",  "PLA Basic",    "#F8F8F8", 1.75, "Branco Arctic"),
    ("Bambu Lab",  "PLA",  "PLA Basic",    "#111111", 1.75, "Preto"),
    ("Bambu Lab",  "PLA",  "PLA Basic",    "#C0392B", 1.75, "Vermelho Vivo"),
    ("Bambu Lab",  "PETG", "PETG HF",      "#2980B9", 1.75, "Azul Oceano"),
    ("Bambu Lab",  "ABS",  "ABS",          "#2C3E50", 1.75, "Cinza Escuro"),
    ("Polymaker",  "PLA",  "PolyLite PLA", "#E74C3C", 1.75, "Vermelho"),
    ("Polymaker",  "PETG", "PolyLite PETG","#27AE60", 1.75, "Verde Esmeralda"),
    ("Polymaker",  "TPU",  "PolyFlex TPU", "#F39C12", 1.75, "Amarelo"),
    ("eSUN",       "PLA",  "PLA+",         "#8E44AD", 1.75, "Roxo"),
    ("eSUN",       "PLA",  "PLA+",         "#2ECC71", 1.75, "Verde Lima"),
    ("eSUN",       "ABS",  "ABS+",         "#95A5A6", 1.75, "Cinza Prata"),
    ("Prusament",  "PLA",  "Prusament PLA","#E67E22", 1.75, "Laranja Galaxy"),
    ("Prusament",  "PETG", "Prusament PETG","#1ABC9C", 1.75, "Teal"),
    ("Hatchbox",   "PLA",  "PLA",          "#F1948A", 1.75, "Rosa"),
    ("Sunlu",      "SILK", "Silk PLA",     "#D4AC0D", 1.75, "Dourado Silk"),
]
for brand, material, family, color, diam, notes in FILAMENTS:
    cur.execute("""INSERT OR IGNORE INTO filaments
                   (brand, material, family, color_hex, diameter_mm, notes, created_at)
                   VALUES (?,?,?,?,?,?,?)""",
                (brand, material, family, color, diam, notes, now))

fil_id = {r["notes"]: r["id"] for r in cur.execute("SELECT id, notes FROM filaments")}

# ── Spools (40) ───────────────────────────────────────────────────────────────
# (filament_notes, model, nominal_g, location, purchase_date_days_ago, active, gross_weights_list)
# gross_weights: do mais antigo ao mais recente (maior → menor conforme usa)
SPOOLS = [
    # ── Bambu Lab PLA Branco Arctic ──
    ("Branco Arctic",   "Bambu Lab 1kg", 1000, "Prateleira A", 120, 1, [1215, 980, 740, 520]),
    ("Branco Arctic",   "Bambu Lab 1kg", 1000, "Prateleira A",  30, 1, [1210, 1050]),
    ("Branco Arctic",   "Bambu Lab 1kg", 1000, "Prateleira A",   5, 1, [1212]),
    # ── Bambu Lab PLA Preto ──
    ("Preto",           "Bambu Lab 1kg", 1000, "Prateleira A", 180, 1, [1208, 900, 600, 320, 215]),
    ("Preto",           "Bambu Lab 1kg", 1000, "Prateleira A",  60, 1, [1211, 800, 450]),
    ("Preto",           "Bambu Lab 1kg", 1000, "Prateleira B",  10, 1, [1209]),
    # ── Bambu Lab PLA Vermelho Vivo ──
    ("Vermelho Vivo",   "Bambu Lab 1kg", 1000, "Prateleira B",  90, 1, [1207, 750, 380]),
    ("Vermelho Vivo",   "Bambu Lab 1kg", 1000, "Prateleira B",  15, 1, [1210, 1100]),
    # ── Bambu Lab PETG Azul Oceano ──
    ("Azul Oceano",     "Standard 1kg",  1000, "Prateleira B",  75, 1, [1195, 820, 500]),
    ("Azul Oceano",     "Standard 1kg",  1000, "Prateleira C",  20, 1, [1198, 980]),
    # ── Bambu Lab ABS Cinza Escuro ──
    ("Cinza Escuro",    "Standard 1kg",  1000, "Prateleira C", 150, 1, [1200, 700, 250]),
    ("Cinza Escuro",    "Standard 1kg",  1000, "Prateleira C",  45, 1, [1202, 900]),
    # ── Polymaker PLA Vermelho ──
    ("Vermelho",        "Standard 1kg",  1000, "Prateleira C",  60, 1, [1205, 600, 310]),
    ("Vermelho",        "Standard 1kg",  1000, "Prateleira D",  12, 1, [1203]),
    # ── Polymaker PETG Verde Esmeralda ──
    ("Verde Esmeralda", "Standard 1kg",  1000, "Prateleira D",  80, 1, [1190, 850, 550, 280]),
    ("Verde Esmeralda", "Standard 1kg",  1000, "Prateleira D",  25, 1, [1192, 1050]),
    # ── Polymaker TPU Amarelo ──
    ("Amarelo",         "Light 500g",     500, "Gaveta 1",      55, 1, [690, 520, 310]),
    ("Amarelo",         "Light 500g",     500, "Gaveta 1",       8, 1, [688]),
    # ── eSUN PLA+ Roxo ──
    ("Roxo",            "Standard 1kg",  1000, "Prateleira D", 100, 1, [1200, 950, 700, 420]),
    ("Roxo",            "Standard 1kg",  1000, "Prateleira A",  35, 1, [1198, 1080]),
    # ── eSUN PLA+ Verde Lima ──
    ("Verde Lima",      "Standard 1kg",  1000, "Armário",       70, 1, [1196, 800, 500]),
    ("Verde Lima",      "Standard 1kg",  1000, "Armário",       18, 1, [1197]),
    # ── eSUN ABS+ Cinza Prata ──
    ("Cinza Prata",     "Standard 1kg",  1000, "Prateleira B", 110, 1, [1205, 600, 220]),
    ("Cinza Prata",     "Standard 1kg",  1000, "Prateleira B",  40, 1, [1203, 950]),
    # ── Prusament PLA Laranja Galaxy ──
    ("Laranja Galaxy",  "Standard 1kg",  1000, "Prateleira C",  95, 1, [1195, 750, 480]),
    ("Laranja Galaxy",  "Standard 1kg",  1000, "Prateleira C",  22, 1, [1197, 1020]),
    # ── Prusament PETG Teal ──
    ("Teal",            "Standard 1kg",  1000, "Prateleira D",  65, 1, [1190, 900, 600]),
    ("Teal",            "Standard 1kg",  1000, "Armário",        7, 1, [1193]),
    # ── Hatchbox PLA Rosa ──
    ("Rosa",            "Light 500g",     500, "Gaveta 1",      50, 1, [685, 500, 320]),
    ("Rosa",            "Light 500g",     500, "Gaveta 2",      16, 1, [687, 600]),
    # ── Sunlu Silk Dourado ──
    ("Dourado Silk",    "Light 500g",     500, "Gaveta 2",      85, 1, [695, 480, 220]),
    ("Dourado Silk",    "Light 500g",     500, "Gaveta 2",      28, 1, [692, 580]),
    # ── Extras variados ──
    ("Branco Arctic",   "Bambu Lab 1kg", 1000, "Armário",       50, 1, [1214, 650]),
    ("Preto",           "Standard 1kg",  1000, "Armário",       40, 1, [1208, 700, 380]),
    ("Azul Oceano",     "Standard 1kg",  1000, "Gaveta 2",      33, 1, [1196, 900, 450]),
    ("Roxo",            "Standard 1kg",  1000, "Gaveta 2",      55, 1, [1200, 550]),
    # ── Finalizados (inativos) ──
    ("Branco Arctic",   "Bambu Lab 1kg", 1000, "Arquivo",      365, 0, [1215, 800, 420, 215]),
    ("Preto",           "Standard 1kg",  1000, "Arquivo",      300, 0, [1205, 600, 210]),
    ("Vermelho",        "Standard 1kg",  1000, "Arquivo",      280, 0, [1203, 700, 215]),
    ("Cinza Escuro",    "Standard 1kg",  1000, "Arquivo",      250, 0, [1200, 500, 212]),
]

for fil_notes, model_name, nominal, location, days_ago, active, readings in SPOOLS:
    fid = fil_id.get(fil_notes)
    mid = model_ids.get(model_name)
    tare = model_tare.get(model_name, 210.0)
    if not fid:
        continue
    cur.execute("""INSERT INTO spools
                   (filament_id, spool_model_id, nominal_weight_g, location,
                    purchase_date, active, created_at)
                   VALUES (?,?,?,?,?,?,?)""",
                (fid, mid, nominal, location,
                 (datetime.utcnow() - timedelta(days=days_ago)).strftime("%Y-%m-%d"),
                 active, ts(days_ago)))
    spool_id = cur.lastrowid
    n = len(readings)
    for i, gross in enumerate(readings):
        cur.execute("""INSERT INTO weight_readings
                       (spool_id, gross_weight_g, tare_weight_g, ts, recorded_by)
                       VALUES (?,?,?,?,?)""",
                    (spool_id, gross, tare,
                     ts(days_ago=max(0, n - i - 1)),
                     "demo"))

conn.commit()
conn.close()
print(f"Seed concluído: {len(FILAMENTS)} filamentos, {len(SPOOLS)} spools.")
