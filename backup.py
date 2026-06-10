"""Backup do Spool Control — lógica compartilhada entre o backup manual (download
pela UI), o backup agendado (rotação diária por dia da semana) e a restauração.

Mantém-se livre de Flask/`app` de propósito: o cron (`deploy/backup-cron.py`) importa
este módulo sem subir o app. O artefato é o MESMO zip do download manual (spool.db +
logos + manifest), então qualquer backup é restaurável pela mesma UI.
"""
import io
import os
import json
import time
import shutil
import zipfile
import tempfile
from pathlib import Path
from datetime import datetime, timezone

import database as db
import logger as log_cfg

log = log_cfg.get_logger("spool.backup")

ROOT = Path(__file__).parent
BRANDS_DIR = ROOT / "static" / "brands"
VERSION_FILE = ROOT / "VERSION"
# Pasta da rotação diária (ao lado do banco — volume persistido, no .gitignore).
BACKUPS_DIR = db.DB_PATH.parent / "backups"
# Extensões de logo aceitas no zip (espelha o upload de marcas; SVG fica de fora).
LOGO_EXTS = ('.png', '.jpg', '.jpeg', '.webp')
# Slots da rotação: 1..7 = dia da semana ISO (seg..dom). Número (não nome) p/ ser
# independente de idioma; a data REAL de cada arquivo vem do mtime (mostrada na UI).
SLOTS = range(1, 8)


def _app_version():
    try:
        return VERSION_FILE.read_text().strip()
    except Exception:
        return "?"


def _add_entries(z, db_path):
    """Escreve spool.db + logos + manifest num ZipFile aberto."""
    z.write(db_path, "spool.db")
    if BRANDS_DIR.is_dir():
        for p in sorted(BRANDS_DIR.iterdir()):
            if p.is_file() and p.suffix.lower() in LOGO_EXTS:
                z.write(p, f"brands/{p.name}")
    z.writestr("manifest.json", json.dumps({
        "app": "spool-control",
        "version": _app_version(),
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }, indent=2))


# ── Geração ──────────────────────────────────────────────────────────────────

def make_backup_bytes():
    """Zip do backup em memória — usado pelo download manual (mantém o formato)."""
    mem = io.BytesIO()
    tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp_db.close()
    try:
        db.backup_to(tmp_db.name)
        with zipfile.ZipFile(mem, "w", zipfile.ZIP_DEFLATED) as z:
            _add_entries(z, tmp_db.name)
    finally:
        os.remove(tmp_db.name)
    mem.seek(0)
    return mem.read()


def make_backup_file(dest_path):
    """Gera o zip em dest_path com snapshot VALIDADO e escrita ATÔMICA (grava em
    .tmp e renomeia — nunca sobrescreve um backup bom com lixo). chmod 600 porque
    o backup contém hashes de senha e todos os dados."""
    dest_path = Path(dest_path)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp_db.close()
    tmp_zip = dest_path.parent / (dest_path.name + ".tmp")
    try:
        db.backup_to(tmp_db.name)
        if not db.is_valid_backup_db(tmp_db.name):
            raise RuntimeError("snapshot do banco inválido — backup abortado")
        with zipfile.ZipFile(tmp_zip, "w", zipfile.ZIP_DEFLATED) as z:
            _add_entries(z, tmp_db.name)
        try:
            os.chmod(tmp_zip, 0o600)
        except OSError:
            pass  # Windows/dev: chmod best-effort
        os.replace(tmp_zip, dest_path)   # atômico no mesmo filesystem
    finally:
        os.remove(tmp_db.name)
        if tmp_zip.exists():
            try:
                os.remove(tmp_zip)
            except OSError:
                pass
    return dest_path


def _copy_atomic(src, dest_dir, name):
    """Copia src p/ dest_dir/name de forma atômica (temp + replace). chmod 600."""
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    tmp = dest_dir / (name + ".tmp")
    shutil.copyfile(src, tmp)
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    os.replace(tmp, dest_dir / name)
    return dest_dir / name


# ── Backup agendado (rotação diária) ─────────────────────────────────────────

def slot_today():
    """Slot do dia: dia da semana ISO no horário LOCAL (1=seg … 7=dom)."""
    return datetime.now().isoweekday()


def slot_filename(slot):
    return f"spool-backup-{slot}.zip"


def backup_hour():
    """Hora LOCAL (0..23) configurada p/ o backup diário. Default 3 (03:00).
    Valor inválido cai no default — nunca derruba o backup."""
    try:
        h = int(db.get_setting("backup_hour", "3"))
    except (TypeError, ValueError):
        return 3
    return h if 0 <= h <= 23 else 3


def _ran_ok_today():
    """True se já houve um backup BEM-SUCEDIDO hoje (data LOCAL). Torna o disparo
    horário idempotente e o catch-up do `Persistent=` inofensivo; um backup que
    FALHOU não conta, então a próxima hora tenta de novo até dar certo."""
    if db.get_setting("backup_last_result", "") != "ok":
        return False
    last = db.get_setting("backup_last_run", "")
    if not last:
        return False
    try:  # backup_last_run é UTC (db.now_iso) — converte p/ data local antes de comparar.
        when = datetime.strptime(last, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return False
    return when.astimezone().date() == datetime.now().date()


def due_now():
    """O timer acorda de hora em hora; só rodamos a partir da hora configurada e
    enquanto não houve sucesso hoje. Usar `>=` (não `==`) preserva o catch-up: se a
    máquina estava desligada na hora marcada e liga depois no mesmo dia, ainda roda."""
    return datetime.now().hour >= backup_hour() and not _ran_ok_today()


def run_scheduled_backup(force=False):
    """Backup diário rotativo: grava sempre local em data/backups/spool-backup-<N>.zip
    (N = dia da semana). Se `backup_external_dir` estiver configurado, copia também.
    Persiste o status em settings p/ a UI alertar. Retorna o caminho local ou None.

    O timer dispara de hora em hora; sem `force`, só executa quando `due_now()` —
    nas demais horas é um tick silencioso (não mexe no status). `force=True` ignora
    o agendamento (backup manual)."""
    if not force and not due_now():
        return None
    now = db.now_iso()
    slot = slot_today()
    name = slot_filename(slot)
    local = BACKUPS_DIR / name
    try:
        make_backup_file(local)
        db.set_setting("backup_last_run", now)
        db.set_setting("backup_last_result", "ok")
        db.set_setting("backup_last_error", "")
        log.info("backup.created", file=str(local), slot=slot,
                 size=local.stat().st_size)
    except Exception as e:
        db.set_setting("backup_last_run", now)
        db.set_setting("backup_last_result", "error")
        db.set_setting("backup_last_error", str(e))
        log.error("backup.failed", exc_info=True)
        return None

    # Cópia externa (opcional). Falha aqui NÃO invalida o backup local — só alerta.
    ext = (db.get_setting("backup_external_dir", "") or "").strip()
    if not ext:
        db.set_setting("backup_external_error", "")
        return local
    try:
        dest = _copy_atomic(local, ext, name)
        db.set_setting("backup_external_error", "")
        log.info("backup.external_copied", dest=str(dest))
    except Exception as e:
        db.set_setting("backup_external_error", str(e))
        log.error("backup.external_failed", dest=ext, exc_info=True)
    return local


def test_external_writable(path):
    """Testa se a pasta externa é gravável (criando-a se preciso). Devolve ''
    quando OK ou uma mensagem de erro — usado ao salvar a configuração."""
    try:
        d = Path(path)
        d.mkdir(parents=True, exist_ok=True)
        probe = d / ".spool-write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return ""
    except Exception as e:
        return str(e)


def list_local_backups():
    """Os 7 slots, com data REAL (mtime) e tamanho dos que existem — p/ a tabela
    da UI. A data vem do arquivo; o número é só o identificador do slot."""
    out = []
    for slot in SLOTS:
        p = BACKUPS_DIR / slot_filename(slot)
        if p.exists():
            st = p.stat()
            out.append({
                "slot": slot,
                "name": p.name,
                "exists": True,
                # mtime local em formato que o filtro localdt do template entende.
                "mtime": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                "size_kb": round(st.st_size / 1024),
            })
        else:
            out.append({"slot": slot, "name": slot_filename(slot), "exists": False})
    return out


# ── Restauração (compartilhada: upload e backup local) ───────────────────────

def restore_from_zip_bytes(data):
    """Restaura a partir dos bytes de um zip de backup. Valida ANTES de tocar no
    banco ativo; anti zip-slip nos logos. Devolve (ok, n_logos, erro)."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except Exception:
        return (False, 0, "not_zip")
    names = zf.namelist()
    if "spool.db" not in names:
        return (False, 0, "no_db")
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    try:
        tmp.write(zf.read("spool.db"))
        tmp.close()
        if not db.is_valid_backup_db(tmp.name):
            return (False, 0, "invalid_db")
        db.restore_from(tmp.name)
    finally:
        os.remove(tmp.name)
    BRANDS_DIR.mkdir(parents=True, exist_ok=True)
    restored = 0
    for n in names:
        if not n.startswith("brands/") or n.endswith("/"):
            continue
        base = os.path.basename(n)   # anti zip-slip
        if not base or Path(base).suffix.lower() not in LOGO_EXTS:
            continue
        (BRANDS_DIR / base).write_bytes(zf.read(n))
        restored += 1
    return (True, restored, "")


def read_local_backup_bytes(slot):
    """Bytes do backup do slot (1..7), ou None se não existir."""
    try:
        slot = int(slot)
    except (TypeError, ValueError):
        return None
    if slot not in SLOTS:
        return None
    p = BACKUPS_DIR / slot_filename(slot)
    return p.read_bytes() if p.exists() else None
