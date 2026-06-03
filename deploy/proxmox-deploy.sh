#!/usr/bin/env bash
# =============================================================================
# Spool Control — LXC installer for Proxmox VE (Proxmox Helper Scripts style)
# License: MIT | https://github.com/iscarelli/spool-control
#
# Run ON THE Proxmox HOST (not inside a container):
#   bash -c "$(curl -fsSL https://raw.githubusercontent.com/iscarelli/spool-control/main/deploy/proxmox-deploy.sh)"
#
# Creates a Debian 12 LXC, asks for the configuration (CTID, host, network,
# resources) and installs Spool Control + a systemd service.
# Public repository — no token required.
# =============================================================================
set -Eeuo pipefail

# Make sure the interactive dialogs can read the terminal even when the script
# was piped to bash (e.g. `curl ... | bash`), where stdin is the pipe and
# whiptail would otherwise fail immediately and abort under `set -e`.
if [ ! -t 0 ] && [ -e /dev/tty ]; then
  exec </dev/tty
fi

APP="Spool Control"
REPO_RAW="https://raw.githubusercontent.com/iscarelli/spool-control/main"
SETUP_URL="${REPO_RAW}/deploy/setup-inside.sh"

# ── Colors / messages ────────────────────────────────────────────────────────
YW="\033[33m"; GN="\033[1;92m"; RD="\033[01;31m"; BL="\033[36m"; CL="\033[m"
BFR="\\r\\033[K"; CM="${GN}✓${CL}"; CROSS="${RD}✗${CL}"
msg_info()  { echo -ne " ${YW}●${CL} $1..."; }
msg_ok()    { echo -e "${BFR} ${CM} $1"; }
msg_error() { echo -e "${BFR} ${CROSS} $1"; }
die()       { msg_error "$1"; exit 1; }

# ── Global error handler ─────────────────────────────────────────────────────
# Without this, any command failing under `set -e` exits silently and the user
# just lands back at the prompt with no idea what happened. This prints the
# failing line and command, and offers to destroy a half-created container.
CREATED=0
on_err() {
  local rc=$? line="${1:-?}"
  trap - ERR                      # avoid re-entrancy if cleanup also fails
  echo
  msg_error "Failed at line ${line} (exit ${rc}): ${BASH_COMMAND}"
  if [ "$CREATED" = "1" ] && command -v whiptail >/dev/null 2>&1; then
    if whiptail --backtitle "$APP" --title "ERROR" \
        --yesno "Installation failed. Destroy the created container ${CTID:-?}?" 9 60; then
      pct stop "$CTID"    >/dev/null 2>&1 || true
      pct destroy "$CTID" >/dev/null 2>&1 || true
      msg_ok "Container ${CTID} removed."
    fi
  fi
  exit "$rc"
}
trap 'on_err $LINENO' ERR

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

# ── Environment checks ───────────────────────────────────────────────────────
header_info
[ "$(id -u)" -eq 0 ] || die "Run as root on the Proxmox host."
command -v pct >/dev/null 2>&1 || die "'pct' command not found — run on the Proxmox VE host."
command -v pveversion >/dev/null 2>&1 || die "Proxmox VE not detected."
command -v whiptail >/dev/null 2>&1 || die "'whiptail' not found (apt install whiptail)."

PVE=$(pveversion | grep -oE 'pve-manager/[0-9]+' | grep -oE '[0-9]+' || echo 0)
[ "$PVE" -ge 7 ] || die "Requires Proxmox VE 7 or newer (detected: $PVE)."

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

whiptail --backtitle "$APP" --title "$APP — LXC Installer" \
  --msgbox "This wizard creates a Debian 12 LXC container and installs $APP.\n\nUse TAB to navigate and SPACE to select." 12 64

if whiptail --backtitle "$APP" --title "CONFIGURATION" --yesno \
  "Use DEFAULT configuration?\n\n  CTID:      $NEXTID\n  Hostname:  $HN\n  Disk:      ${DISK_SIZE} GB\n  vCPU:      $CORE_COUNT\n  RAM:       ${RAM_SIZE} MB\n  Network:   DHCP (vmbr0)\n  Type:      Debian 12, unprivileged\n\nChoose 'No' for advanced configuration." 20 64; then
  ADVANCED="no"
else
  ADVANCED="yes"
fi

# ── Storage selection (rootfs) ───────────────────────────────────────────────
pick_storage() {
  local menu=() count=0 tag type
  while read -r tag type _; do
    [ -z "$tag" ] && continue
    menu+=("$tag" "$type" "OFF"); count=$((count+1))
  done < <(pvesm status -content rootdir 2>/dev/null | awk 'NR>1{print $1, $2}')
  [ "$count" -eq 0 ] && die "No storage with 'rootdir' content available."
  if [ "$count" -eq 1 ]; then
    STORAGE="${menu[0]}"; return
  fi
  STORAGE=$(whiptail --backtitle "$APP" --title "STORAGE (rootfs)" \
    --radiolist "Where should the container disk be created?" 16 60 6 "${menu[@]}" 3>&1 1>&2 2>&3) \
    || die "Cancelled."
  [ -z "$STORAGE" ] && die "No storage selected."
}

# ── Template storage (vztmpl) ────────────────────────────────────────────────
pick_template_storage() {
  TMPL_STORAGE=$(pvesm status -content vztmpl 2>/dev/null | awk 'NR==2{print $1}')
  [ -z "${TMPL_STORAGE:-}" ] && TMPL_STORAGE="local"
}

if [ "$ADVANCED" = "yes" ]; then
  CTID=$(whiptail --backtitle "$APP" --inputbox "Container ID (CTID)" 8 60 "$NEXTID" 3>&1 1>&2 2>&3) || die "Cancelled."
  HN=$(whiptail --backtitle "$APP" --inputbox "Hostname" 8 60 "$HN" 3>&1 1>&2 2>&3) || die "Cancelled."
  DISK_SIZE=$(whiptail --backtitle "$APP" --inputbox "Disk size (GB)" 8 60 "$DISK_SIZE" 3>&1 1>&2 2>&3) || die "Cancelled."
  CORE_COUNT=$(whiptail --backtitle "$APP" --inputbox "CPU cores" 8 60 "$CORE_COUNT" 3>&1 1>&2 2>&3) || die "Cancelled."
  RAM_SIZE=$(whiptail --backtitle "$APP" --inputbox "RAM (MB)" 8 60 "$RAM_SIZE" 3>&1 1>&2 2>&3) || die "Cancelled."
  BRG=$(whiptail --backtitle "$APP" --inputbox "Network bridge" 8 60 "$BRG" 3>&1 1>&2 2>&3) || die "Cancelled."

  if whiptail --backtitle "$APP" --title "NETWORK" --yesno "Use DHCP?\n\n'No' = static IP" 10 60; then
    NET="dhcp"
  else
    NET=$(whiptail --backtitle "$APP" --inputbox "Static IP in CIDR (e.g. 10.1.0.30/24)" 8 64 "" 3>&1 1>&2 2>&3) || die "Cancelled."
    GATE=$(whiptail --backtitle "$APP" --inputbox "Gateway (e.g. 10.1.0.1)" 8 64 "" 3>&1 1>&2 2>&3) || die "Cancelled."
    [ -z "$NET" ] && die "Empty static IP."
  fi

  pick_storage

  if ! whiptail --backtitle "$APP" --title "DEBIAN MIRROR" \
      --yesno "Use the Debian BR mirror (UFPR)?\n\n'Yes' is faster in Brazil; 'No' keeps the template's default mirror." 11 64; then
    USE_BR_MIRROR="0"
  fi
else
  pick_storage
fi

# ── Domain / proxy ───────────────────────────────────────────────────────────
DOMAIN=$(whiptail --backtitle "$APP" --title "PUBLIC URL (optional)" \
  --inputbox "Public domain behind an HTTPS proxy (e.g. spool.example.com).\n\nLeave EMPTY for direct access via http://IP:8001\n(sets SECURE_COOKIES accordingly)." 12 66 "" 3>&1 1>&2 2>&3) || DOMAIN=""

pick_template_storage

# ── Summary / confirmation ───────────────────────────────────────────────────
IPDESC=$([ "$NET" = "dhcp" ] && echo "DHCP" || echo "$NET gw=$GATE")
URLDESC=$([ -n "$DOMAIN" ] && echo "https://$DOMAIN (proxy)" || echo "http://IP:8001 (direct)")
whiptail --backtitle "$APP" --title "CONFIRM" --yesno \
  "Create the container with:\n\n  CTID:     $CTID\n  Host:     $HN\n  Disk:     ${DISK_SIZE}GB on '$STORAGE'\n  vCPU/RAM: $CORE_COUNT / ${RAM_SIZE}MB\n  Network:  $BRG / $IPDESC\n  Access:   $URLDESC\n  Template: $TMPL_STORAGE\n\nProceed?" 20 70 || die "Cancelled by user."

# ── Debian 12 template ───────────────────────────────────────────────────────
msg_info "Locating Debian 12 template"
pveam update >/dev/null 2>&1 || true
TEMPLATE=$(pveam available --section system 2>/dev/null | sed -n 's/.*\(debian-12-standard_.*_amd64.tar.zst\).*/\1/p' | tail -1)
[ -z "$TEMPLATE" ] && die "debian-12-standard template not found in 'pveam available'."
msg_ok "Template: $TEMPLATE"

if ! pveam list "$TMPL_STORAGE" 2>/dev/null | grep -q "$TEMPLATE"; then
  msg_info "Downloading template (may take a while)"
  pveam download "$TMPL_STORAGE" "$TEMPLATE" >/dev/null 2>&1 || die "Failed to download the template."
  msg_ok "Template downloaded"
fi

# ── Container creation ───────────────────────────────────────────────────────
NET0="name=eth0,bridge=${BRG},ip=${NET}"
[ "$NET" != "dhcp" ] && [ -n "$GATE" ] && NET0="${NET0},gw=${GATE}"

msg_info "Creating LXC container $CTID"
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
msg_ok "Container created"

msg_info "Starting container"
pct start "$CTID" >/dev/null
msg_ok "Container started"

# ── Wait for network ─────────────────────────────────────────────────────────
msg_info "Waiting for network in the container"
for i in $(seq 1 30); do
  if pct exec "$CTID" -- getent hosts github.com >/dev/null 2>&1; then break; fi
  sleep 2
  [ "$i" = "30" ] && die "Container has no DNS/network resolution after 60s."
done
msg_ok "Network ready"

IP=$(pct exec "$CTID" -- bash -c "hostname -I | awk '{print \$1}'" 2>/dev/null | tr -d '\r')

# ── Base URL / secure cookies ────────────────────────────────────────────────
if [ -n "$DOMAIN" ]; then
  APP_BASE_URL="https://${DOMAIN}"; SECURE_COOKIES="1"
else
  APP_BASE_URL="http://${IP}:8001"; SECURE_COOKIES="0"
fi

# ── App installation inside the container ────────────────────────────────────
msg_info "Preparing dependencies (curl)"
pct exec "$CTID" -- bash -c "apt-get update -qq && apt-get install -y -qq curl ca-certificates >/dev/null 2>&1" || die "Failed to install curl."
msg_ok "Base dependencies ready"

msg_info "Installing $APP (public clone + venv + systemd)"
pct exec "$CTID" -- bash -c "
  DOMAIN='${DOMAIN:-}' APP_BASE_URL='${APP_BASE_URL}' SECURE_COOKIES='${SECURE_COOKIES}' \
  USE_BR_MIRROR='${USE_BR_MIRROR}' \
  bash <(curl -fsSL '${SETUP_URL}')
" || die "setup-inside.sh failed (see: pct exec $CTID -- journalctl -u spool-control -n 40)."
msg_ok "$APP installed"

# ── Admin password + result ──────────────────────────────────────────────────
ADMIN_PASS=$(pct exec "$CTID" -- bash -c "grep '^ADMIN_DEFAULT_PASS=' /opt/spool-control/spool.env | cut -d= -f2-" 2>/dev/null | tr -d '\r')
HEALTH=$(pct exec "$CTID" -- bash -c "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8001/health" 2>/dev/null || echo "000")

trap - ERR
echo
echo -e "${GN}=====================================================${CL}"
echo -e "${GN}  $APP installed successfully!${CL}"
echo -e "${GN}=====================================================${CL}"
echo -e "  CTID:      ${BL}${CTID}${CL}  (${HN})"
echo -e "  IP:        ${BL}${IP}${CL}"
echo -e "  Access:    ${GN}${APP_BASE_URL}${CL}"
echo -e "  Direct:    http://${IP}:8001   (health → HTTP ${HEALTH})"
echo -e "  Login:     admin / ${GN}${ADMIN_PASS}${CL}"
echo -e "  Update:    pct exec ${CTID} -- bash /opt/spool-control/deploy/update-lxc.sh"
echo -e "${GN}=====================================================${CL}"
[ -z "$DOMAIN" ] && echo -e "  ${YW}Direct HTTP access — for HTTPS, put it behind a proxy and re-run with a domain.${CL}"
echo
