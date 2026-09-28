Código: spoolmandb_refresh.py, filament_catalog.py, deploy/vendor-spoolmandb.sh,
deploy/backup-cron.py, routes/admin.py, routes/filaments.py,
templates/admin/update.html, spoolman_catalog.json

# Catálogo de filamentos (SpoolmanDB)

O cadastro de filamento tem um botão **"Importar do catálogo"** que pré-preenche marca,
material, família, cor e diâmetro a partir de uma base aberta de filamentos. O usuário
revisa e salva normalmente.

## Fonte e licença

- **Upstream:** [github.com/Donkie/SpoolmanDB](https://github.com/Donkie/SpoolmanDB) —
  base comunitária de filamentos, **licença MIT**. JSON compilado servido em
  <https://donkie.github.io/SpoolmanDB/> (`filaments.json`, `materials.json`).
- **Atribuição (MIT):** os dados de filamento são © contribuidores do SpoolmanDB, sob MIT.
  O aviso fica no campo `_source` de cada snapshot e no rodapé do modal de busca.

## Duas cópias, uma regra de precedência (desde a v1.39.2)

Até a v1.39.1 o catálogo era só o snapshot **vendorado** — sem download em runtime,
igual ao Niimbot. A partir daqui isso é **revertido só para o catálogo**: o servidor
passou a manter também uma cópia própria, atualizada automaticamente. As DUAS cópias
convivem; `filament_catalog.py` decide qual usar a cada acesso:

1. **`data/spoolman_catalog.json`** — gravada em runtime pelo refresh diário
   (`spoolmandb_refresh.run_scheduled_refresh`, chamado pelo cron do backup) ou pelo
   botão **"Atualizar catálogo agora"** em `/admin/update`. Usada quando existe, é
   válida (JSON parseável, lista de filamentos não vazia) **e** sua data `fetched` é
   maior ou igual à da cópia vendorada (nunca regride para uma cópia mais velha).
2. **`spoolman_catalog.json`** (raiz do repo) — snapshot **vendorado**, committado no
   git, atualizado manualmente por `deploy/vendor-spoolmandb.sh`. Fallback sempre
   disponível: numa instalação nova, ou se o download em runtime nunca funcionou, o
   catálogo não fica vazio à toa (preserva a operação offline).
3. Nenhuma das duas válida → listas vazias — o botão "Importar do catálogo" some, mas
   `import app` nunca falha por causa disso (FAIL-SAFE).

A escolha é reavaliada a cada acesso via `os.stat` (mtime) das duas cópias — carga
LAZY: só reabre e reparseia o JSON quando algum mtime muda. Isso é o que permite os
**dois workers do gunicorn** (processos separados, sem memória compartilhada) verem um
refresh escrito por qualquer um dos dois (ou pelo cron) sem reiniciar o serviço.

A transformação (download → filtro → dedup → sort) é uma função pura só,
`spoolmandb_refresh.build_snapshot`, compartilhada pelas três formas de gerar um
snapshot (dev script, cron diário, botão manual) — uma só fonte da lógica.

## Atualização automática (diária, piggyback no cron do backup)

`deploy/backup-cron.py` (rodado de hora em hora pelo `spool-backup.timer`, ver
`docs/atualizacao.md`/`backup.py`) chama, depois do backup, `spoolmandb_refresh.
run_scheduled_refresh()` — mesmo padrão do backup: no-op se já houve um refresh
bem-sucedido HOJE (data local), tenta de novo na hora seguinte se a última tentativa
falhou. Grava o resultado em `settings`: `catalog_refresh_last_run`,
`catalog_refresh_result` (`ok`/`error`), `catalog_refresh_error`. Uma falha no
catálogo NUNCA afeta o backup e vice-versa (cada um roda no seu próprio try/except,
redundante de propósito — ver comentário no topo de `deploy/backup-cron.py`).

## Atualização manual (botão, ou script de dev)

- **Botão "Atualizar catálogo agora"** em `/admin/update` (só admin) → POST
  `/admin/catalog/refresh` (`routes/admin.py`) → roda o MESMO `fetch_and_write`
  síncrono (teto de ~30s), grava em `data/spoolman_catalog.json` e nos mesmos campos
  de `settings` do refresh automático. Sucesso ou falha vira flash na página, que
  também mostra a data do snapshot em uso, a fonte (servidor/vendorado) e o
  resultado/erro da última tentativa automática.
- **Script de dev** (snapshot VENDORADO, committado):
  ```bash
  deploy/vendor-spoolmandb.sh      # baixa, transforma e regrava spoolman_catalog.json
  # revisar git diff, bump VERSION + CHANGELOG, commit, deploy
  ```

Os dois caminhos (automático e manual, servidor) escrevem em `data/`, nunca no
`spoolman_catalog.json` da raiz — só o script de dev toca o arquivo vendorado/committado.

## Arquivos

| Arquivo | Papel |
|---|---|
| `spoolmandb_refresh.py` | Transformação pura (`build_snapshot`) + download/escrita atômica (`fetch_and_write`) + agendamento diário (`run_scheduled_refresh`) — fonte única, usada pelo script de dev, pelo cron e pela rota manual |
| `deploy/vendor-spoolmandb.sh` | Dev-run do refresh do snapshot VENDORADO (raiz do repo, committado) |
| `deploy/backup-cron.py` | Chama o backup e, no mesmo tick, `run_scheduled_refresh()` |
| `spoolman_catalog.json` | Snapshot vendorado (raiz do repo) — fallback sempre disponível |
| `data/spoolman_catalog.json` | Cópia gravada em runtime (fora do git) — preferida quando válida e não mais velha que a vendorada |
| `filament_catalog.py` | Resolve qual cópia usar e expõe `get_brands()`/`get_materials()`/`get_filaments()`/`info()`/`available()` — **fail-safe**, carga lazy com reload por mtime |
| `routes/admin.py` → `/admin/catalog/refresh` | Botão manual (só admin) |
| `routes/filaments.py` → `/api/filament-catalog` | Expõe o catálogo (login) para o picker |
| `static/filament-catalog.js` | Picker: enriquece datalists + modal de busca + pré-preenche o form |

## Mapeamento de campos (SpoolmanDB → spool-control)

| spool-control | SpoolmanDB | Observação |
|---|---|---|
| `brand` | `manufacturer` | marca nova entra sozinha ao salvar |
| `material` | `material` | como vem (PLA, PETG, PLA+…) |
| `family` | `finish` | "Matte"/"Silk"… ; `glossy`/ausente → em branco |
| `color_hex` | `#` + `color_hex` | ver **"Cor de 8 dígitos"** abaixo |
| `diameter_mm` | `diameter` | só preenche se casar com 1.75/2.85 |
| `notes` | `name` (nome da cor) | só se as Notas estiverem vazias |
| `translucent` (checkbox "Transparente / translúcido") | `translucent` OU alfa < 0xFF (ver abaixo) | v1.39.2 — pré-preenchido no import, editável antes de salvar |

### Cor de 8 dígitos (transparência) e o campo `translucent`

Uma minoria das entradas do `filaments.json` traz `color_hex` de **8 dígitos**
em vez de 6 — formato **AARRGGBB** (alfa + RGB), confirmado contra o próprio
JSON em 2026-09: `3C8AD77F` em "Neon Green" (AmazonBasics) só faz sentido como
alfa `3C` (~24%, translúcido) + RGB `8AD77F` (verde) — a leitura alternativa
RRGGBBAA daria azul. `spoolmandb_refresh._normalize_hex` separa os dois:
normaliza para `#rrggbb` (últimos 6 dígitos) e marca `translucent=True` quando
o alfa é < `FF`, **OU** quando o campo booleano `translucent` do próprio
upstream já vem `true` (385 entradas no snapshot de 2026-09-27, ~273 depois do
dedup). O `translucent` entra na CHAVE de dedup — duas entradas iguais em
tudo mais, mas uma opaca e outra translúcida, viram duas linhas.

**Ruído conhecido, não corrigido:** um lote de ~20 entradas de um único
contribuidor ("Das Filament") parece usar a ordem inversa (RGB primeiro,
alfa depois) — não há como distinguir os dois formatos por marca sem
heurística, e a maioria (inclusive todo `…FFFFFF` = Clear/Transparent em 5
fabricantes diferentes) bate com AARRGGBB. Vira, na pior hipótese, uma cor
levemente errada para esse lote — nunca quebra o import nem o app.
