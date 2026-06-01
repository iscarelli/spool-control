#!/bin/bash
# Remove system dirs erroneamente copiados para /opt/spool-control/
ssh -i ~/.ssh/claude_proxmox claude@10.1.0.16 \
  "sudo /usr/sbin/pct exec 117 -- bash -c '
    cd /opt/spool-control
    rm -rf bin boot dev etc home lib lib64 lost+found media mnt opt proc root run sbin srv sys tmp usr var
    echo "Limpeza concluída"
    df -h /
    ls /opt/spool-control/
  '"
