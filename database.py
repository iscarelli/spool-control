import sqlite3
import os
from pathlib import Path
from datetime import datetime, timezone, timedelta

DB_PATH = Path(__file__).parent / "data" / "spool.db"


def get_db():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
    return db


# ── Backup / restore (SQLite Online Backup API) ──────────────────────────────
# Usa a API de backup do SQLite, que tira um snapshot consistente (inclui o WAL)
# e respeita o lock — seguro mesmo com a app rodando e conexões por requisição.

def backup_to(dest_path):
    """Copia o conteúdo do DB ativo para dest_path (arquivo .db novo)."""
    src = get_db()
    dst = sqlite3.connect(dest_path)
    try:
        with dst:
            src.backup(dst)
    finally:
        dst.close()
        src.close()


def is_valid_backup_db(path):
    """Confere que `path` é um SQLite com as tabelas essenciais do Spool Control."""
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            names = {r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
        finally:
            con.close()
    except Exception:
        return False
    return {"users", "filaments", "spools", "settings"}.issubset(names)


def restore_from(src_path):
    """Substitui TODO o conteúdo do DB ativo pelo de src_path (via backup API).
    Valide com is_valid_backup_db() antes de chamar."""
    src = sqlite3.connect(src_path)
    dst = get_db()
    try:
        with dst:
            src.backup(dst)
    finally:
        dst.close()
        src.close()


def init_db():
    DB_PATH.parent.mkdir(exist_ok=True)
    db = get_db()
    db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            username      TEXT    UNIQUE NOT NULL,
            password_hash TEXT    NOT NULL,
            role          TEXT    NOT NULL DEFAULT 'viewer',
            created_at    TEXT    NOT NULL
        );

        CREATE TABLE IF NOT EXISTS spool_models (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            name           TEXT    NOT NULL,
            tare_weight_g  REAL    NOT NULL,
            notes          TEXT    NOT NULL DEFAULT '',
            created_at     TEXT    NOT NULL
        );

        CREATE TABLE IF NOT EXISTS filaments (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            brand        TEXT    NOT NULL,
            material     TEXT    NOT NULL,
            family       TEXT    NOT NULL,
            color_hex    TEXT    NOT NULL DEFAULT '',
            diameter_mm  REAL    NOT NULL DEFAULT 1.75,
            notes        TEXT    NOT NULL DEFAULT '',
            created_at   TEXT    NOT NULL
        );

        CREATE TABLE IF NOT EXISTS spools (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            filament_id     INTEGER NOT NULL REFERENCES filaments(id),
            spool_model_id  INTEGER REFERENCES spool_models(id),
            custom_tare_g   REAL,
            nominal_weight_g REAL NOT NULL DEFAULT 1000,
            location        TEXT NOT NULL DEFAULT '',
            purchase_date   TEXT NOT NULL DEFAULT '',
            purchase_price  REAL,
            notes           TEXT NOT NULL DEFAULT '',
            active          INTEGER NOT NULL DEFAULT 1,
            created_at      TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS weight_readings (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            spool_id       INTEGER NOT NULL REFERENCES spools(id),
            gross_weight_g REAL    NOT NULL,
            tare_weight_g  REAL    NOT NULL,
            net_weight_g   REAL    GENERATED ALWAYS AS (gross_weight_g - tare_weight_g) STORED,
            ts             TEXT    NOT NULL,
            recorded_by    TEXT    NOT NULL DEFAULT '',
            notes          TEXT    NOT NULL DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS settings (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS login_log (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            ts       TEXT NOT NULL,
            username TEXT NOT NULL,
            ip       TEXT NOT NULL DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS login_failures (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            ts       TEXT NOT NULL,
            ip       TEXT NOT NULL DEFAULT '',
            username TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_login_failures_ip_ts
            ON login_failures (ip, ts);

        CREATE TABLE IF NOT EXISTS label_queue (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            spool_id  INTEGER NOT NULL UNIQUE REFERENCES spools(id),
            added_at  TEXT    NOT NULL
        );

        CREATE TABLE IF NOT EXISTS brands (
            name       TEXT PRIMARY KEY,
            domain     TEXT NOT NULL DEFAULT '',
            logo_path  TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT ''
        );

        INSERT OR IGNORE INTO brands (name)
        SELECT DISTINCT brand FROM filaments WHERE brand != '';

        INSERT OR IGNORE INTO settings (key, value) VALUES
            ('app_base_url',         'http://localhost:5000'),
            ('low_stock_threshold_g','200'),
            ('low_stock_pct',        '20'),
            ('label_width_mm',       '60'),
            ('label_height_mm',      '40');
    """)
    db.commit()
    db.close()


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── Users ──────────────────────────────────────────────────────────────────

def get_user_by_username(username):
    db = get_db()
    row = db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    db.close()
    return row


def get_user_by_id(user_id):
    db = get_db()
    row = db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    db.close()
    return row


def list_users():
    db = get_db()
    rows = db.execute("SELECT * FROM users ORDER BY username").fetchall()
    db.close()
    return rows


def ensure_admin_user(username, password_hash):
    db = get_db()
    db.execute(
        "INSERT OR IGNORE INTO users (username, password_hash, role, created_at) VALUES (?,?,?,?)",
        (username, password_hash, "admin", now_iso()),
    )
    db.commit()
    db.close()


def create_user(username, password_hash, role="viewer"):
    db = get_db()
    db.execute(
        "INSERT INTO users (username, password_hash, role, created_at) VALUES (?,?,?,?)",
        (username, password_hash, role, now_iso()),
    )
    db.commit()
    db.close()


def update_user_password(user_id, password_hash):
    db = get_db()
    db.execute("UPDATE users SET password_hash=? WHERE id=?", (password_hash, user_id))
    db.commit()
    db.close()


def delete_user(user_id):
    db = get_db()
    db.execute("DELETE FROM users WHERE id=?", (user_id,))
    db.commit()
    db.close()


def log_login(username, ip):
    db = get_db()
    db.execute(
        "INSERT INTO login_log (ts, username, ip) VALUES (?,?,?)",
        (now_iso(), username, ip),
    )
    db.commit()
    db.close()


# ── Login throttle (anti força-bruta) ──────────────────────────────────────

def record_login_failure(ip, username):
    db = get_db()
    db.execute(
        "INSERT INTO login_failures (ts, ip, username) VALUES (?,?,?)",
        (now_iso(), ip, username),
    )
    db.commit()
    db.close()


def count_recent_login_failures(ip, window_minutes):
    """Falhas de login deste IP nos últimos window_minutes."""
    cutoff = (datetime.now(timezone.utc)
              - timedelta(minutes=window_minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")
    db = get_db()
    n = db.execute(
        "SELECT COUNT(*) FROM login_failures WHERE ip=? AND ts >= ?",
        (ip, cutoff),
    ).fetchone()[0]
    db.close()
    return n


def clear_login_failures(ip):
    db = get_db()
    db.execute("DELETE FROM login_failures WHERE ip=?", (ip,))
    db.commit()
    db.close()


# ── Settings ───────────────────────────────────────────────────────────────

def get_setting(key, default=""):
    db = get_db()
    row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    db.close()
    return row["value"] if row else default


def set_setting(key, value):
    db = get_db()
    db.execute(
        "INSERT INTO settings (key, value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )
    db.commit()
    db.close()


def get_all_settings():
    db = get_db()
    rows = db.execute("SELECT key, value FROM settings ORDER BY key").fetchall()
    db.close()
    return {r["key"]: r["value"] for r in rows}


# ── Brands ─────────────────────────────────────────────────────────────────

def list_brands():
    db = get_db()
    rows = db.execute("""
        SELECT b.*, COUNT(DISTINCT f.id) AS filament_count
        FROM brands b
        LEFT JOIN filaments f ON f.brand = b.name
        GROUP BY b.name ORDER BY b.name
    """).fetchall()
    db.close()
    return rows


def list_brands_ordered():
    db = get_db()
    rows = db.execute("""
        SELECT b.name, b.logo_path,
               COUNT(DISTINCT f.id) AS filament_count
        FROM brands b
        LEFT JOIN filaments f ON f.brand = b.name
        GROUP BY b.name
        ORDER BY
            CASE WHEN COUNT(DISTINCT f.id) > 0 THEN 0 ELSE 1 END,
            b.name
    """).fetchall()
    db.close()
    return rows


def get_brand(name):
    db = get_db()
    row = db.execute("SELECT * FROM brands WHERE name=?", (name,)).fetchone()
    db.close()
    return row


def update_brand_domain(name, domain):
    db = get_db()
    db.execute(
        "INSERT INTO brands (name, domain) VALUES (?,?) ON CONFLICT(name) DO UPDATE SET domain=excluded.domain",
        (name, domain),
    )
    db.commit()
    db.close()


def update_brand_logo_path(name, logo_path):
    db = get_db()
    db.execute(
        "UPDATE brands SET logo_path=?, updated_at=? WHERE name=?",
        (logo_path, now_iso(), name),
    )
    db.commit()
    db.close()


# ── Spool Models ───────────────────────────────────────────────────────────

def list_spool_models():
    db = get_db()
    rows = db.execute("SELECT * FROM spool_models ORDER BY name").fetchall()
    db.close()
    return rows


def get_spool_model(model_id):
    db = get_db()
    row = db.execute("SELECT * FROM spool_models WHERE id=?", (model_id,)).fetchone()
    db.close()
    return row


def create_spool_model(name, tare_weight_g, notes=""):
    db = get_db()
    db.execute(
        "INSERT INTO spool_models (name, tare_weight_g, notes, created_at) VALUES (?,?,?,?)",
        (name, tare_weight_g, notes, now_iso()),
    )
    db.commit()
    db.close()


def update_spool_model(model_id, name, tare_weight_g, notes=""):
    db = get_db()
    db.execute(
        "UPDATE spool_models SET name=?, tare_weight_g=?, notes=? WHERE id=?",
        (name, tare_weight_g, notes, model_id),
    )
    db.commit()
    db.close()


def delete_spool_model(model_id):
    db = get_db()
    count = db.execute(
        "SELECT COUNT(*) FROM spools WHERE spool_model_id=?", (model_id,)
    ).fetchone()[0]
    if count > 0:
        db.close()
        raise ValueError("Modelo em uso por spools existentes")
    db.execute("DELETE FROM spool_models WHERE id=?", (model_id,))
    db.commit()
    db.close()


# ── Filaments ──────────────────────────────────────────────────────────────

def list_filaments():
    db = get_db()
    rows = db.execute("""
        SELECT f.*,
               COUNT(s.id) AS spool_count,
               SUM(CASE WHEN s.active=1 THEN 1 ELSE 0 END) AS active_count,
               b.logo_path AS brand_logo,
               COALESCE(SUM(CASE WHEN s.active=1 THEN s.nominal_weight_g ELSE 0 END), 0) AS total_nominal_g,
               COALESCE(SUM(CASE WHEN s.active=1 THEN COALESCE(lw.net_weight_g, s.nominal_weight_g) ELSE 0 END), 0) AS total_net_g
        FROM filaments f
        LEFT JOIN spools s ON s.filament_id = f.id
        LEFT JOIN brands b ON b.name = f.brand
        LEFT JOIN (
            SELECT spool_id, net_weight_g
            FROM weight_readings
            WHERE id IN (SELECT MAX(id) FROM weight_readings GROUP BY spool_id)
        ) lw ON lw.spool_id = s.id
        GROUP BY f.id
        ORDER BY f.material, f.brand, f.family
    """).fetchall()
    db.close()
    return rows


def get_filament(filament_id):
    db = get_db()
    row = db.execute("""
        SELECT f.*, b.logo_path AS brand_logo
        FROM filaments f
        LEFT JOIN brands b ON b.name = f.brand
        WHERE f.id=?
    """, (filament_id,)).fetchone()
    db.close()
    return row


def create_filament(brand, material, family, color_hex="", diameter_mm=1.75, notes=""):
    db = get_db()
    db.execute(
        "INSERT INTO filaments (brand, material, family, color_hex, diameter_mm, notes, created_at) VALUES (?,?,?,?,?,?,?)",
        (brand, material, family, color_hex, diameter_mm, notes, now_iso()),
    )
    last = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    db.execute("INSERT OR IGNORE INTO brands (name) VALUES (?)", (brand,))
    db.commit()
    db.close()
    return last


def update_filament(filament_id, brand, material, family, color_hex="", diameter_mm=1.75, notes=""):
    db = get_db()
    db.execute(
        "UPDATE filaments SET brand=?, material=?, family=?, color_hex=?, diameter_mm=?, notes=? WHERE id=?",
        (brand, material, family, color_hex, diameter_mm, notes, filament_id),
    )
    db.execute("INSERT OR IGNORE INTO brands (name) VALUES (?)", (brand,))
    db.commit()
    db.close()


def delete_filament(filament_id):
    db = get_db()
    count = db.execute(
        "SELECT COUNT(*) FROM spools WHERE filament_id=?", (filament_id,)
    ).fetchone()[0]
    if count > 0:
        db.close()
        raise ValueError("Filamento possui spools associados")
    db.execute("DELETE FROM filaments WHERE id=?", (filament_id,))
    db.commit()
    db.close()


# ── Spools ─────────────────────────────────────────────────────────────────

def _spool_query_base():
    return """
        SELECT s.*,
               f.brand, f.material, f.family, f.color_hex, f.diameter_mm,
               sm.name AS model_name,
               COALESCE(s.custom_tare_g, sm.tare_weight_g, 0) AS effective_tare_g,
               wr.net_weight_g AS current_net_g,
               wr.gross_weight_g AS current_gross_g,
               wr.ts AS last_weighed_at
        FROM spools s
        JOIN filaments f ON f.id = s.filament_id
        LEFT JOIN spool_models sm ON sm.id = s.spool_model_id
        LEFT JOIN weight_readings wr ON wr.id = (
            SELECT MAX(id) FROM weight_readings WHERE spool_id = s.id
        )
    """


def list_spools(active_only=True):
    db = get_db()
    where = "WHERE s.active=1" if active_only else ""
    rows = db.execute(
        f"{_spool_query_base()} {where} ORDER BY f.material, f.brand, f.family, s.id"
    ).fetchall()
    db.close()
    return rows


def get_spool(spool_id):
    db = get_db()
    row = db.execute(
        f"{_spool_query_base()} WHERE s.id=?", (spool_id,)
    ).fetchone()
    db.close()
    return row


def list_spools_for_filament(filament_id):
    db = get_db()
    rows = db.execute(
        f"{_spool_query_base()} WHERE s.filament_id=? ORDER BY s.id",
        (filament_id,),
    ).fetchall()
    db.close()
    return rows


def create_spool(filament_id, spool_model_id, custom_tare_g, nominal_weight_g,
                 location, purchase_date, purchase_price, notes):
    db = get_db()
    db.execute(
        """INSERT INTO spools
           (filament_id, spool_model_id, custom_tare_g, nominal_weight_g,
            location, purchase_date, purchase_price, notes, active, created_at)
           VALUES (?,?,?,?,?,?,?,?,1,?)""",
        (filament_id, spool_model_id or None, custom_tare_g or None,
         nominal_weight_g, location, purchase_date, purchase_price or None,
         notes, now_iso()),
    )
    last = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    db.commit()
    db.close()
    return last


def update_spool(spool_id, filament_id, spool_model_id, custom_tare_g, nominal_weight_g,
                 location, purchase_date, purchase_price, notes):
    db = get_db()
    db.execute(
        """UPDATE spools SET filament_id=?, spool_model_id=?, custom_tare_g=?, nominal_weight_g=?,
           location=?, purchase_date=?, purchase_price=?, notes=?
           WHERE id=?""",
        (filament_id, spool_model_id or None, custom_tare_g or None, nominal_weight_g,
         location, purchase_date, purchase_price or None, notes, spool_id),
    )
    db.commit()
    db.close()


def deactivate_spool(spool_id):
    db = get_db()
    db.execute("UPDATE spools SET active=0 WHERE id=?", (spool_id,))
    db.commit()
    db.close()


# ── Weight Readings ────────────────────────────────────────────────────────

def add_weight_reading(spool_id, gross_weight_g, tare_weight_g, recorded_by="", notes=""):
    db = get_db()
    db.execute(
        """INSERT INTO weight_readings
           (spool_id, gross_weight_g, tare_weight_g, ts, recorded_by, notes)
           VALUES (?,?,?,?,?,?)""",
        (spool_id, gross_weight_g, tare_weight_g, now_iso(), recorded_by, notes),
    )
    db.commit()
    db.close()


def list_weight_readings(spool_id=None, filament_id=None, limit=200):
    db = get_db()
    if spool_id:
        rows = db.execute(
            """SELECT wr.*, f.brand, f.material, f.family, s.location
               FROM weight_readings wr
               JOIN spools s ON s.id = wr.spool_id
               JOIN filaments f ON f.id = s.filament_id
               WHERE wr.spool_id=?
               ORDER BY wr.ts DESC LIMIT ?""",
            (spool_id, limit),
        ).fetchall()
    elif filament_id:
        rows = db.execute(
            """SELECT wr.*, f.brand, f.material, f.family, s.location
               FROM weight_readings wr
               JOIN spools s ON s.id = wr.spool_id
               JOIN filaments f ON f.id = s.filament_id
               WHERE s.filament_id=?
               ORDER BY wr.ts DESC LIMIT ?""",
            (filament_id, limit),
        ).fetchall()
    else:
        rows = db.execute(
            """SELECT wr.*, f.brand, f.material, f.family, s.location
               FROM weight_readings wr
               JOIN spools s ON s.id = wr.spool_id
               JOIN filaments f ON f.id = s.filament_id
               ORDER BY wr.ts DESC LIMIT ?""",
            (limit,),
        ).fetchall()
    db.close()
    return rows


# ── Reports ────────────────────────────────────────────────────────────────

def report_by_material():
    db = get_db()
    rows = db.execute("""
        WITH latest AS (
            SELECT spool_id, net_weight_g
            FROM weight_readings
            WHERE id IN (SELECT MAX(id) FROM weight_readings GROUP BY spool_id)
        )
        SELECT f.material,
               COUNT(DISTINCT s.id)        AS spool_count,
               COALESCE(SUM(l.net_weight_g), 0) AS total_net_g,
               COALESCE(SUM(s.nominal_weight_g), 0) AS total_nominal_g
        FROM spools s
        JOIN filaments f ON f.id = s.filament_id
        LEFT JOIN latest l ON l.spool_id = s.id
        WHERE s.active = 1
        GROUP BY f.material
        ORDER BY f.material
    """).fetchall()
    db.close()
    return rows


def report_by_location():
    db = get_db()
    rows = db.execute("""
        WITH latest AS (
            SELECT spool_id, net_weight_g
            FROM weight_readings
            WHERE id IN (SELECT MAX(id) FROM weight_readings GROUP BY spool_id)
        )
        SELECT COALESCE(NULLIF(s.location,''), '(sem local)') AS location,
               COUNT(DISTINCT s.id)        AS spool_count,
               COALESCE(SUM(l.net_weight_g), 0) AS total_net_g
        FROM spools s
        LEFT JOIN latest l ON l.spool_id = s.id
        WHERE s.active = 1
        GROUP BY location
        ORDER BY location
    """).fetchall()
    db.close()
    return rows


def report_low_stock(threshold_g=200, threshold_pct=20):
    db = get_db()
    rows = db.execute("""
        WITH latest AS (
            SELECT spool_id, net_weight_g
            FROM weight_readings
            WHERE id IN (SELECT MAX(id) FROM weight_readings GROUP BY spool_id)
        )
        SELECT s.id, s.location, s.nominal_weight_g,
               f.brand, f.material, f.family, f.color_hex,
               COALESCE(l.net_weight_g, 0) AS current_net_g,
               CASE WHEN s.nominal_weight_g > 0
                    THEN CAST(COALESCE(l.net_weight_g,0)*100.0/s.nominal_weight_g AS INTEGER)
                    ELSE 0 END AS pct_remaining
        FROM spools s
        JOIN filaments f ON f.id = s.filament_id
        LEFT JOIN latest l ON l.spool_id = s.id
        WHERE s.active = 1
          AND (COALESCE(l.net_weight_g,0) < ? OR
               (s.nominal_weight_g > 0 AND COALESCE(l.net_weight_g,0)*100.0/s.nominal_weight_g < ?))
        ORDER BY COALESCE(l.net_weight_g, 0) ASC
    """, (threshold_g, threshold_pct)).fetchall()
    db.close()
    return rows


# ── Label Queue ────────────────────────────────────────────────────────────

def queue_add(spool_id):
    db = get_db()
    db.execute(
        "INSERT OR IGNORE INTO label_queue (spool_id, added_at) VALUES (?,?)",
        (spool_id, now_iso()),
    )
    db.commit()
    db.close()


def queue_remove(spool_id):
    db = get_db()
    db.execute("DELETE FROM label_queue WHERE spool_id=?", (spool_id,))
    db.commit()
    db.close()


def queue_list():
    db = get_db()
    rows = db.execute(f"""
        {_spool_query_base()}
        WHERE s.id IN (SELECT spool_id FROM label_queue)
        ORDER BY (SELECT added_at FROM label_queue WHERE spool_id = s.id)
    """).fetchall()
    db.close()
    return rows


def queue_ids():
    db = get_db()
    rows = db.execute("SELECT spool_id FROM label_queue").fetchall()
    db.close()
    return {r["spool_id"] for r in rows}


def queue_count():
    db = get_db()
    n = db.execute("SELECT COUNT(*) FROM label_queue").fetchone()[0]
    db.close()
    return n


def queue_clear():
    db = get_db()
    db.execute("DELETE FROM label_queue")
    db.commit()
    db.close()


def is_in_queue(spool_id):
    db = get_db()
    row = db.execute("SELECT 1 FROM label_queue WHERE spool_id=?", (spool_id,)).fetchone()
    db.close()
    return row is not None


# ── Search ─────────────────────────────────────────────────────────────────

def search_spools(q):
    db = get_db()
    p = f"%{q}%"
    rows = db.execute(
        f"""{_spool_query_base()}
            WHERE s.active=1 AND (
                f.brand LIKE ? OR f.material LIKE ? OR f.family LIKE ?
                OR s.location LIKE ? OR printf('SP-%04d', s.id) LIKE ?
            )
            ORDER BY f.material, f.brand, s.id LIMIT 100""",
        (p, p, p, p, p),
    ).fetchall()
    db.close()
    return rows


def search_filaments(q):
    db = get_db()
    p = f"%{q}%"
    rows = db.execute("""
        SELECT f.*,
               COUNT(s.id) AS spool_count,
               SUM(CASE WHEN s.active=1 THEN 1 ELSE 0 END) AS active_count,
               COALESCE(SUM(CASE WHEN s.active=1 THEN s.nominal_weight_g ELSE 0 END), 0) AS total_nominal_g,
               COALESCE(SUM(CASE WHEN s.active=1 THEN COALESCE(lw.net_weight_g, s.nominal_weight_g) ELSE 0 END), 0) AS total_net_g
        FROM filaments f
        LEFT JOIN spools s ON s.filament_id = f.id
        LEFT JOIN (
            SELECT spool_id, net_weight_g
            FROM weight_readings
            WHERE id IN (SELECT MAX(id) FROM weight_readings GROUP BY spool_id)
        ) lw ON lw.spool_id = s.id
        WHERE f.brand LIKE ? OR f.material LIKE ? OR f.family LIKE ?
        GROUP BY f.id ORDER BY f.material, f.brand LIMIT 100
    """, (p, p, p)).fetchall()
    db.close()
    return rows


# ── Materials ──────────────────────────────────────────────────────────────

def get_materials_in_use():
    db = get_db()
    rows = db.execute("SELECT DISTINCT material FROM filaments ORDER BY material").fetchall()
    db.close()
    return [r["material"] for r in rows]


def dashboard_stats():
    db = get_db()
    total_spools = db.execute("SELECT COUNT(*) FROM spools WHERE active=1").fetchone()[0]
    total_filaments = db.execute("SELECT COUNT(*) FROM filaments").fetchone()[0]
    recent_weighings = db.execute("""
        SELECT wr.ts, wr.net_weight_g, f.brand, f.material, f.family, s.id AS spool_id
        FROM weight_readings wr
        JOIN spools s ON s.id = wr.spool_id
        JOIN filaments f ON f.id = s.filament_id
        ORDER BY wr.ts DESC LIMIT 5
    """).fetchall()
    db.close()
    return {
        "total_spools": total_spools,
        "total_filaments": total_filaments,
        "recent_weighings": recent_weighings,
    }
