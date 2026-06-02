# Changelog

Versionamento seguindo [SemVer](https://semver.org/lang/pt-BR/): **MAJOR.MINOR.PATCH**

| Dígito | Quando incrementar |
|---|---|
| **MAJOR** | Quebra de compatibilidade — mudança de schema incompatível, remoção de rotas, reestruturação do deploy |
| **MINOR** | Nova funcionalidade adicionada de forma compatível — nova rota, novo relatório, nova integração |
| **PATCH** | Correção de bug, ajuste visual, melhoria de texto, atualização de dependência |

---

## [1.0.0] — 2026-06-02

Primeira versão em produção.

### Funcionalidades
- Cadastro de filamentos (material, marca, família, cor, diâmetro)
- Dropdown de marcas com logos automáticos (Google Favicon API) e upload manual
- Lista de materiais expandida (~45 tipos), ordenada pelos cadastrados no sistema
- Múltiplos spools por filamento com tara por modelo de carretel ou personalizada
- Workflow de pesagem: peso bruto − tara = net, com histórico
- Pesagem rápida (`/weigh`): código SP-XXXX + peso bruto, sem navegar pelo spool
- Etiquetas térmicas PDF 60×40mm com QR code (sem peso impresso)
- Fila de impressão de etiquetas em lote com badge de contagem no menu
- Prompt automático de fila ao criar spool ou alterar localização
- Relatórios: por material, por local, estoque baixo, histórico de peso
- Filtro instantâneo client-side e colunas ordenáveis nas listagens
- Busca global no navbar (`/search`)
- Autenticação Flask com roles admin/viewer
- Página pública por spool (`/spools/<id>`) — alvo do QR code, sem login
- Admin: usuários, marcas/logos, configurações (base URL, thresholds de estoque)

### Deploy
- Debian 12 LXC no Proxmox
- Gunicorn com `--preload` (2 workers, evita race condition no bootstrap)
- Traefik via Proxmox Provider (Notes da LXC) + Let's Encrypt DNS challenge
- Scripts: `setup-inside.sh` (instalação), `update-lxc.sh` (atualização), `seed_brands.py` (logos)
