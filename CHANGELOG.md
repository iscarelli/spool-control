# Changelog

Versionamento seguindo [SemVer](https://semver.org/lang/pt-BR/): **MAJOR.MINOR.PATCH**

| Dígito | Quando incrementar |
|---|---|
| **MAJOR** | Quebra de compatibilidade — mudança de schema incompatível, remoção de rotas, reestruturação do deploy |
| **MINOR** | Nova funcionalidade adicionada de forma compatível — nova rota, novo relatório, nova integração |
| **PATCH** | Correção de bug, ajuste visual, melhoria de texto, atualização de dependência |

---

## [1.1.0] — 2026-06-02

### Adicionado
- Busca global no navbar (`/search`) + filtro instantâneo client-side nas listas de filamentos e spools
- Colunas ordenáveis nas listas (click no cabeçalho, ícone ⇅/↑/↓)
- Fila de impressão de etiquetas: adicionar/remover spools, badge de contagem no menu, imprimir tudo em PDF, limpar fila
- Prompt automático de fila ao criar spool ou alterar localização
- Pesagem rápida (`/weigh`): código SP-XXXX + peso bruto → net calculado automaticamente
- Logos de marcas: download via Google Favicon API + upload manual (Admin → Marcas)
- Dropdown de marcas no form de filamento ordenado por uso (em uso primeiro, depois outras, + nova marca)
- Tamanho da etiqueta configurável (largura × altura mm) em Admin → Configurações
- Preview de cor + link direto "Editar cor / filamento" no form de edição de spool
- Filamento pode ser trocado ao editar spool (muda material, cor, marca)
- Lista de filamentos: Material, Marca e Família são links que filtram a lista de spools
- Lista de spools: botão de fila de impressão (mostra estado) + botão editar inline
- Botão duplicar filamento (copia só os campos, sem spools, abre edição)
- Botão remover filamento (habilitado só sem spools; tooltip explica quando desabilitado)
- Fluxo `?next=` na edição de filamento: salvar cor retorna para a tela do spool
- Código SP-XXXX exibido no título do form de edição de spool
- Ícone SVG de balança de cozinha personalizado (Bootstrap Icons não tem balança)
- Ícone SVG de spool como favicon e logo da navbar
- Badge de versão fixo no canto inferior direito

### Corrigido
- `bi-balance-scale` não existe no Bootstrap Icons 1.11.3 — substituído por SVG próprio
- `cp -r templates` criava `templates/templates/` no update-lxc.sh — corrigido para `cp -r templates/.`
- Tooltip em botão `disabled` — `title` nativo não dispara; substituído por Bootstrap tooltip (`data-bs-toggle`)
- `d-flex` em `<td>` causava barra branca na lista de filamentos — removido
- `--preload` adicionado ao gunicorn para evitar race condition no bootstrap com 2 workers
- `INSERT OR IGNORE` no bootstrap do admin para evitar erro em múltiplos workers
- Ícones de ordenação invisíveis em cabeçalho dark — `color:inherit` no lugar de `text-muted`

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
