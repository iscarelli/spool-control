#!/usr/bin/env bash
# =============================================================================
# setup-inside.sh — Setup completo do Spool Control num LXC Debian 12
# Execute DENTRO do container como root: bash setup-inside.sh
#
# O repositório é PÚBLICO — clone anônimo, sem credenciais no servidor.
#
# Parametrizável por variáveis de ambiente (usado pelo proxmox-deploy.sh):
#   DOMAIN              domínio público (default: spool.lojinharacer.com.br)
#   APP_BASE_URL        URL base p/ QR/etiquetas (default: https://$DOMAIN)
#   SECURE_COOKIES      1 atrás de HTTPS/proxy; 0 p/ acesso direto http (default 1)
#   USE_BR_MIRROR       1 usa mirror Debian BR (UFPR); 0 mantém o padrão (default 1)
#   ADMIN_DEFAULT_PASS  senha inicial do admin (default: gerada aleatoriamente)
# =============================================================================
set -euo pipefail

APP_DIR=/opt/spool-control
REPO="https://github.com/iscarelli/spool-control.git"
REPO_DIR=/tmp/spool-repo
DOMAIN="${DOMAIN:-spool.lojinharacer.com.br}"
APP_BASE_URL="${APP_BASE_URL:-https://${DOMAIN}}"
SECURE_COOKIES="${SECURE_COOKIES:-1}"
USE_BR_MIRROR="${USE_BR_MIRROR:-1}"
ADMIN_DEFAULT_PASS="${ADMIN_DEFAULT_PASS:-}"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

[ "$(id -u)" -eq 0 ] || error "Execute como root."

# ── 1. Mirror UFPR (mais rápido no Brasil) ────────────────────────────────────
if [ "$USE_BR_MIRROR" = "1" ]; then
    info "Configurando mirror Debian (UFPR)..."
    cat > /etc/apt/sources.list << 'SOURCES'
deb http://debian.c3sl.ufpr.br/debian bookworm main contrib non-free non-free-firmware
deb http://debian.c3sl.ufpr.br/debian bookworm-updates main contrib non-free non-free-firmware
deb http://security.debian.org/debian-security bookworm-security main contrib non-free non-free-firmware
SOURCES
fi

# ── 2. Suprimir apt-listchanges e atualizar ───────────────────────────────────
printf '[apt]\nfrontend=none\n' > /etc/apt/listchanges.conf
apt-get update -qq

# ── 3. Locale ─────────────────────────────────────────────────────────────────
info "Configurando locale..."
LANG=C LC_ALL=C DEBIAN_FRONTEND=noninteractive apt-get install -y -q locales
sed -i 's/^# *en_US.UTF-8/en_US.UTF-8/' /etc/locale.gen
locale-gen en_US.UTF-8
update-locale LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8
export LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8

# ── 4. Dependências ───────────────────────────────────────────────────────────
info "Instalando dependencias..."
DEBIAN_FRONTEND=noninteractive apt-get install -y -q python3 python3-venv git curl sudo

# ── 5. Usuário e diretórios ───────────────────────────────────────────────────
info "Criando usuario 'spool'..."
useradd -r -s /bin/false spool 2>/dev/null || warn "Usuario 'spool' ja existe."
mkdir -p "${APP_DIR}/data" "${APP_DIR}/deploy"

# ── 6. Clonar repositório ─────────────────────────────────────────────────────
info "Clonando repositorio..."
rm -rf "$REPO_DIR"
git clone -q "$REPO" "$REPO_DIR"

info "Copiando arquivos para $APP_DIR..."
cp "$REPO_DIR/app.py"           "$APP_DIR/app.py"
cp "$REPO_DIR/database.py"      "$APP_DIR/database.py"
cp "$REPO_DIR/labels.py"        "$APP_DIR/labels.py"
cp "$REPO_DIR/translations.py"  "$APP_DIR/translations.py"
cp "$REPO_DIR/requirements.txt" "$APP_DIR/requirements.txt"
cp "$REPO_DIR/VERSION"          "$APP_DIR/VERSION"
cp "$REPO_DIR/CHANGELOG.md"     "$APP_DIR/CHANGELOG.md"
cp -r "$REPO_DIR/templates"     "$APP_DIR/templates"
cp -r "$REPO_DIR/static"        "$APP_DIR/static"
cp "$REPO_DIR/deploy/update-lxc.sh"          "$APP_DIR/deploy/update-lxc.sh"
cp "$REPO_DIR/deploy/spool-control.service"  "$APP_DIR/deploy/spool-control.service"
cp "$REPO_DIR/deploy/spool-update.service"   "$APP_DIR/deploy/spool-update.service"
cp "$REPO_DIR/deploy/sudoers-spool-update"   "$APP_DIR/deploy/sudoers-spool-update"
cp "$REPO_DIR/deploy/seed_brands.py"         "$APP_DIR/deploy/seed_brands.py"
chmod +x "$APP_DIR/deploy/update-lxc.sh"

rm -rf "$REPO_DIR"

# ── 7. Virtualenv e dependências Python ───────────────────────────────────────
info "Criando virtualenv e instalando dependencias Python..."
python3 -m venv "${APP_DIR}/.venv"
"${APP_DIR}/.venv/bin/pip" install --quiet --upgrade pip
"${APP_DIR}/.venv/bin/pip" install --quiet -r "${APP_DIR}/requirements.txt"

# ── 8. Gerar spool.env ────────────────────────────────────────────────────────
info "Gerando spool.env..."
ENV_FILE="${APP_DIR}/spool.env"
SECRET_KEY=$(openssl rand -hex 32)
ADMIN_PASS="${ADMIN_DEFAULT_PASS:-$(openssl rand -base64 12 | tr -d '/+=')}"
cat > "$ENV_FILE" << EOF
SECRET_KEY=${SECRET_KEY}
ADMIN_DEFAULT_PASS=${ADMIN_PASS}
APP_BASE_URL=${APP_BASE_URL}
SECURE_COOKIES=${SECURE_COOKIES}
EOF
chmod 600 "$ENV_FILE"

# ── 9. Permissões ─────────────────────────────────────────────────────────────
chown -R spool:spool "$APP_DIR"

# ── 10. Serviço systemd ───────────────────────────────────────────────────────
info "Configurando servico systemd..."
ln -sf "${APP_DIR}/deploy/spool-control.service" /etc/systemd/system/spool-control.service

# Autoatualizacao pela web: oneshot (root) + regra sudoers minima p/ o user 'spool'.
ln -sf "${APP_DIR}/deploy/spool-update.service" /etc/systemd/system/spool-update.service
install -m 0440 "${APP_DIR}/deploy/sudoers-spool-update" /etc/sudoers.d/spool-update
if ! visudo -cf /etc/sudoers.d/spool-update >/dev/null 2>&1; then
    rm -f /etc/sudoers.d/spool-update
    warn "sudoers de autoatualizacao invalido — removido (update via web indisponivel)."
fi

systemctl daemon-reload
systemctl enable spool-control
systemctl restart spool-control

# ── 11. Verificação ───────────────────────────────────────────────────────────
info "Verificando servico..."
sleep 3
systemctl is-active spool-control || error "Servico nao iniciou. Veja: journalctl -u spool-control -n 30"

HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 10 \
    "http://$(hostname -I | awk '{print $1}'):8001/health" || echo "000")

echo ""
echo -e "${GREEN}=====================================================${NC}"
echo -e "${GREEN}  Setup concluido!${NC}"
echo -e "${GREEN}=====================================================${NC}"
echo -e "  URL:       ${GREEN}${APP_BASE_URL}${NC}"
echo -e "  Login:     admin / ${GREEN}${ADMIN_PASS}${NC}"
echo -e "  Health:    http://$(hostname -I | awk '{print $1}'):8001/health → HTTP ${HTTP_CODE}"
echo -e "  Updates:   bash ${APP_DIR}/deploy/update-lxc.sh"
echo -e "${GREEN}=====================================================${NC}"
