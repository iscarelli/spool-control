#!/usr/bin/env bash
# =============================================================================
# reset-demo.sh — Reinicia os dados da instância demo do Spool Control
# Disparo: spool-demo-reset.timer (daily 00:00 UTC)
# Execute como root dentro do servidor.
# =============================================================================
set -euo pipefail

APP_DIR=/opt/spool-control
DB_PATH="${APP_DIR}/data/spool.db"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info() { echo -e "${GREEN}[$(date '+%H:%M:%S')]${NC} $*"; }
warn() { echo -e "${YELLOW}[$(date '+%H:%M:%S')]${NC} $*"; }

[ "$(id -u)" -eq 0 ] || { echo "Execute como root."; exit 1; }

info "Parando serviço..."
systemctl stop spool-control

info "Removendo banco de dados..."
rm -f "$DB_PATH" "${DB_PATH}-wal" "${DB_PATH}-shm"

info "Recriando banco e aplicando seed..."
# init_db via importação do app (cria tabelas + admin padrão)
( cd "$APP_DIR"
  set -a; [ -f spool.env ] && . spool.env; set +a
  "${APP_DIR}/.venv/bin/python" -c "import database; database.init_db()" )

# Popula com dados demo
"${APP_DIR}/.venv/bin/python" "${APP_DIR}/deploy/seed-demo-data.py"

chown -R spool:spool "${APP_DIR}/data"

info "Reiniciando serviço..."
systemctl start spool-control
sleep 2
systemctl is-active spool-control || { warn "Serviço não iniciou!"; exit 1; }

info "Reset concluído."
