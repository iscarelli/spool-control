#!/usr/bin/env bash
# Comando `update` (padrão Proxmox Helper Scripts). Instalado como
# /usr/local/bin/update pelo update-lxc.sh. No console do LXC (root), basta:
#
#     update
#
# Atualiza para a última release publicada. Root rodando no próprio shell é o
# caminho normal/seguro — não é o caminho web (que usa o flag + spool-update.path).
exec bash /opt/spool-control/deploy/update-lxc.sh --latest-release "$@"
