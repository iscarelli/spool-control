# Spool Control

Sistema web para gerenciamento de filamentos de impressão 3D.

Registre filamentos, catalogue carretéis, pesagem com cálculo automático de tara, etiquetas térmicas 60×40mm com QR code e relatórios de estoque.

## Funcionalidades

- Cadastro de filamentos (material, marca, família, cor) com logos de marca automáticos
- Múltiplos spools por filamento com histórico de pesagens
- Pesagem rápida: informe o código do spool e o peso bruto — o sistema subtrai a tara
- Etiquetas PDF 60×40mm com QR code (aponta para a página do spool — requer login)
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
    ├── proxmox-deploy.sh   # Instalador LXC p/ Proxmox (cria o container + instala)
    ├── spool-control.service
    ├── setup-inside.sh     # Instalação dentro do LXC (clone público + venv + systemd)
    ├── update-lxc.sh       # Atualização via git pull
    └── seed_brands.py      # Download de logos de marcas
```

`data/spool.db` e `spool.env` ficam fora do git (gerados no servidor).

## Deploy — Proxmox LXC

### Instalação automática (recomendado)

Execute **no host Proxmox VE** (PVE 7+). O instalador cria um LXC Debian 12 e
configura todo o sistema, perguntando CTID, hostname, rede, recursos e URL:

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/iscarelli/spool-control/main/deploy/proxmox-deploy.sh)"
```

Ao final imprime o IP, a URL de acesso e a **senha inicial do admin**. O
repositório é público — nenhuma credencial GitHub é necessária.

> Se informar um **domínio** (atrás de proxy HTTPS), o instalador ativa
> `SECURE_COOKIES=1`. Sem domínio, configura acesso direto via `http://IP:8001`.

### Instalação manual (alternativa)

Em um LXC Debian 12 já existente, como root:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/iscarelli/spool-control/main/deploy/setup-inside.sh)
```

Variáveis opcionais: `DOMAIN`, `APP_BASE_URL`, `SECURE_COOKIES`, `USE_BR_MIRROR`,
`ADMIN_DEFAULT_PASS`. O script instala dependências, clona o repositório
(anônimo), cria o virtualenv, configura o serviço systemd e imprime a senha
inicial do admin.

### Configurar HTTPS via Traefik (Proxmox Provider)

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

### Atualizações futuras

Atualizações puxam a versão mais recente do repositório público (sem token):

```bash
pct exec <VMID> -- bash /opt/spool-control/deploy/update-lxc.sh
# rollback para uma tag/branch específica:
pct exec <VMID> -- bash /opt/spool-control/deploy/update-lxc.sh --ref v1.5.0
```

### Download de logos de marcas

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
