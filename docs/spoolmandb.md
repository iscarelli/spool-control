# Catálogo de filamentos (SpoolmanDB)

O cadastro de filamento tem um botão **"Importar do catálogo"** que pré-preenche marca,
material, família, cor e diâmetro a partir de uma base aberta de filamentos. O usuário
revisa e salva normalmente.

## Fonte e licença

- **Upstream:** [github.com/Donkie/SpoolmanDB](https://github.com/Donkie/SpoolmanDB) —
  base comunitária de filamentos, **licença MIT**. JSON compilado servido em
  <https://donkie.github.io/SpoolmanDB/> (`filaments.json`, `materials.json`).
- **Atribuição (MIT):** os dados de filamento são © contribuidores do SpoolmanDB, sob MIT.
  O aviso fica no campo `_source` do snapshot vendorado e no rodapé do modal de busca.

## Como funciona (vendoring — igual ao Niimbot)

- O catálogo **não** é baixado em runtime nem no deploy (preserva o deploy à prova de
  falhas, o CSP estrito e a operação offline). Ele é **vendorado** como snapshot
  `spoolman_catalog.json` na raiz do repo.
- SpoolmanDB não publica releases/tags → o snapshot vendorado **é o pin** (carimbado com a
  data de coleta no campo `_source`/`fetched`).

## Atualizar o snapshot

```bash
deploy/vendor-spoolmandb.sh      # baixa, transforma e regrava spoolman_catalog.json
# revisar git diff, bump VERSION + CHANGELOG, commit, deploy
```

O script baixa `filaments.json` + `materials.json`, deduplica por
(marca, material, finish, cor, hex, diâmetro) e grava um snapshot compacto.

## Arquivos

| Arquivo | Papel |
|---|---|
| `deploy/vendor-spoolmandb.sh` | Re-vendora o snapshot a partir do SpoolmanDB (manual) |
| `spoolman_catalog.json` | Snapshot vendorado (`brands`, `materials`, `filaments`) |
| `filament_catalog.py` | Carrega o snapshot — **fail-safe** (arquivo ausente/corrompido → listas vazias, app sobe normal) |
| `routes/filaments.py` → `/api/filament-catalog` | Expõe o catálogo (login) para o picker |
| `static/filament-catalog.js` | Picker: enriquece datalists + modal de busca + pré-preenche o form |

## Mapeamento de campos (SpoolmanDB → spool-control)

| spool-control | SpoolmanDB | Observação |
|---|---|---|
| `brand` | `manufacturer` | marca nova entra sozinha ao salvar |
| `material` | `material` | como vem (PLA, PETG, PLA+…) |
| `family` | `finish` | "Matte"/"Silk"… ; `glossy`/ausente → em branco |
| `color_hex` | `#` + `color_hex` | |
| `diameter_mm` | `diameter` | só preenche se casar com 1.75/2.85 |
| `notes` | `name` (nome da cor) | só se as Notas estiverem vazias |
