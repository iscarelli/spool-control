#!/usr/bin/env bash
# =============================================================================
# Spool Control — instalador LXC para Proxmox VE (estilo Proxmox Helper Scripts)
# License: MIT | https://github.com/iscarelli/spool-control
#
# Execute NO HOST Proxmox (não dentro de um container):
#   bash -c "$(curl -fsSL https://raw.githubusercontent.com/iscarelli/spool-control/main/deploy/proxmox-deploy.sh)"
#
# Cria um LXC Debian 12, pergunta a configuração (CTID, host, rede, recursos)
# e instala o Spool Control + serviço systemd. Repositório público — sem token.
# =============================================================================
set -euo pipefail

APP="Spool Control"
REPO_RAW="https://raw.githubusercontent.com/iscarelli/spool-control/main"
SETUP_URL="${REPO_RAW}/deploy/setup-inside.sh"

# ── Cores / mensagens ────────────────────────────────────────────────────────
YW="\033[33m"; GN="\033[1;92m"; RD="\033[01;31m"; BL="\033[36m"; CL="\033[m"
BFR="\\r\\033[K"; CM="${GN}✓${CL}"; CROSS="${RD}✗${CL}"
msg_info()  { echo -ne " ${YW}●${CL} $1..."; }
msg_ok()    { echo -e "${BFR} ${CM} $1"; }
msg_error() { echo -e "${BFR} ${CROSS} $1"; }
die()       { msg_error "$1"; exit 1; }

header_info() {
  clear
  cat <<"EOF"
   ____                  __   ____            __           __
  / __/__  ___  ___  ___/ /  / __/__  ___ ___/ /________  / /
 _\ \/ _ \/ _ \/ _ \/ _  /  / _// _ \/ _ `/ -_) __/ _ \/ /
/___/ .__/\___/\___/\_,_/  /___/\___/\_,_/\__/\__/\___/_/
   /_/                  Proxmox LXC installer
EOF
}

# ── Verificações de ambiente ─────────────────────────────────────────────────
header_info
[ "$(id -u)" -eq 0 ] || die "Execute como root no host Proxmox."
command -v pct >/dev/null 2>&1 || die "Comando 'pct' não encontrado — rode no host Proxmox VE."
command -v pveversion >/dev/null 2>&1 || die "Proxmox VE não detectado."
command -v whiptail >/dev/null 2>&1 || die "'whiptail' não encontrado (apt install whiptail)."

PVE=$(pveversion | grep -oE 'pve-manager/[0-9]+' | grep -oE '[0-9]+' || echo 0)
[ "$PVE" -ge 7 ] || die "Requer Proxmox VE 7 ou superior (detectado: $PVE)."

# ── Defaults ─────────────────────────────────────────────────────────────────
NEXTID=$(pvesh get /cluster/nextid 2>/dev/null || echo 100)
CTID="$NEXTID"
HN="spool"
DISK_SIZE="4"
CORE_COUNT="1"
RAM_SIZE="512"
BRG="vmbr0"
NET="dhcp"
GATE=""
STORAGE=""
DOMAIN=""
USE_BR_MIRROR="1"
UNPRIV="1"

whiptail --backtitle "$APP" --title "$APP — Instalador LXC" \
  --msgbox "Este assistente cria um container LXC Debian 12 e instala o $APP.\n\nUse TAB para navegar e ESPAÇO para selecionar." 12 64

if whiptail --backtitle "$APP" --title "CONFIGURAÇÃO" --yesno \
  "Usar configuração PADRÃO?\n\n  CTID:      $NEXTID\n  Hostname:  $HN\n  Disco:     ${DISK_SIZE} GB\n  vCPU:      $CORE_COUNT\n  RAM:       ${RAM_SIZE} MB\n  Rede:      DHCP (vmbr0)\n  Tipo:      Debian 12, não-privilegiado\n\nEscolha 'Não' para configuração avançada." 20 64; then
  ADVANCED="no"
else
  ADVANCED="yes"
fi

# ── Seleção de storage (rootfs) ──────────────────────────────────────────────
pick_storage() {
  local menu=() count=0 tag type
  while read -r tag type _; do
    [ -z "$tag" ] && continue
    menu+=("$tag" "$type" "OFF"); count=$((count+1))
  done < <(pvesm status -content rootdir 2>/dev/null | awk 'NR>1{print $1, $2}')
  [ "$count" -eq 0 ] && die "Nenhum storage com conteúdo 'rootdir' disponível."
  if [ "$count" -eq 1 ]; then
    STORAGE="${menu[0]}"; return
  fi
  STORAGE=$(whiptail --backtitle "$APP" --title "STORAGE (rootfs)" \
    --radiolist "Onde criar o disco do container?" 16 60 6 "${menu[@]}" 3>&1 1>&2 2>&3) \
    || die "Cancelado."
  [ -z "$STORAGE" ] && die "Nenhum storage selecionado."
}

# ── Storage de templates (vztmpl) ────────────────────────────────────────────
pick_template_storage() {
  TMPL_STORAGE=$(pvesm status -content vztmpl 2>/dev/null | awk 'NR==2{print $1}')
  [ -z "${TMPL_STORAGE:-}" ] && TMPL_STORAGE="local"
}

if [ "$ADVANCED" = "yes" ]; then
  CTID=$(whiptail --backtitle "$APP" --inputbox "Container ID (CTID)" 8 60 "$NEXTID" 3>&1 1>&2 2>&3) || die "Cancelado."
  HN=$(whiptail --backtitle "$APP" --inputbox "Hostname" 8 60 "$HN" 3>&1 1>&2 2>&3) || die "Cancelado."
  DISK_SIZE=$(whiptail --backtitle "$APP" --inputbox "Tamanho do disco (GB)" 8 60 "$DISK_SIZE" 3>&1 1>&2 2>&3) || die "Cancelado."
  CORE_COUNT=$(whiptail --backtitle "$APP" --inputbox "Núcleos de CPU" 8 60 "$CORE_COUNT" 3>&1 1>&2 2>&3) || die "Cancelado."
  RAM_SIZE=$(whiptail --backtitle "$APP" --inputbox "Memória RAM (MB)" 8 60 "$RAM_SIZE" 3>&1 1>&2 2>&3) || die "Cancelado."
  BRG=$(whiptail --backtitle "$APP" --inputbox "Bridge de rede" 8 60 "$BRG" 3>&1 1>&2 2>&3) || die "Cancelado."

  if whiptail --backtitle "$APP" --title "REDE" --yesno "Usar DHCP?\n\n'Não' = IP estático" 10 60; then
    NET="dhcp"
  else
    NET=$(whiptail --backtitle "$APP" --inputbox "IP estático em CIDR (ex.: 10.1.0.30/24)" 8 64 "" 3>&1 1>&2 2>&3) || die "Cancelado."
    GATE=$(whiptail --backtitle "$APP" --inputbox "Gateway (ex.: 10.1.0.1)" 8 64 "" 3>&1 1>&2 2>&3) || die "Cancelado."
    [ -z "$NET" ] && die "IP estático vazio."
  fi

  pick_storage

  if ! whiptail --backtitle "$APP" --title "DEBIAN MIRROR" \
      --yesno "Usar mirror Debian BR (UFPR)?\n\n'Sim' acelera no Brasil; 'Não' mantém o mirror padrão do template." 11 64; then
    USE_BR_MIRROR="0"
  fi
else
  pick_storage
fi

# ── Domínio / proxy ──────────────────────────────────────────────────────────
DOMAIN=$(whiptail --backtitle "$APP" --title "URL PÚBLICA (opcional)" \
  --inputbox "Domínio público atrás de proxy HTTPS (ex.: spool.exemplo.com).\n\nDeixe VAZIO para acesso direto via http://IP:8001\n(define SECURE_COOKIES adequadamente)." 12 66 "" 3>&1 1>&2 2>&3) || DOMAIN=""

pick_template_storage

# ── Resumo / confirmação ─────────────────────────────────────────────────────
IPDESC=$([ "$NET" = "dhcp" ] && echo "DHCP" || echo "$NET gw=$GATE")
URLDESC=$([ -n "$DOMAIN" ] && echo "https://$DOMAIN (proxy)" || echo "http://IP:8001 (direto)")
whiptail --backtitle "$APP" --title "CONFIRMAR" --yesno \
  "Criar o container com:\n\n  CTID:     $CTID\n  Host:     $HN\n  Disco:    ${DISK_SIZE}GB em '$STORAGE'\n  vCPU/RAM: $CORE_COUNT / ${RAM_SIZE}MB\n  Rede:     $BRG / $IPDESC\n  Acesso:   $URLDESC\n  Template: $TMPL_STORAGE\n\nProsseguir?" 20 70 || die "Cancelado pelo usuário."

# ── Template Debian 12 ───────────────────────────────────────────────────────
msg_info "Localizando template Debian 12"
pveam update >/dev/null 2>&1 || true
TEMPLATE=$(pveam available --section system 2>/dev/null | sed -n 's/.*\(debian-12-standard_.*_amd64.tar.zst\).*/\1/p' | tail -1)
[ -z "$TEMPLATE" ] && die "Template debian-12-standard não encontrado em 'pveam available'."
msg_ok "Template: $TEMPLATE"

if ! pveam list "$TMPL_STORAGE" 2>/dev/null | grep -q "$TEMPLATE"; then
  msg_info "Baixando template (pode demorar)"
  pveam download "$TMPL_STORAGE" "$TEMPLATE" >/dev/null 2>&1 || die "Falha ao baixar o template."
  msg_ok "Template baixado"
fi

# ── Limpeza em caso de erro após a criação ───────────────────────────────────
CREATED=0
cleanup_on_err() {
  [ "$CREATED" = "1" ] || exit 1
  echo
  if whiptail --backtitle "$APP" --title "ERRO" --yesno "A instalação falhou. Destruir o container $CTID criado?" 9 60; then
    pct stop "$CTID" >/dev/null 2>&1 || true
    pct destroy "$CTID" >/dev/null 2>&1 || true
    msg_ok "Container $CTID removido."
  fi
  exit 1
}
trap cleanup_on_err ERR

# ── Criação do container ─────────────────────────────────────────────────────
NET0="name=eth0,bridge=${BRG},ip=${NET}"
[ "$NET" != "dhcp" ] && [ -n "$GATE" ] && NET0="${NET0},gw=${GATE}"

msg_info "Criando container LXC $CTID"
pct create "$CTID" "${TMPL_STORAGE}:vztmpl/${TEMPLATE}" \
  --hostname "$HN" \
  --cores "$CORE_COUNT" \
  --memory "$RAM_SIZE" \
  --swap 512 \
  --rootfs "${STORAGE}:${DISK_SIZE}" \
  --net0 "$NET0" \
  --unprivileged "$UNPRIV" \
  --features nesting=1 \
  --onboot 1 \
  --ostype debian \
  --tags "spool-control" >/dev/null
CREATED=1
msg_ok "Container criado"

msg_info "Iniciando container"
pct start "$CTID" >/dev/null
msg_ok "Container iniciado"

# ── Aguardar rede ────────────────────────────────────────────────────────────
msg_info "Aguardando rede no container"
for i in $(seq 1 30); do
  if pct exec "$CTID" -- getent hosts github.com >/dev/null 2>&1; then break; fi
  sleep 2
  [ "$i" = "30" ] && die "Container sem resolução DNS/rede após 60s."
done
msg_ok "Rede pronta"

IP=$(pct exec "$CTID" -- bash -c "hostname -I | awk '{print \$1}'" 2>/dev/null | tr -d '\r')

# ── URL base / cookies seguros ───────────────────────────────────────────────
if [ -n "$DOMAIN" ]; then
  APP_BASE_URL="https://${DOMAIN}"; SECURE_COOKIES="1"
else
  APP_BASE_URL="http://${IP}:8001"; SECURE_COOKIES="0"
fi

# ── Instalação do app dentro do container ────────────────────────────────────
msg_info "Preparando dependências (curl)"
pct exec "$CTID" -- bash -c "apt-get update -qq && apt-get install -y -qq curl ca-certificates >/dev/null 2>&1" || die "Falha ao instalar curl."
msg_ok "Dependências base prontas"

msg_info "Instalando $APP (clone público + venv + systemd)"
pct exec "$CTID" -- bash -c "
  DOMAIN='${DOMAIN:-}' APP_BASE_URL='${APP_BASE_URL}' SECURE_COOKIES='${SECURE_COOKIES}' \
  USE_BR_MIRROR='${USE_BR_MIRROR}' \
  bash <(curl -fsSL '${SETUP_URL}')
" || die "Falha no setup-inside.sh (veja: pct exec $CTID -- journalctl -u spool-control -n 40)."
msg_ok "$APP instalado"

# ── Senha do admin + resultado ───────────────────────────────────────────────
ADMIN_PASS=$(pct exec "$CTID" -- bash -c "grep '^ADMIN_DEFAULT_PASS=' /opt/spool-control/spool.env | cut -d= -f2-" 2>/dev/null | tr -d '\r')
HEALTH=$(pct exec "$CTID" -- bash -c "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8001/health" 2>/dev/null || echo "000")

trap - ERR
echo
echo -e "${GN}=====================================================${CL}"
echo -e "${GN}  $APP instalado com sucesso!${CL}"
echo -e "${GN}=====================================================${CL}"
echo -e "  CTID:      ${BL}${CTID}${CL}  (${HN})"
echo -e "  IP:        ${BL}${IP}${CL}"
echo -e "  Acesso:    ${GN}${APP_BASE_URL}${CL}"
echo -e "  Direto:    http://${IP}:8001   (health → HTTP ${HEALTH})"
echo -e "  Login:     admin / ${GN}${ADMIN_PASS}${CL}"
echo -e "  Update:    pct exec ${CTID} -- bash /opt/spool-control/deploy/update-lxc.sh"
echo -e "${GN}=====================================================${CL}"
[ -z "$DOMAIN" ] && echo -e "  ${YW}Acesso direto via HTTP — para HTTPS, ponha atrás de um proxy e re-rode com domínio.${CL}"
echo
