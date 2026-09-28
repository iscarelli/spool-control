#!/usr/bin/env python3
"""Entry point do backup diário rotativo (chamado pelo spool-backup.service).

Roda no venv SEM subir o Flask: só configura o logging JSON e dispara o backup
rotativo (backup.run_scheduled_backup) e, piggyback no mesmo tick horário, o
refresh diário do catálogo de filamentos (spoolmandb_refresh.run_scheduled_refresh —
ver docs/spoolmandb.md). O status de cada um fica gravado em settings p/ a UI
alertar. Ver backup.py e deploy/spool-backup.{service,timer}.

Os dois são independentes: cada chamada já engole a própria exceção e grava o
erro em settings (nunca deixam nada escapar), mas envolvemos em try/except aqui
TAMBÉM — de propósito, redundante — para que um bug futuro num dos dois não
impeça o outro de rodar neste tick.
"""
import sys
from pathlib import Path

# Permite rodar de qualquer cwd: garante o diretório do projeto no import path.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import logger as log_cfg

log_cfg.configure_logging()
log = log_cfg.get_logger("spool.backup_cron")

import backup  # noqa: E402  (depois do configure_logging, de propósito)
import spoolmandb_refresh  # noqa: E402


if __name__ == "__main__":
    try:
        backup.run_scheduled_backup()
    except Exception:
        log.error("backup_cron.backup_step_failed", exc_info=True)

    try:
        spoolmandb_refresh.run_scheduled_refresh()
    except Exception:
        log.error("backup_cron.catalog_step_failed", exc_info=True)
