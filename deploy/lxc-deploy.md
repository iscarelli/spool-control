# Deploy — spool-control no Proxmox

Infraestrutura: CasaMMD / CasaMMD1 — rede 10.1.0.0/23

---

## Valores definidos

| Campo | Valor |
|---|---|
| VMID | **117** (próximo livre após 116) |
| IP | **10.1.0.29** (próximo sugerido livre) |
| Hostname | `spool` |
| Nó | CasaMMD1 (`claude@10.1.0.16`) |
| Porta do app | `8001` |
| Domínio | `spool.lojinharacer.com.br` |

---

## Passo 1 — Confirmar VMIDs e IPs em uso

```bash
ssh -i ~/.ssh/claude_proxmox claude@10.1.0.15 "sudo /usr/sbin/pct list; sudo /usr/sbin/qm list"
ssh -i ~/.ssh/claude_proxmox claude@10.1.0.16 "sudo /usr/sbin/pct list; sudo /usr/sbin/qm list"
```

---

## Passo 2 — Criar o LXC

```bash
ssh -i ~/.ssh/claude_proxmox claude@10.1.0.16 "sudo /usr/sbin/pct create 117 \
  local:vztmpl/debian-12-standard_12.12-1_amd64.tar.zst \
  --hostname spool \
  --cores 1 --memory 512 --swap 512 \
  --rootfs local-lvm:8 \
  --net0 name=eth0,bridge=vmbr0,ip=dhcp \
  --nameserver 10.1.0.18 \
  --unprivileged 1 --features nesting=1 \
  --start 1"
```

---

## Passo 3 — Capturar o MAC e reservar o IP no Unifi

```bash
# Capturar MAC
ssh -i ~/.ssh/claude_proxmox claude@10.1.0.16 \
  "sudo /usr/sbin/pct exec 117 -- ip addr show eth0 | grep ether"

# Login Unifi e reserva DHCP (substitua bc:24:11:XX:XX:XX pelo MAC real)
CSRF=$(curl -sk -c /tmp/uc -D - \
  -X POST https://10.1.1.254/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"claude","password":"<UNIFI_PASS>"}' \
  | grep -i 'x-csrf-token:' | tr -d '\r' | awk '{print $2}')

ID=$(curl -sk -b /tmp/uc \
  'https://10.1.1.254/proxy/network/api/s/default/rest/user' \
  | python3 -c "
import sys, json
d = [c for c in json.load(sys.stdin)['data'] if c.get('mac')=='bc:24:11:XX:XX:XX']
print(d[0]['_id'] if d else 'NOT_FOUND')")

curl -sk -b /tmp/uc -H "x-csrf-token: $CSRF" \
  -X PUT "https://10.1.1.254/proxy/network/api/s/default/rest/user/$ID" \
  -H 'Content-Type: application/json' \
  -d '{"fixed_ip":"10.1.0.29","use_fixedip":true,"name":"spool"}'
```

---

## Passo 4 — Reiniciar para pegar o IP fixo

```bash
ssh -i ~/.ssh/claude_proxmox claude@10.1.0.16 \
  "sudo /usr/sbin/pct reboot 117"

# Aguardar ~10s e confirmar
ssh -i ~/.ssh/claude_proxmox claude@10.1.0.16 \
  "sudo /usr/sbin/pct exec 117 -- ip addr show eth0 | grep 'inet '"
# Esperado: inet 10.1.0.29/23
```

---

## Passo 5 — Copiar e instalar o projeto

```bash
# Copiar projeto para a LXC
scp -i ~/.ssh/claude_proxmox -r \
  /Users/iscarelli/Library/CloudStorage/OneDrive-Personal/Projects/spool-control \
  claude@10.1.0.16:/tmp/spool-control

# Mover para dentro da LXC e rodar o setup
ssh -i ~/.ssh/claude_proxmox claude@10.1.0.16 \
  "sudo /usr/sbin/pct exec 117 -- bash -c 'mkdir -p /opt/spool-control'"

ssh -i ~/.ssh/claude_proxmox claude@10.1.0.16 \
  "sudo cp -r /tmp/spool-control/* \$(sudo /usr/sbin/pct mount 117 | grep -o '/var/lib/lxc/117/rootfs')/opt/spool-control/"

# Executar setup dentro da LXC
ssh -i ~/.ssh/claude_proxmox claude@10.1.0.16 \
  "sudo /usr/sbin/pct exec 117 -- bash /opt/spool-control/deploy/setup-inside.sh"
```

---

## Passo 6 — Expor via Traefik (Notes da LXC)

O Traefik lê o campo Notes a cada 30s via API do Proxmox. Labels usando `=` para valores simples e `: ` quando o valor contém `:` (URLs).

```bash
ssh -i ~/.ssh/claude_proxmox claude@10.1.0.16 \
  "sudo /usr/sbin/pct set 117 -description \$'traefik.enable=true
traefik.http.routers.spool.rule: Host(\`spool.lojinharacer.com.br\`)
traefik.http.routers.spool.entrypoints=websecure
traefik.http.routers.spool.tls.certresolver=letsencrypt
traefik.http.services.spool.loadbalancer.server.url: http://10.1.0.29:8001'"
```

---

## Passo 7 — Verificar rota no Traefik

```bash
# Traefik está no LXC 104 no nó CasaMMD (10.1.0.15)
ssh -i ~/.ssh/claude_proxmox claude@10.1.0.15 \
  "sudo /usr/sbin/pct exec 104 -- grep 'spool' /var/log/traefik/traefik.log | tail -5"
# Esperado: "Created router and service for spool (ID: 117)"
```

Após isso: `https://spool.lojinharacer.com.br` com SSL.

---

## Passo 8 — Adicionar ao job de backup

Após confirmar que o serviço está rodando, adicionar VMID 117 ao job de backup do CasaMMD1
(atualmente cobre 106,107,108,109,110,111,112,113,114).

---

## Credenciais iniciais

- Login: `admin` / `admin123`
- Trocar imediatamente em `/admin/users`
- Configurar `APP_BASE_URL` em `/admin/settings` se necessário (já vem `https://spool.lojinharacer.com.br`)
