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
error() { echo -e "${RED}[ERROR]${NC} $*"; FAIL_REASON="$*"; exit 1; }

# ── Status do update para a UI ───────────────────────────────────────────────
# Grava o resultado em data/.update-status (JSON) que o app (user spool, não-root)
# lê na /admin/update — assim uma falha aparece com o motivo em vez de o botão
# "voltar em silêncio". Sem isto o usuário não tinha como saber por que não atualizou.
STATUS_FILE="${APP_DIR}/data/.update-status"
DEPLOY_DONE=0
FAIL_REASON=""
write_status() {
    local state="$1"; shift; local msg="${*:-}"
    msg=${msg//\\/}; msg=${msg//\"/}; msg=${msg//$'\n'/ }   # JSON-safe (sem aspas/barras/quebras)
    { printf '{"state":"%s","message":"%s","ts":"%s"}\n' \
        "$state" "$msg" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$STATUS_FILE"; } 2>/dev/null || return 0
    chown spool:spool "$STATUS_FILE" 2>/dev/null || true
    chmod 644 "$STATUS_FILE" 2>/dev/null || true
}
on_err()  { FAIL_REASON="${FAIL_REASON:-falhou em \'${BASH_COMMAND}\' (linha ${1:-?})}"; }
on_exit() {
    local rc=$?
    trap - ERR EXIT
    { [ "$DEPLOY_DONE" = "1" ] || [ "$rc" -eq 0 ]; } && return 0
    local extra=""
    [ -s /tmp/spool-smoke.log ] && extra=" — $(tail -n 2 /tmp/spool-smoke.log | tr '\n' ' ')"
    write_status failed "${FAIL_REASON:-deploy abortado (rc=$rc)}${extra}"
}

main() {
    # ── Dispatcher ───────────────────────────────────────────────────────────
    if [ "${1:-}" = "--setup" ]; then
        info "Instalando git..."
        apt-get install -y -q git
        info "Setup concluido. Proximos deploys: bash $0"
        return 0
    fi

    # ── Deploy normal / rollback ──────────────────────────────────────────────
    # A partir daqui qualquer aborto (smoke test, clone, API) é registrado em
    # .update-status pelo on_exit, para a /admin/update mostrar o motivo.
    trap 'on_err $LINENO' ERR
    trap on_exit EXIT
    write_status running "Atualizacao em andamento"

    local REF=""
    if [ "${1:-}" = "--ref" ]; then
        [ -z "${2:-}" ] && error "Uso: $0 --ref <tag|branch|commit>"
        REF="$2"
    elif [ "${1:-}" = "--latest-release" ]; then
        # Usado pela autoatualização via web (spool-update.service). Resolve a
        # última tag publicada via `git ls-remote` (protocolo git, SEM a REST API
        # do GitHub) — imune ao limite anônimo de 60/h. Aborta se falhar (sem cair
        # p/ main). --sort=-v:refname ordena por versão (maior primeiro).
        info "Resolvendo ultima release no GitHub..."
        REF=$(git ls-remote --tags --refs --sort=-v:refname \
            https://github.com/iscarelli/spool-control.git 'v*' 2>/dev/null \
            | head -1 | sed -E 's@.*refs/tags/@@')
        [ -z "$REF" ] && error "Nao foi possivel resolver a ultima release via git ls-remote."
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
    # pip e import gravam no smoke log; se o pip falhar (ex.: dep nova como pyotp
    # sem acesso ao PyPI), abortamos com motivo claro em vez de morrer via set -e.
    if ! "${APP_DIR}/.venv/bin/pip" install --quiet -r "$REPO_DIR/requirements.txt" \
            >/tmp/spool-smoke.log 2>&1; then
        error "Falha ao instalar as dependencias do novo codigo (PyPI inacessivel? disco cheio?) — deploy abortado, servico atual mantido no ar. Detalhe: $(tail -n 3 /tmp/spool-smoke.log)"
    fi
    if ! ( cd "$REPO_DIR"; set -a
           if [ -f "${APP_DIR}/spool.env" ]; then . "${APP_DIR}/spool.env"; else SECRET_KEY=smoketest; fi
           set +a
           PYTHONPATH="$REPO_DIR" "${APP_DIR}/.venv/bin/python" -c "import app" ) >>/tmp/spool-smoke.log 2>&1; then
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

    # ── Logos de marcas conhecidas ────────────────────────────────────────────
    info "Atualizando logos de marcas conhecidas..."
    "${APP_DIR}/.venv/bin/python" "${APP_DIR}/deploy/seed_brands.py" \
        || warn "Falha ao buscar alguns logos — sem impacto no funcionamento."
    chown -R spool:spool "${APP_DIR}/static/brands" 2>/dev/null || true

    # ── Aparato de autoatualizacao pela web (flag-file + vigia root) ─────────
    # Mecanismo SEM privilegio para o app: a UI escreve data/.update-requested e um
    # systemd .path unit (root) dispara o oneshot. Remove o grant sudoers legado — o
    # app nao chama mais sudo (encolhe a aresta admin->root). Tambem instala o comando
    # `update` (padrao Proxmox Helper Scripts) para uso no console.
    info "Configurando autoatualizacao (flag-file + systemd .path)..."
    rm -f /etc/sudoers.d/spool-update   # remove grant root legado (se existir)
    ln -sf "${APP_DIR}/deploy/spool-update.service" /etc/systemd/system/spool-update.service
    ln -sf "${APP_DIR}/deploy/spool-update.path"    /etc/systemd/system/spool-update.path
    chmod +x "${APP_DIR}/deploy/update-cli.sh"
    ln -sf "${APP_DIR}/deploy/update-cli.sh" /usr/local/bin/update

    # Backup diario rotativo (entra/atualiza junto; instalacoes antigas ganham aqui).
    ln -sf "${APP_DIR}/deploy/spool-backup.service" /etc/systemd/system/spool-backup.service
    ln -sf "${APP_DIR}/deploy/spool-backup.timer"   /etc/systemd/system/spool-backup.timer

    info "Reiniciando servico..."
    ln -sf "${APP_DIR}/deploy/spool-control.service" /etc/systemd/system/spool-control.service
    systemctl daemon-reload
    # Habilita o observador do flag de update (inotify; dispara o oneshot na hora).
    systemctl enable --now spool-update.path 2>/dev/null \
        || warn "Nao foi possivel habilitar spool-update.path (update via web pode usar fallback)."
    systemctl enable --now spool-backup.timer 2>/dev/null \
        || warn "Nao foi possivel habilitar spool-backup.timer (backup automatico indisponivel)."
    systemctl restart spool-control
    sleep 2
    systemctl is-active spool-control || error "Servico nao iniciou. Veja: journalctl -u spool-control -n 30"
    systemctl status spool-control --no-pager | head -15

    DEPLOY_DONE=1
    write_status done "$(tr -d '[:space:]' < "${APP_DIR}/VERSION" 2>/dev/null)"
    echo -e "\n${GREEN}Deploy concluido.${NC}"
}

main "$@"
