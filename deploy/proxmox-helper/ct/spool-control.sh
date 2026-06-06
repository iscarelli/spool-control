#!/usr/bin/env bash
source <(curl -fsSL https://raw.githubusercontent.com/community-scripts/ProxmoxVE/main/misc/build.func)
# Copyright (c) 2021-2026 community-scripts ORG
# Author: iscarelli
# License: MIT | https://github.com/community-scripts/ProxmoxVE/raw/main/LICENSE
# Source: https://github.com/iscarelli/spool-control

APP="Spool-Control"
var_tags="${var_tags:-3dprinting;inventory}"
var_cpu="${var_cpu:-1}"
var_ram="${var_ram:-256}"
var_disk="${var_disk:-2}"
var_os="${var_os:-debian}"
var_version="${var_version:-12}"
var_arm64="${var_arm64:-no}"
var_unprivileged="${var_unprivileged:-1}"

header_info "$APP"
variables
color
catch_errors

function update_script() {
  header_info
  check_container_storage
  check_container_resources

  if [[ ! -d /opt/spool-control ]]; then
    msg_error "No ${APP} Installation Found!"
    exit
  fi

  if check_for_gh_release "spool-control" "iscarelli/spool-control"; then
    msg_info "Stopping ${APP}"
    systemctl stop spool-control
    msg_ok "Stopped ${APP}"

    msg_info "Backing Up Data"
    cp /opt/spool-control/spool.env /tmp/spool-env.bak
    cp -r /opt/spool-control/data/ /tmp/spool-data.bak/
    msg_ok "Backed Up Data"

    CLEAN_INSTALL=1 fetch_and_deploy_gh_release "spool-control" "iscarelli/spool-control" "tarball"

    msg_info "Restoring Data"
    cp /tmp/spool-env.bak /opt/spool-control/spool.env
    rm -rf /opt/spool-control/data/
    cp -r /tmp/spool-data.bak/ /opt/spool-control/data/
    rm -f /tmp/spool-env.bak
    rm -rf /tmp/spool-data.bak/
    msg_ok "Restored Data"

    msg_info "Updating Python Dependencies"
    source /opt/spool-control/.venv/bin/activate
    pip install -q -r /opt/spool-control/requirements.txt
    deactivate
    msg_ok "Updated Python Dependencies"

    msg_info "Starting ${APP}"
    chown -R spool:spool /opt/spool-control
    systemctl start spool-control
    msg_ok "Started ${APP}"
    msg_ok "Updated Successfully!"
  fi
  exit
}

start
build_container
description

msg_ok "Completed Successfully!\n"
echo -e "${CREATING}${GN}${APP} setup has been successfully initialized!${CL}"
echo -e "${INFO}${YW} Access it using the following URL:${CL}"
echo -e "${TAB}${GATEWAY}${BGN}http://${IP}:8001${CL}"
echo -e "${INFO}${YW} Admin credentials: ${BGN}admin${CL} / password in ${BGN}/opt/spool-control/.admin-pass${CL}"
