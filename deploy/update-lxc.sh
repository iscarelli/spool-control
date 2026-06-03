#!/usr/bin/env bash
# =============================================================================
# update-lxc.sh — Atualiza o Spool Control via git clone
# Execute DENTRO do LXC como root: bash /opt/spool-control/deploy/update-lxc.sh
#
# Primeira execução: bash update-lxc.sh --setup
# Deploy normal:     bash update-lxc.sh
# Deploy de versão:  bash update-lxc.sh --ref v1.2.1   (rollback para tag/branch)
#
# O repositório é PÚBLICO — o clone é anônimo (sem token). Nenhuma credencial
# do GitHub fica armazenada no servidor.
# =============================================================================
# ESTRUTURA: tudo dentro de main() para que bash compile a função inteira
# antes de executá-la — evita que o 'cp' deste próprio script corrompa a execução.
set -euo pipefail

APP_DIR=/opt/spool-control
REPO="https://github.com/iscarelli/spool-control.git"
REPO_DIR=/tmp/spool-repo

GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

main() {
    # ── Dispatcher ───────────────────────────────────────────────────────────
    if [ "${1:-}" = "--setup" ]; then
        info "Instalando git..."
        apt-get install -y -q git
        info "Setup concluido. Proximos deploys: bash $0"
        return 0
    fi

    # ── Deploy normal / rollback ──────────────────────────────────────────────
    local REF=""
    if [ "${1:-}" = "--ref" ]; then
        [ -z "${2:-}" ] && error "Uso: $0 --ref <tag|branch|commit>"
        REF="$2"
    fi

    [ "$(id -u)" -eq 0 ] || error "Execute como root."

    # Remove token legado, se existir (não é mais necessário — repo público).
    rm -f "${APP_DIR}/.gh_token"

    info "Clonando repositorio${REF:+ (ref: $REF)}..."
    rm -rf "$REPO_DIR"
    git clone -q "$REPO" "$REPO_DIR"
    if [ -n "$REF" ]; then
        git -C "$REPO_DIR" checkout -q "$REF"
        warn "Deploying ref '$REF' — nao e a HEAD do main."
    fi

    info "Atualizando arquivos em $APP_DIR..."
    cp "$REPO_DIR/app.py"           "$APP_DIR/app.py"
    cp "$REPO_DIR/database.py"      "$APP_DIR/database.py"
    cp "$REPO_DIR/labels.py"        "$APP_DIR/labels.py"
    cp "$REPO_DIR/translations.py"  "$APP_DIR/translations.py"
    cp "$REPO_DIR/requirements.txt" "$APP_DIR/requirements.txt"
    cp "$REPO_DIR/VERSION"          "$APP_DIR/VERSION"
    cp "$REPO_DIR/CHANGELOG.md"     "$APP_DIR/CHANGELOG.md"
    cp -r "$REPO_DIR/templates/." "$APP_DIR/templates/"
    cp -r "$REPO_DIR/static/."    "$APP_DIR/static/"
    cp "$REPO_DIR/deploy/update-lxc.sh"         "$APP_DIR/deploy/update-lxc.sh"
    cp "$REPO_DIR/deploy/spool-control.service"  "$APP_DIR/deploy/spool-control.service"
    cp "$REPO_DIR/deploy/seed_brands.py"         "$APP_DIR/deploy/seed_brands.py"
    chmod +x "$APP_DIR/deploy/update-lxc.sh"
    rm -rf "$REPO_DIR"

    info "Atualizando dependencias Python..."
    "${APP_DIR}/.venv/bin/pip" install --quiet -r "${APP_DIR}/requirements.txt"

    # Garante que spool.env existe
    local ENV_FILE="${APP_DIR}/spool.env"
    if [ ! -f "$ENV_FILE" ]; then
        warn "spool.env nao encontrado — gerando automaticamente..."
        local SECRET_KEY ADMIN_PASS
        SECRET_KEY=$(openssl rand -hex 32)
        ADMIN_PASS=$(openssl rand -base64 12 | tr -d '/+=')
        cat > "$ENV_FILE" << EOF
SECRET_KEY=${SECRET_KEY}
ADMIN_DEFAULT_PASS=${ADMIN_PASS}
APP_BASE_URL=https://spool.lojinharacer.com.br
SECURE_COOKIES=1
EOF
        chmod 600 "$ENV_FILE"
        chown spool:spool "$ENV_FILE" 2>/dev/null || true
        warn "=== SENHA INICIAL DO ADMIN: ${ADMIN_PASS} ==="
    fi

    chown -R spool:spool "$APP_DIR"

    info "Reiniciando servico..."
    ln -sf "${APP_DIR}/deploy/spool-control.service" /etc/systemd/system/spool-control.service
    systemctl daemon-reload
    systemctl restart spool-control
    sleep 2
    systemctl is-active spool-control || error "Servico nao iniciou. Veja: journalctl -u spool-control -n 30"
    systemctl status spool-control --no-pager | head -15

    echo -e "\n${GREEN}Deploy concluido.${NC}"
}

main "$@"
