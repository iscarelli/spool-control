import sqlite3
import os
import secrets
import colorsys
from contextlib import closing
from pathlib import Path
from datetime import datetime, timezone, timedelta
import logger as log_cfg

_log = log_cfg.get_logger("spool.db")

# Caminho do banco. Default: data/spool.db ao lado do código. SPOOL_DB_PATH permite
# apontar para outro arquivo (usado pelos testes, que rodam contra um banco temporário).
DB_PATH = Path(os.environ.get("SPOOL_DB_PATH") or (Path(__file__).parent / "data" / "spool.db"))


def get_db():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
    return db


# Todas as funções abaixo usam `with closing(get_db()) as db:` — isso garante que a
# conexão seja FECHADA mesmo se a query lançar exceção no meio (sem o closing, um erro
# pulava o db.close() e vazava a conexão, podendo travar a escrita do SQLite em WAL).


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
        _log.error("backup.validation_failed", path=str(path), exc_info=True)
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
    with closing(get_db()) as db:
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

            -- Códigos de recuperação do 2FA: 8 one-time por usuário, guardados
            -- HASHEADOS (generate_password_hash). used_at != '' marca consumido.
            CREATE TABLE IF NOT EXISTS recovery_codes (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id   INTEGER NOT NULL REFERENCES users(id),
                code_hash TEXT    NOT NULL,
                used_at   TEXT    NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS brands (
                name       TEXT PRIMARY KEY,
                domain     TEXT NOT NULL DEFAULT '',
                logo_path  TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS api_keys (
                integration  TEXT PRIMARY KEY,              -- 'scale' | 'homeassistant'
                label        TEXT NOT NULL DEFAULT '',
                key          TEXT NOT NULL,
                scope        TEXT NOT NULL DEFAULT 'read',  -- 'read' | 'write' (write inclui read)
                enabled      INTEGER NOT NULL DEFAULT 1,
                created_at   TEXT NOT NULL,
                last_used_at TEXT NOT NULL DEFAULT ''
            );

            INSERT OR IGNORE INTO brands (name)
            SELECT DISTINCT brand FROM filaments WHERE brand != '';

            INSERT OR IGNORE INTO settings (key, value) VALUES
                ('low_stock_threshold_g','200'),
                ('low_stock_pct',        '20'),
                ('label_width_mm',       '60'),
                ('label_height_mm',      '40');
        """)
        # app_base_url é semeado a partir do ambiente (APP_BASE_URL, definido na
        # instalação) — cada usuário roda no próprio servidor, então o QR precisa
        # apontar para a URL pública DELE, nunca para localhost.
        db.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES ('app_base_url', ?)",
            (os.environ.get("APP_BASE_URL", "").strip() or "http://localhost:5000",),
        )
        db.commit()

        # Migrations: adiciona colunas que não existiam em versões antigas do schema.
        # ALTER TABLE não suporta IF NOT EXISTS no SQLite — usamos try/except.
        for sql in [
            "ALTER TABLE brands ADD COLUMN domain     TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE brands ADD COLUMN updated_at TEXT NOT NULL DEFAULT ''",
            # Força troca de senha no próximo login (senha inicial/temporária). Default 0
            # para instalações existentes — só vale p/ admins do bootstrap e usuários
            # criados/resetados por um admin a partir desta versão.
            "ALTER TABLE users ADD COLUMN must_change_password INTEGER NOT NULL DEFAULT 0",
            # 2FA opcional (TOTP) por usuário. Segredo em texto (precisa do plaintext
            # p/ validar, mesmo precedente das API keys); off por padrão.
            "ALTER TABLE users ADD COLUMN totp_secret  TEXT    NOT NULL DEFAULT ''",
            "ALTER TABLE users ADD COLUMN totp_enabled INTEGER NOT NULL DEFAULT 0",
        ]:
            try:
                db.execute(sql)
            except sqlite3.OperationalError:
                pass  # coluna já existe
        db.commit()


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── Users ──────────────────────────────────────────────────────────────────

def get_user_by_username(username):
    with closing(get_db()) as db:
        return db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()


def get_user_by_id(user_id):
    with closing(get_db()) as db:
        return db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()


def list_users():
    with closing(get_db()) as db:
        return db.execute("SELECT * FROM users ORDER BY username").fetchall()


def ensure_admin_user(username, password_hash, must_change=True):
    with closing(get_db()) as db:
        db.execute(
            "INSERT OR IGNORE INTO users (username, password_hash, role, created_at, must_change_password) VALUES (?,?,?,?,?)",
            (username, password_hash, "admin", now_iso(), 1 if must_change else 0),
        )
        db.commit()


def create_user(username, password_hash, role="viewer", must_change=True):
    with closing(get_db()) as db:
        db.execute(
            "INSERT INTO users (username, password_hash, role, created_at, must_change_password) VALUES (?,?,?,?,?)",
            (username, password_hash, role, now_iso(), 1 if must_change else 0),
        )
        db.commit()


def update_user_password(user_id, password_hash, must_change=False):
    with closing(get_db()) as db:
        db.execute(
            "UPDATE users SET password_hash=?, must_change_password=? WHERE id=?",
            (password_hash, 1 if must_change else 0, user_id),
        )
        db.commit()


def set_must_change_password(user_id, must_change):
    with closing(get_db()) as db:
        db.execute(
            "UPDATE users SET must_change_password=? WHERE id=?",
            (1 if must_change else 0, user_id),
        )
        db.commit()


def delete_user(user_id):
    with closing(get_db()) as db:
        db.execute("DELETE FROM users WHERE id=?", (user_id,))
        db.commit()


def log_login(username, ip):
    with closing(get_db()) as db:
        db.execute(
            "INSERT INTO login_log (ts, username, ip) VALUES (?,?,?)",
            (now_iso(), username, ip),
        )
        db.commit()


# ── 2FA (TOTP opcional por usuário) ──────────────────────────────────────────
# Segredo TOTP em texto (igual às API keys; preciso p/ validar). Códigos de
# recuperação ficam HASHEADOS na tabela recovery_codes. Tudo opt-in: off até o
# usuário ativar em /account/2fa.

def set_totp_secret(user_id, secret):
    with closing(get_db()) as db:
        db.execute("UPDATE users SET totp_secret=? WHERE id=?", (secret, user_id))
        db.commit()


def enable_totp(user_id):
    with closing(get_db()) as db:
        db.execute("UPDATE users SET totp_enabled=1 WHERE id=?", (user_id,))
        db.commit()


def disable_totp(user_id):
    """Desliga o 2FA: zera o segredo, o flag e apaga TODOS os códigos de recuperação."""
    with closing(get_db()) as db:
        db.execute(
            "UPDATE users SET totp_secret='', totp_enabled=0 WHERE id=?", (user_id,)
        )
        db.execute("DELETE FROM recovery_codes WHERE user_id=?", (user_id,))
        db.commit()


def store_recovery_codes(user_id, code_hashes):
    """Substitui os códigos de recuperação do usuário pelos novos (já hasheados)."""
    with closing(get_db()) as db:
        db.execute("DELETE FROM recovery_codes WHERE user_id=?", (user_id,))
        db.executemany(
            "INSERT INTO recovery_codes (user_id, code_hash) VALUES (?,?)",
            [(user_id, h) for h in code_hashes],
        )
        db.commit()


def consume_recovery_code(user_id, code):
    """Acha um código não-usado cujo hash bate com `code`, marca como usado e
    retorna True. Retorna False se nenhum bate (ou todos já foram usados).
    O check é feito em Python (hashes são por-código, não dá p/ comparar em SQL)."""
    from werkzeug.security import check_password_hash
    with closing(get_db()) as db:
        rows = db.execute(
            "SELECT id, code_hash FROM recovery_codes WHERE user_id=? AND used_at=''",
            (user_id,),
        ).fetchall()
        for r in rows:
            if check_password_hash(r["code_hash"], code):
                db.execute(
                    "UPDATE recovery_codes SET used_at=? WHERE id=?",
                    (now_iso(), r["id"]),
                )
                db.commit()
                return True
    return False


def count_recovery_codes_remaining(user_id):
    with closing(get_db()) as db:
        return db.execute(
            "SELECT COUNT(*) FROM recovery_codes WHERE user_id=? AND used_at=''",
            (user_id,),
        ).fetchone()[0]


# ── Login throttle (anti força-bruta) ──────────────────────────────────────

def record_login_failure(ip, username):
    with closing(get_db()) as db:
        db.execute(
            "INSERT INTO login_failures (ts, ip, username) VALUES (?,?,?)",
            (now_iso(), ip, username),
        )
        db.commit()


def count_recent_login_failures(ip, window_minutes):
    """Falhas de login deste IP nos últimos window_minutes."""
    cutoff = (datetime.now(timezone.utc)
              - timedelta(minutes=window_minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")
    with closing(get_db()) as db:
        return db.execute(
            "SELECT COUNT(*) FROM login_failures WHERE ip=? AND ts >= ?",
            (ip, cutoff),
        ).fetchone()[0]


def clear_login_failures(ip):
    with closing(get_db()) as db:
        db.execute("DELETE FROM login_failures WHERE ip=?", (ip,))
        db.commit()


# ── Settings ───────────────────────────────────────────────────────────────

def get_setting(key, default=""):
    with closing(get_db()) as db:
        row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(key, value):
    with closing(get_db()) as db:
        db.execute(
            "INSERT INTO settings (key, value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        db.commit()


def get_all_settings():
    with closing(get_db()) as db:
        rows = db.execute("SELECT key, value FROM settings ORDER BY key").fetchall()
    return {r["key"]: r["value"] for r in rows}


# ── API keys (integrações: balança, Home Assistant, …) ───────────────────────
# Uma chave por integração (slug). Chaves independentes: rotacionar uma não afeta
# as outras. scope 'write' (balança, grava pesagem) inclui 'read'; 'read' (HA) só lê.

def new_api_token():
    return secrets.token_urlsafe(32)


def list_api_keys():
    with closing(get_db()) as db:
        return db.execute("SELECT * FROM api_keys ORDER BY integration").fetchall()


def get_api_key(integration):
    with closing(get_db()) as db:
        return db.execute(
            "SELECT * FROM api_keys WHERE integration=?", (integration,)
        ).fetchone()


def ensure_api_key(integration, scope="read", label="", key=None, enabled=True):
    """Cria a chave da integração se ainda não existir (idempotente). Usado no seed."""
    with closing(get_db()) as db:
        db.execute(
            """INSERT OR IGNORE INTO api_keys
               (integration, label, key, scope, enabled, created_at)
               VALUES (?,?,?,?,?,?)""",
            (integration, label, key or new_api_token(), scope,
             1 if enabled else 0, now_iso()),
        )
        db.commit()


def regenerate_api_key(integration):
    """Gera um novo token SÓ para esta integração (não toca nas outras)."""
    token = new_api_token()
    with closing(get_db()) as db:
        db.execute(
            "UPDATE api_keys SET key=?, created_at=? WHERE integration=?",
            (token, now_iso(), integration),
        )
        db.commit()
    return token


def set_api_key_enabled(integration, enabled):
    with closing(get_db()) as db:
        db.execute(
            "UPDATE api_keys SET enabled=? WHERE integration=?",
            (1 if enabled else 0, integration),
        )
        db.commit()


def touch_api_key(integration):
    with closing(get_db()) as db:
        db.execute(
            "UPDATE api_keys SET last_used_at=? WHERE integration=?",
            (now_iso(), integration),
        )
        db.commit()


def verify_api_key(presented, need_write=False):
    """Slug da integração cuja chave (habilitada) casa com `presented`, ou None.
    Timing-safe; se need_write, exige scope='write'. Fallback: aceita a env
    SPOOL_API_KEY legada (escopo write) p/ não quebrar installs antigos."""
    presented = presented or ""
    with closing(get_db()) as db:
        rows = db.execute(
            "SELECT integration, key, scope FROM api_keys WHERE enabled=1"
        ).fetchall()
    for r in rows:
        if secrets.compare_digest(presented, r["key"]):
            if need_write and r["scope"] != "write":
                continue
            return r["integration"]
    env_key = os.environ.get("SPOOL_API_KEY", "").strip()
    if env_key and secrets.compare_digest(presented, env_key):
        return "scale"   # legado: env sempre tratada como balança (write)
    return None


# ── Brands ─────────────────────────────────────────────────────────────────

def list_brands():
    with closing(get_db()) as db:
        return db.execute("""
            SELECT b.*, COUNT(DISTINCT f.id) AS filament_count
            FROM brands b
            LEFT JOIN filaments f ON f.brand = b.name
            GROUP BY b.name ORDER BY b.name
        """).fetchall()


def list_brands_ordered():
    with closing(get_db()) as db:
        return db.execute("""
            SELECT b.name, b.logo_path,
                   COUNT(DISTINCT f.id) AS filament_count
            FROM brands b
            LEFT JOIN filaments f ON f.brand = b.name
            GROUP BY b.name
            ORDER BY
                CASE WHEN COUNT(DISTINCT f.id) > 0 THEN 0 ELSE 1 END,
                b.name
        """).fetchall()


def get_brand(name):
    with closing(get_db()) as db:
        return db.execute("SELECT * FROM brands WHERE name=?", (name,)).fetchone()


def create_brand(name, domain=""):
    with closing(get_db()) as db:
        db.execute(
            "INSERT OR IGNORE INTO brands (name, domain) VALUES (?,?)",
            (name, domain),
        )
        db.commit()


def delete_brand(name):
    with closing(get_db()) as db:
        count = db.execute(
            "SELECT COUNT(*) FROM filaments WHERE brand=?", (name,)
        ).fetchone()[0]
        if count > 0:
            raise ValueError("Marca possui filamentos vinculados — remova-os antes")
        db.execute("DELETE FROM brands WHERE name=?", (name,))
        db.commit()


def update_brand_domain(name, domain):
    with closing(get_db()) as db:
        db.execute(
            "INSERT INTO brands (name, domain) VALUES (?,?) ON CONFLICT(name) DO UPDATE SET domain=excluded.domain",
            (name, domain),
        )
        db.commit()


def update_brand_logo_path(name, logo_path):
    with closing(get_db()) as db:
        db.execute(
            "UPDATE brands SET logo_path=?, updated_at=? WHERE name=?",
            (logo_path, now_iso(), name),
        )
        db.commit()


# ── Spool Models ───────────────────────────────────────────────────────────

def list_spool_models():
    with closing(get_db()) as db:
        return db.execute("SELECT * FROM spool_models ORDER BY name").fetchall()


def get_spool_model(model_id):
    with closing(get_db()) as db:
        return db.execute("SELECT * FROM spool_models WHERE id=?", (model_id,)).fetchone()


def create_spool_model(name, tare_weight_g, notes=""):
    with closing(get_db()) as db:
        db.execute(
            "INSERT INTO spool_models (name, tare_weight_g, notes, created_at) VALUES (?,?,?,?)",
            (name, tare_weight_g, notes, now_iso()),
        )
        db.commit()


def update_spool_model(model_id, name, tare_weight_g, notes=""):
    with closing(get_db()) as db:
        db.execute(
            "UPDATE spool_models SET name=?, tare_weight_g=?, notes=? WHERE id=?",
            (name, tare_weight_g, notes, model_id),
        )
        db.commit()


def delete_spool_model(model_id):
    with closing(get_db()) as db:
        count = db.execute(
            "SELECT COUNT(*) FROM spools WHERE spool_model_id=?", (model_id,)
        ).fetchone()[0]
        if count > 0:
            raise ValueError("Modelo em uso por spools existentes")
        db.execute("DELETE FROM spool_models WHERE id=?", (model_id,))
        db.commit()


# ── Filaments ──────────────────────────────────────────────────────────────

def list_filaments():
    with closing(get_db()) as db:
        return db.execute("""
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


def get_filament(filament_id):
    with closing(get_db()) as db:
        return db.execute("""
            SELECT f.*, b.logo_path AS brand_logo
            FROM filaments f
            LEFT JOIN brands b ON b.name = f.brand
            WHERE f.id=?
        """, (filament_id,)).fetchone()


def create_filament(brand, material, family, color_hex="", diameter_mm=1.75, notes=""):
    with closing(get_db()) as db:
        db.execute(
            "INSERT INTO filaments (brand, material, family, color_hex, diameter_mm, notes, created_at) VALUES (?,?,?,?,?,?,?)",
            (brand, material, family, color_hex, diameter_mm, notes, now_iso()),
        )
        last = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.execute("INSERT OR IGNORE INTO brands (name) VALUES (?)", (brand,))
        db.commit()
    return last


def update_filament(filament_id, brand, material, family, color_hex="", diameter_mm=1.75, notes=""):
    with closing(get_db()) as db:
        db.execute(
            "UPDATE filaments SET brand=?, material=?, family=?, color_hex=?, diameter_mm=?, notes=? WHERE id=?",
            (brand, material, family, color_hex, diameter_mm, notes, filament_id),
        )
        db.execute("INSERT OR IGNORE INTO brands (name) VALUES (?)", (brand,))
        db.commit()


def delete_filament(filament_id):
    with closing(get_db()) as db:
        count = db.execute(
            "SELECT COUNT(*) FROM spools WHERE filament_id=?", (filament_id,)
        ).fetchone()[0]
        if count > 0:
            raise ValueError("Filamento possui spools associados")
        db.execute("DELETE FROM filaments WHERE id=?", (filament_id,))
        db.commit()


# ── Spools ─────────────────────────────────────────────────────────────────

def _spool_query_base():
    return """
        SELECT s.*,
               f.brand, f.material, f.family, f.color_hex, f.diameter_mm,
               b.logo_path AS brand_logo,
               sm.name AS model_name,
               COALESCE(s.custom_tare_g, sm.tare_weight_g, 0) AS effective_tare_g,
               wr.net_weight_g AS current_net_g,
               wr.gross_weight_g AS current_gross_g,
               wr.ts AS last_weighed_at
        FROM spools s
        JOIN filaments f ON f.id = s.filament_id
        LEFT JOIN brands b ON b.name = f.brand
        LEFT JOIN spool_models sm ON sm.id = s.spool_model_id
        LEFT JOIN weight_readings wr ON wr.id = (
            SELECT MAX(id) FROM weight_readings WHERE spool_id = s.id
        )
    """


def list_spools(active_only=True):
    where = "WHERE s.active=1" if active_only else ""
    with closing(get_db()) as db:
        return db.execute(
            f"{_spool_query_base()} {where} ORDER BY f.material, f.brand, f.family, s.id"
        ).fetchall()


def get_spool(spool_id):
    with closing(get_db()) as db:
        return db.execute(
            f"{_spool_query_base()} WHERE s.id=?", (spool_id,)
        ).fetchone()


def list_spools_for_filament(filament_id):
    with closing(get_db()) as db:
        return db.execute(
            f"{_spool_query_base()} WHERE s.filament_id=? ORDER BY s.id",
            (filament_id,),
        ).fetchall()


def create_spool(filament_id, spool_model_id, custom_tare_g, nominal_weight_g,
                 location, purchase_date, purchase_price, notes):
    with closing(get_db()) as db:
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
    return last


def update_spool(spool_id, filament_id, spool_model_id, custom_tare_g, nominal_weight_g,
                 location, purchase_date, purchase_price, notes):
    with closing(get_db()) as db:
        db.execute(
            """UPDATE spools SET filament_id=?, spool_model_id=?, custom_tare_g=?, nominal_weight_g=?,
               location=?, purchase_date=?, purchase_price=?, notes=?
               WHERE id=?""",
            (filament_id, spool_model_id or None, custom_tare_g or None, nominal_weight_g,
             location, purchase_date, purchase_price or None, notes, spool_id),
        )
        db.commit()


def deactivate_spool(spool_id):
    with closing(get_db()) as db:
        db.execute("UPDATE spools SET active=0 WHERE id=?", (spool_id,))
        db.commit()


# ── Weight Readings ────────────────────────────────────────────────────────

def add_weight_reading(spool_id, gross_weight_g, tare_weight_g, recorded_by="", notes=""):
    with closing(get_db()) as db:
        db.execute(
            """INSERT INTO weight_readings
               (spool_id, gross_weight_g, tare_weight_g, ts, recorded_by, notes)
               VALUES (?,?,?,?,?,?)""",
            (spool_id, gross_weight_g, tare_weight_g, now_iso(), recorded_by, notes),
        )
        db.commit()


def list_weight_readings(spool_id=None, filament_id=None, limit=200):
    with closing(get_db()) as db:
        if spool_id:
            return db.execute(
                """SELECT wr.*, f.brand, f.material, f.family, s.location
                   FROM weight_readings wr
                   JOIN spools s ON s.id = wr.spool_id
                   JOIN filaments f ON f.id = s.filament_id
                   WHERE wr.spool_id=?
                   ORDER BY wr.ts DESC LIMIT ?""",
                (spool_id, limit),
            ).fetchall()
        elif filament_id:
            return db.execute(
                """SELECT wr.*, f.brand, f.material, f.family, s.location
                   FROM weight_readings wr
                   JOIN spools s ON s.id = wr.spool_id
                   JOIN filaments f ON f.id = s.filament_id
                   WHERE s.filament_id=?
                   ORDER BY wr.ts DESC LIMIT ?""",
                (filament_id, limit),
            ).fetchall()
        else:
            return db.execute(
                """SELECT wr.*, f.brand, f.material, f.family, s.location
                   FROM weight_readings wr
                   JOIN spools s ON s.id = wr.spool_id
                   JOIN filaments f ON f.id = s.filament_id
                   ORDER BY wr.ts DESC LIMIT ?""",
                (limit,),
            ).fetchall()


# ── Reports ────────────────────────────────────────────────────────────────

def report_by_material():
    with closing(get_db()) as db:
        return db.execute("""
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


def report_by_location():
    with closing(get_db()) as db:
        return db.execute("""
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


def report_low_stock(threshold_g=200, threshold_pct=20):
    with closing(get_db()) as db:
        return db.execute("""
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


# ── Label Queue ────────────────────────────────────────────────────────────

def queue_add(spool_id):
    with closing(get_db()) as db:
        db.execute(
            "INSERT OR IGNORE INTO label_queue (spool_id, added_at) VALUES (?,?)",
            (spool_id, now_iso()),
        )
        db.commit()


def queue_remove(spool_id):
    with closing(get_db()) as db:
        db.execute("DELETE FROM label_queue WHERE spool_id=?", (spool_id,))
        db.commit()


def queue_list():
    with closing(get_db()) as db:
        return db.execute(f"""
            {_spool_query_base()}
            WHERE s.id IN (SELECT spool_id FROM label_queue)
            ORDER BY (SELECT added_at FROM label_queue WHERE spool_id = s.id)
        """).fetchall()


def queue_ids():
    with closing(get_db()) as db:
        rows = db.execute("SELECT spool_id FROM label_queue").fetchall()
    return {r["spool_id"] for r in rows}


def queue_count():
    with closing(get_db()) as db:
        return db.execute("SELECT COUNT(*) FROM label_queue").fetchone()[0]


def queue_clear():
    with closing(get_db()) as db:
        db.execute("DELETE FROM label_queue")
        db.commit()


def is_in_queue(spool_id):
    with closing(get_db()) as db:
        row = db.execute("SELECT 1 FROM label_queue WHERE spool_id=?", (spool_id,)).fetchone()
    return row is not None


# ── Search ─────────────────────────────────────────────────────────────────

def search_spools(q):
    p = f"%{q}%"
    with closing(get_db()) as db:
        return db.execute(
            f"""{_spool_query_base()}
                WHERE s.active=1 AND (
                    f.brand LIKE ? OR f.material LIKE ? OR f.family LIKE ?
                    OR s.location LIKE ? OR printf('SP-%04d', s.id) LIKE ?
                )
                ORDER BY f.material, f.brand, s.id LIMIT 100""",
            (p, p, p, p, p),
        ).fetchall()


def search_filaments(q):
    p = f"%{q}%"
    with closing(get_db()) as db:
        return db.execute("""
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


# ── Materials ──────────────────────────────────────────────────────────────

def get_materials_in_use():
    with closing(get_db()) as db:
        rows = db.execute("SELECT DISTINCT material FROM filaments ORDER BY material").fetchall()
    return [r["material"] for r in rows]


# Baldes de cor básicos (nome PT → hex representante da barra). O nome é a chave
# de tradução usada no template (_()); EN/ES em translations.py.
COLOR_BUCKETS = {
    "Preto":    "#222222",
    "Branco":   "#f5f5f5",
    "Cinza":    "#9aa0a6",
    "Vermelho": "#c0392b",
    "Laranja":  "#e67e22",
    "Amarelo":  "#f1c40f",
    "Verde":    "#27ae60",
    "Ciano":    "#1abc9c",
    "Azul":     "#2e6fd6",
    "Roxo":     "#8e44ad",
    "Rosa":     "#e84393",
    "Marrom":   "#8a5a2b",
}


def classify_color(hex_str):
    """Mapeia um #RRGGBB para um balde de cor básico (junta todos os verdes,
    vermelhos, etc.). Retorna None se o hex for inválido/ausente."""
    s = (hex_str or "").strip().lstrip("#")
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    if len(s) != 6:
        return None
    try:
        r = int(s[0:2], 16) / 255.0
        g = int(s[2:4], 16) / 255.0
        b = int(s[4:6], 16) / 255.0
    except ValueError:
        return None
    h, sat, val = colorsys.rgb_to_hsv(r, g, b)
    hue = h * 360
    if val < 0.18:
        return "Preto"
    if sat < 0.15:
        return "Branco" if val > 0.75 else "Cinza"
    if 10 <= hue < 45 and val < 0.6 and sat > 0.3:
        return "Marrom"
    if hue < 20 or hue >= 345:
        return "Vermelho"
    if hue < 45:
        return "Laranja"
    if hue < 66:
        return "Amarelo"
    if hue < 170:
        return "Verde"
    if hue < 200:
        return "Ciano"
    if hue < 255:
        return "Azul"
    if hue < 290:
        return "Roxo"
    return "Rosa"


def stats_counts():
    """Contagem de spools ATIVOS por marca, material e COR (classificada a partir
    do color_hex). Cada lista vem ordenada por contagem desc."""
    with closing(get_db()) as db:
        brands = db.execute("""
            SELECT f.brand AS name, COUNT(*) AS cnt
            FROM spools s JOIN filaments f ON f.id = s.filament_id
            WHERE s.active = 1
            GROUP BY f.brand ORDER BY cnt DESC, f.brand
        """).fetchall()
        materials = db.execute("""
            SELECT f.material AS name, COUNT(*) AS cnt
            FROM spools s JOIN filaments f ON f.id = s.filament_id
            WHERE s.active = 1
            GROUP BY f.material ORDER BY cnt DESC, f.material
        """).fetchall()
        color_rows = db.execute("""
            SELECT f.color_hex AS hex
            FROM spools s JOIN filaments f ON f.id = s.filament_id
            WHERE s.active = 1
        """).fetchall()
    # Agrupa por balde de cor derivado do hexa.
    buckets = {}
    for r in color_rows:
        name = classify_color(r["hex"])
        if not name:
            continue
        buckets[name] = buckets.get(name, 0) + 1
    colors = sorted(
        ({"name": n, "cnt": c, "color": COLOR_BUCKETS[n]} for n, c in buckets.items()),
        key=lambda d: (-d["cnt"], d["name"]),
    )
    return {
        "brands":    [dict(r) for r in brands],
        "materials": [dict(r) for r in materials],
        "colors":    colors,
    }


def list_inventory(q=None):
    """Spools ATIVOS para o grid de inventário — um item por spool físico
    ('repete' filamentos). Inclui o logo da marca p/ o modal de detalhe."""
    sql = """
        SELECT s.id, s.location, s.notes, s.nominal_weight_g, s.purchase_date,
               f.brand, f.material, f.family, f.color_hex, f.diameter_mm,
               b.logo_path AS brand_logo,
               COALESCE(s.custom_tare_g, sm.tare_weight_g, 0) AS effective_tare_g,
               sm.name AS model_name,
               wr.net_weight_g AS current_net_g,
               wr.ts AS last_weighed_at
        FROM spools s
        JOIN filaments f ON f.id = s.filament_id
        LEFT JOIN spool_models sm ON sm.id = s.spool_model_id
        LEFT JOIN brands b ON b.name = f.brand
        LEFT JOIN weight_readings wr ON wr.id = (
            SELECT MAX(id) FROM weight_readings WHERE spool_id = s.id
        )
        WHERE s.active = 1
    """
    params = []
    if q:
        p = f"%{q}%"
        sql += (" AND (f.brand LIKE ? OR f.material LIKE ? OR f.family LIKE ?"
                " OR s.location LIKE ? OR printf('SP-%04d', s.id) LIKE ?)")
        params = [p, p, p, p, p]
    sql += " ORDER BY f.material, f.brand, f.family, s.id"
    with closing(get_db()) as db:
        return db.execute(sql, params).fetchall()


def dashboard_stats():
    with closing(get_db()) as db:
        total_spools = db.execute("SELECT COUNT(*) FROM spools WHERE active=1").fetchone()[0]
        total_filaments = db.execute("SELECT COUNT(*) FROM filaments").fetchone()[0]
        recent_weighings = db.execute("""
            SELECT wr.ts, wr.net_weight_g, f.brand, f.material, f.family, s.id AS spool_id
            FROM weight_readings wr
            JOIN spools s ON s.id = wr.spool_id
            JOIN filaments f ON f.id = s.filament_id
            ORDER BY wr.ts DESC LIMIT 5
        """).fetchall()
    return {
        "total_spools": total_spools,
        "total_filaments": total_filaments,
        "recent_weighings": recent_weighings,
    }
