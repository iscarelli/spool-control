# Changelog

Versionamento seguindo [SemVer](https://semver.org/lang/pt-BR/): **MAJOR.MINOR.PATCH**

| Dígito | Quando incrementar |
|---|---|
| **MAJOR** | Quebra de compatibilidade — mudança de schema incompatível, remoção de rotas, reestruturação do deploy |
| **MINOR** | Nova funcionalidade adicionada de forma compatível — nova rota, novo relatório, nova integração |
| **PATCH** | Correção de bug, ajuste visual, melhoria de texto, atualização de dependência |

---

## [1.4.8] — 2026-06-02

### Corrigido
- Mensagem da fila usa singular/plural correto: "1 spool adicionado" vs "N spools adicionados/removidos"

---

## [1.4.7] — 2026-06-02

### Adicionado
- Botão "Todos" na lista de spools vira toggle: se todos visíveis já estão na fila, remove todos; caso contrário, adiciona todos
- Flash de sucesso agora exibe como toast top-center que some automaticamente em 3 segundos

---

## [1.4.6] — 2026-06-02

### Adicionado
- Opção "Novo material..." no dropdown de material do formulário de filamento — permite cadastrar tipos não listados (mesmo padrão já existente para marcas)

---

## [1.4.1] — 2026-06-02

### Corrigido
- Ícone do carretel na navbar some no light mode — substituído `filter:invert(0.9)` inline por classe `.brand-icon` controlada via CSS por tema
- Donuts ainda mais espessos: stroke-width 15, viewBox 50×50, cx/cy 25 — buraco interno ~36% do diâmetro externo, próximo da referência visual

---

## [1.4.0] — 2026-06-02

### Adicionado
- **Dark/Light mode**: toggle no navbar, preferência salva no localStorage, sem flash no carregamento
- **i18n PT/BR → EN**: infraestrutura de tradução em `translations.py`, alternador PT|EN no navbar, rotas `/lang/pt` e `/lang/en`, strings de navegação e listas traduzidas
- CSS design tokens para light mode (`[data-bs-theme="light"]`)

### Alterado
- Donuts ainda mais espessos: stroke-width 9, viewBox 44×44, cx/cy 22 — diâmetro externo mantido
- Track dos donuts adaptável ao tema via classe `.donut-track` e `var(--sc-border)`
- Botões "+ Novo Filamento" e "+ Novo Spool": `btn-outline-primary` (verde contornado) — mais discreto
- Botão de pesagem inline: `btn-outline-secondary` ao invés de `btn-outline-dark`
- Donut macro Jinja reutilizável nos 3 templates principais

---

## [1.3.1] — 2026-06-02

### Adicionado
- Donut de estoque no título da página de detalhe do filamento (`/filaments/<id>`)
- Donuts por spool na listagem de spools dentro do detalhe do filamento
- Clique em qualquer lugar da linha abre o detalhe (filamentos e spools)
- Modal inline de pesagem na listagem de spools: registra peso sem sair da página, atualiza donut e peso na hora
- Botão "Fila: Todos" na listagem de spools: adiciona todos os spools visíveis à fila de impressão
- Rota `POST /label-queue/add-all` para enfileirar múltiplos spools de uma vez
- Suporte AJAX no endpoint de pesagem (`X-Requested-With: XMLHttpRequest` → resposta JSON)

### Alterado
- Removido donut agregado do título da listagem de filamentos (agora aparece no detalhe de cada filamento)
- Donuts com stroke mais grosso (stroke-width 6, viewBox 40×40) — diâmetro externo mantido
- Removida barra de progresso da listagem de spools do detalhe de filamento (substituída por donut)

---

## [1.3.0] — 2026-06-02

### Adicionado
- Design system completo: dark mode nativo Bootstrap 5.3 (`data-bs-theme="dark"`) com paleta slate/green
- Font Inter (Google Fonts) para toda a interface; Fira Code para badge de versão
- Design tokens CSS (`--sc-bg`, `--sc-surface`, `--sc-accent`, etc.) como base de theming
- Navbar com indicador de página ativa (`.sc-active`) por endpoint Flask

### Alterado
- Navbar: layout refinado, gap entre itens, dropdowns com bordas arredondadas e sombra
- Tabelas: header com tipografia uppercase 0.7rem + letter-spacing; background `#111827`
- Botões: paleta revisada — primário verde, secundário slate, danger/warning sutis
- Alerts: fundo translúcido colorido ao invés de sólido
- Cards: superfície `#1E293B`, borda `#334155`, border-radius 10px
- Badge de versão: monoespaçado, posicionado fixo no canto inferior direito
- Botões "+ Novo Filamento" e "+ Novo Spool": `btn-primary` (verde) ao invés de `btn-dark`

---

## [1.2.1] — 2026-06-02

### Alterado
- QR Code das etiquetas: ECC elevado de M (15%) para Q (25%) — maior robustez de leitura para a futura estação física com GM861-LED

---

## [1.2.0] — 2026-06-02

### Adicionado
- Gráfico de rosca (donut SVG) na lista de filamentos: exibe proporção de estoque restante vs. nominal de todos os spools ativos, usando a cor do filamento
- Donut agregado no título da lista de filamentos, mostrando o percentual total de estoque disponível entre todos os filamentos
- Gráfico de rosca (donut SVG) na lista de spools: exibe proporção restante de cada rolo individualmente, usando a cor do filamento
- Script de deploy (`update-lxc.sh`) passa a copiar o `CHANGELOG.md` para o servidor a cada atualização

### Alterado
- Lista de filamentos: removido swatch de cor antes da Família (substituído pelo donut)
- Lista de spools: removido swatch de cor e barra de progresso (substituídos pelo donut)

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
