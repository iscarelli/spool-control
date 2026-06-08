#!/usr/bin/env python3
"""Entry point do backup diário rotativo (chamado pelo spool-backup.service).

Roda no venv SEM subir o Flask: só configura o logging JSON e dispara o backup
rotativo (backup.run_scheduled_backup). O status fica gravado em settings p/ a UI
alertar. Ver backup.py e deploy/spool-backup.{service,timer}.
"""
import sys
from pathlib import Path

# Permite rodar de qualquer cwd: garante o diretório do projeto no import path.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import logger as log_cfg

log_cfg.configure_logging()

import backup  # noqa: E402  (depois do configure_logging, de propósito)


if __name__ == "__main__":
    backup.run_scheduled_backup()
