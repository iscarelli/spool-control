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
    elif [ "${1:-}" = "--latest-release" ]; then
        # Usado pela autoatualização via web (spool-update.service). Resolve a
        # última tag publicada no GitHub; aborta se a API falhar (sem cair p/ main).
        info "Resolvendo ultima release no GitHub..."
        REF=$(curl -fsSL -H "User-Agent: spool-control" \
            https://api.github.com/repos/iscarelli/spool-control/releases/latest \
            | grep -oE '"tag_name"[[:space:]]*:[[:space:]]*"[^"]+"' | head -1 \
            | sed -E 's/.*"([^"]+)"$/\1/')
        [ -z "$REF" ] && error "Nao foi possivel resolver a ultima release via API do GitHub."
        info "Ultima release: $REF"
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

    # ── Smoke test ANTES de tocar em $APP_DIR ────────────────────────────────
    # Instala as deps e tenta importar o app a partir do CLONE. Se falhar, aborta
    # sem copiar nada: o servico atual continua intacto (evita crash loop / 404
    # por modulo faltando, erro de sintaxe, import quebrado etc.).
    info "Instalando dependencias e validando o novo codigo (smoke test)..."
    "${APP_DIR}/.venv/bin/pip" install --quiet -r "$REPO_DIR/requirements.txt"
    if ! ( cd "$REPO_DIR"; set -a
           if [ -f "${APP_DIR}/spool.env" ]; then . "${APP_DIR}/spool.env"; else SECRET_KEY=smoketest; fi
           set +a
           PYTHONPATH="$REPO_DIR" "${APP_DIR}/.venv/bin/python" -c "import app" ) 2>/tmp/spool-smoke.log; then
        error "Novo codigo NAO importa — deploy abortado, servico atual mantido no ar. Detalhe: $(tail -n 3 /tmp/spool-smoke.log)"
    fi
    info "Smoke test OK — aplicando."

    # Aplica TODO o conteudo versionado (git archive) — nao ha lista de arquivos
    # para esquecer: o que estiver no git e' aplicado. Nao apaga itens fora do git
    # (data/, spool.env, .venv, static/brands/), pois o tar so extrai/sobrescreve
    # os arquivos rastreados. (Deps ja instaladas no smoke test acima.)
    info "Aplicando arquivos versionados em $APP_DIR..."
    git -C "$REPO_DIR" archive HEAD | tar -x -C "$APP_DIR"
    chmod +x "$APP_DIR/deploy/update-lxc.sh"
    rm -rf "$REPO_DIR"

    # Garante que spool.env existe
    local ENV_FILE="${APP_DIR}/spool.env"
    if [ ! -f "$ENV_FILE" ]; then
        warn "spool.env nao encontrado — gerando automaticamente..."
        local SECRET_KEY ADMIN_PASS SPOOL_API_KEY
        SECRET_KEY=$(openssl rand -hex 32)
        ADMIN_PASS=$(openssl rand -base64 12 | tr -d '/+=')
        SPOOL_API_KEY=$(openssl rand -hex 24)
        cat > "$ENV_FILE" << EOF
SECRET_KEY=${SECRET_KEY}
ADMIN_DEFAULT_PASS=${ADMIN_PASS}
APP_BASE_URL=https://spool.lojinharacer.com.br
SECURE_COOKIES=1
SPOOL_API_KEY=${SPOOL_API_KEY}
EOF
        chmod 600 "$ENV_FILE"
        chown spool:spool "$ENV_FILE" 2>/dev/null || true
        warn "=== SENHA INICIAL DO ADMIN: ${ADMIN_PASS} ==="
    fi

    chown -R spool:spool "$APP_DIR"

    # ── Aparato de autoatualizacao pela web (oneshot + sudoers) ──────────────
    info "Configurando autoatualizacao (systemd oneshot + sudoers)..."
    command -v sudo >/dev/null 2>&1 || { apt-get update -qq && apt-get install -y -q sudo; }
    ln -sf "${APP_DIR}/deploy/spool-update.service" /etc/systemd/system/spool-update.service
    install -m 0440 "${APP_DIR}/deploy/sudoers-spool-update" /etc/sudoers.d/spool-update
    if ! visudo -cf /etc/sudoers.d/spool-update >/dev/null 2>&1; then
        rm -f /etc/sudoers.d/spool-update
        warn "sudoers de autoatualizacao invalido — removido (update via web indisponivel)."
    fi

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
