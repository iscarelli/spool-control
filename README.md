# Spool Control

Sistema web para gerenciamento de filamentos de impressão 3D.

Registre filamentos, catalogue carretéis, pesagem com cálculo automático de tara, etiquetas térmicas 60×40mm com QR code e relatórios de estoque.

## Funcionalidades

- Cadastro de filamentos (material, marca, família, cor) com logos de marca automáticos
- Múltiplos spools por filamento com histórico de pesagens
- Pesagem rápida: informe o código do spool e o peso bruto — o sistema subtrai a tara
- Etiquetas PDF 60×40mm com QR code (aponta para página pública do spool)
- Fila de impressão de etiquetas em lote
- Relatórios: por material, por local, estoque baixo, histórico de pesos
- Busca e ordenação nas listagens
- Autenticação com controle de acesso (admin / viewer)

## Stack

| Camada | Tecnologia |
|---|---|
| Backend | Flask 3.x + Gunicorn |
| Banco | SQLite (WAL mode) |
| Frontend | Bootstrap 5.3 + Bootstrap Icons |
| Etiquetas | ReportLab + qrcode + Pillow |
| Deploy | Systemd + Traefik |

## Estrutura

```
spool-control/
├── app.py              # Rotas Flask
├── database.py         # Schema SQLite e helpers
├── labels.py           # Geração de PDF de etiquetas
├── requirements.txt
├── static/
│   ├── spool.css
│   ├── spool.js        # Filtro e ordenação client-side
│   ├── spool-icon.svg
│   └── brands/         # Logos de marcas (gerados em deploy)
├── templates/
└── deploy/
    ├── spool-control.service
    ├── setup-inside.sh     # Instalação inicial (dentro do LXC)
    ├── update-lxc.sh       # Atualização via git pull
    └── seed_brands.py      # Download de logos de marcas
```

`data/spool.db` e `spool.env` ficam fora do git (gerados no servidor).

## Deploy — Proxmox LXC

Testado em Debian 12 (Bookworm). O script `setup-inside.sh` automatiza toda a instalação.

### Pré-requisitos

- LXC Debian 12 com acesso à internet
- Repositório clonável via token GitHub (`gh auth token`)
- Traefik rodando na rede com suporte ao [Proxmox Provider](https://github.com/juliens/traefik-proxmox-provider) (opcional — para HTTPS automático)

### 1 — Criar o LXC

```bash
pct create <VMID> local:vztmpl/debian-12-standard_12.12-1_amd64.tar.zst \
  --hostname spool \
  --cores 1 --memory 512 --swap 512 \
  --rootfs local-lvm:8 \
  --net0 name=eth0,bridge=vmbr0,ip=dhcp \
  --nameserver <DNS_IP> \
  --unprivileged 1 --features nesting=1 \
  --start 1
```

### 2 — Reservar IP fixo

Configure a reserva DHCP no seu roteador para o MAC da LXC antes de reiniciar. Após reiniciar, confirme o IP:

```bash
pct exec <VMID> -- ip addr show eth0 | grep 'inet '
```

### 3 — Instalar o projeto

Copie `deploy/setup-inside.sh` para dentro da LXC e execute como root, passando o GitHub token:

```bash
# Do nó Proxmox
pct push <VMID> /caminho/setup-inside.sh /tmp/setup-inside.sh
pct exec <VMID> -- bash /tmp/setup-inside.sh <GITHUB_TOKEN>
```

O script instala dependências, clona o repositório, cria o virtualenv, configura o serviço systemd e imprime a **senha inicial do admin** ao final.

### 4 — Configurar HTTPS via Traefik (Proxmox Provider)

O Traefik lê o campo **Notes** da LXC via API do Proxmox. Configure assim:

```bash
pct set <VMID> -description $'traefik.enable=true
traefik.http.routers.spool.rule: Host(`spool.exemplo.com.br`)
traefik.http.routers.spool.entrypoints=websecure
traefik.http.routers.spool.tls.certresolver=letsencrypt
traefik.http.services.spool.loadbalancer.server.url: http://<IP_DA_LXC>:8001'
```

> **Formato das labels:** use `=` para valores simples e `: ` (com espaço) quando o valor contém `:` (URLs e regras Host).

Aguarde ~30s para o Traefik detectar a rota. Verifique em `https://spool.exemplo.com.br/health`.

### 5 — Atualizações futuras

Após o primeiro deploy, salve o token para uso interno:

```bash
pct exec <VMID> -- bash /opt/spool-control/deploy/update-lxc.sh --setup <GITHUB_TOKEN>
```

A partir daí, atualizações são feitas com:

```bash
pct exec <VMID> -- bash /opt/spool-control/deploy/update-lxc.sh
```

### 6 — Download de logos de marcas

Após o primeiro acesso, execute para baixar logos das marcas mais conhecidas:

```bash
pct exec <VMID> -- /opt/spool-control/.venv/bin/python3 /opt/spool-control/deploy/seed_brands.py
```

Os logos são salvos em `static/brands/` e exibidos automaticamente na listagem de filamentos. Novos logos podem ser adicionados em **Admin → Marcas / Logos**.

## Credenciais iniciais

- Usuário: `admin`
- Senha: gerada aleatoriamente pelo `setup-inside.sh` (exibida ao final da instalação)

Troque imediatamente em **Admin → Usuários**.

## Variáveis de ambiente (`spool.env`)

Gerado automaticamente pelo `setup-inside.sh`. Exemplo:

```env
SECRET_KEY=<hex aleatório>
ADMIN_DEFAULT_PASS=<senha inicial>
APP_BASE_URL=https://spool.exemplo.com.br
SECURE_COOKIES=1
```

> `spool.env` está no `.gitignore` e nunca deve ser commitado.
