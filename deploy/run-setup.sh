#!/bin/bash
# Repositório público — sem token. O setup clona anonimamente.
set -e
SCRIPT=~/Library/CloudStorage/OneDrive-Personal/Projects/spool-control/deploy/setup-inside.sh

echo "==> Enviando setup-inside.sh para a LXC..."
scp -i ~/.ssh/claude_proxmox "$SCRIPT" claude@10.1.0.16:/tmp/setup-inside.sh
ssh -i ~/.ssh/claude_proxmox claude@10.1.0.16 \
  "sudo /usr/sbin/pct push 117 /tmp/setup-inside.sh /tmp/setup-inside.sh"

echo "==> Executando setup..."
ssh -i ~/.ssh/claude_proxmox claude@10.1.0.16 \
  "sudo /usr/sbin/pct exec 117 -- bash /tmp/setup-inside.sh"
