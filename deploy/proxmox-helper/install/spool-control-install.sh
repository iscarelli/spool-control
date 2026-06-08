#!/usr/bin/env bash
# Copyright (c) 2021-2026 community-scripts ORG
# Author: iscarelli
# License: MIT | https://github.com/community-scripts/ProxmoxVE/raw/main/LICENSE
# Source: https://github.com/iscarelli/spool-control

# ── Framework compatibility ───────────────────────────────────────────────────
# When run via the community-scripts framework, $FUNCTIONS_FILE_PATH is injected.
# When run standalone (manual install on a plain Debian 12 LXC), stub functions
# are defined below so the script works without the framework.
if [[ -n "${FUNCTIONS_FILE_PATH:-}" ]]; then
  source /dev/stdin <<<"$FUNCTIONS_FILE_PATH"
  color
  verb_ip6
  catch_errors
  setting_up_container
  network_check
  update_os
else
  set -euo pipefail
  GN='\033[1;92m' YW='\033[33m' RD='\033[01;31m' CL='\033[m'
  msg_info()  { echo -ne " ${YW}◈${CL} $1..."; }
  msg_ok()    { echo -e "\r${GN}✓${CL} $1   "; }
  msg_error() { echo -e "\r${RD}✗${CL} $1"; exit 1; }
  STD=""
  cleanup_lxc() { apt-get -y autoremove -qq; apt-get -y autoclean -qq; }
  motd_ssh()  { :; }
  customize() { :; }
  apt-get update -qq
  DEBIAN_FRONTEND=noninteractive apt-get upgrade -y -qq
fi

msg_info "Installing Dependencies"
$STD apt-get install -y \
  python3 \
  python3-venv \
  python3-pip \
  git \
  curl \
  sudo \
  libssl-dev \
  libffi-dev \
  libjpeg-dev \
  zlib1g-dev
msg_ok "Installed Dependencies"

msg_info "Creating spool User"
useradd -r -s /usr/sbin/nologin -d /opt/spool-control spool 2>/dev/null || true
msg_ok "Created spool User"

if [[ -n "${FUNCTIONS_FILE_PATH:-}" ]]; then
  fetch_and_deploy_gh_release "spool-control" "iscarelli/spool-control" "tarball"
else
  msg_info "Cloning Repository"
  rm -rf /tmp/spool-repo
  $STD git clone -q https://github.com/iscarelli/spool-control.git /tmp/spool-repo
  mkdir -p /opt/spool-control
  git -C /tmp/spool-repo archive HEAD | tar -x -C /opt/spool-control
  rm -rf /tmp/spool-repo
  msg_ok "Cloned Repository"
fi

msg_info "Setting Up Python Environment"
python3 -m venv /opt/spool-control/.venv
source /opt/spool-control/.venv/bin/activate
$STD pip install --upgrade pip
$STD pip install -r /opt/spool-control/requirements.txt
deactivate
msg_ok "Set Up Python Environment"

msg_info "Configuring Spool-Control"
SECRET_KEY=$(openssl rand -hex 32)
ADMIN_PASS=$(openssl rand -base64 12 | tr -d '/+=')
SPOOL_API_KEY=$(openssl rand -hex 24)
mkdir -p /opt/spool-control/data

cat <<EOF >/opt/spool-control/spool.env
SECRET_KEY=${SECRET_KEY}
ADMIN_DEFAULT_PASS=${ADMIN_PASS}
SPOOL_API_KEY=${SPOOL_API_KEY}
EOF
chmod 600 /opt/spool-control/spool.env

# Write password to a readable file inside the container for reference
echo "${ADMIN_PASS}" >/opt/spool-control/.admin-pass
chmod 600 /opt/spool-control/.admin-pass
msg_ok "Configured Spool-Control"

msg_info "Setting Permissions"
chown -R spool:spool /opt/spool-control
msg_ok "Set Permissions"

msg_info "Creating Service"
ln -sf /opt/spool-control/deploy/spool-control.service /etc/systemd/system/spool-control.service
# Autoatualizacao pela web SEM privilegio: flag-file + systemd .path watcher (o app nao usa sudo).
ln -sf /opt/spool-control/deploy/spool-update.service /etc/systemd/system/spool-update.service
ln -sf /opt/spool-control/deploy/spool-update.path    /etc/systemd/system/spool-update.path
systemctl daemon-reload
$STD systemctl enable spool-control
$STD systemctl enable --now spool-update.path || true
$STD systemctl start spool-control
msg_ok "Created and Started Service"

motd_ssh
customize
cleanup_lxc
