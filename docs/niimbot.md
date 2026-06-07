# Impressão direta Niimbot (Web Bluetooth)

Impressão de etiquetas **direto do navegador** numa Niimbot, sem app intermediário.
Disponível desde a **v1.11.0**. Modelos suportados:

| Modelo | Task / protocolo | DPI | Status |
|---|---|---|---|
| **B1 Pro** | `v4` | 300 | validado em hardware |
| **B1** (e B1 SE) | `b1` (protocolo 3) | 203 | validado em hardware |
| M2-H | `b1` | 300 | *não validado* — oculto até confirmar (ver abaixo) |

A impressora é **identificada automaticamente** na conexão (B1 e B1 Pro anunciam o
mesmo nome BLE). O usuário escolhe só o **tamanho físico** da etiqueta (50 × 30 mm);
o app resolve internamente o modelo e a resolução (DPI) certos conforme a impressora
detectada — não há seleção manual de modelo nem de variante de pixel.

## Onde mora o quê

O **driver do protocolo** e a engenharia reversa vivem num projeto dedicado e
**público**: **[iscarelli/niimbot-web-bluetooth]** (pasta local `../niimbot-web-bluetooth`).
Lá estão o driver genérico (`src/niimbot.js`), a doc do protocolo (`docs/protocol-v4.md`),
o registro canônico (`registry.json`) e uma demo standalone.

Este projeto (spool-control) é **público** e o servidor de produção o clona
**anonimamente** — logo, o driver precisa morar neste repositório. A solução: o
spool-control **vendora** (mantém uma cópia *fixada numa tag*) do driver **e** do
registro, e adiciona só a cola específica do app. Não há download em runtime nem CDN
— o que está no git é o que roda (compatível com o deploy à prova de falhas, o CSP e
a LXC offline).

| Arquivo (spool-control) | Papel |
|---|---|
| `static/niimbot.js` | **Cópia vendorada** do driver. Não editar — atualizar via script. |
| `niimbot_registry.json` | **Cópia vendorada** do `registry.json` upstream (modelos + tamanhos). Fonte única. |
| `niimbot_registry.py` | **Carrega** o JSON acima; oculta entradas `_untested`; expõe `PRINTER_MODELS`, `LABEL_SIZES`, defaults e helpers às rotas. |
| `static/niimbot-spool.js` | Adaptador deste app: busca o registro e liga os botões da UI. |
| `labels.py` → `generate_label_png()` | Renderiza a etiqueta 1-bit (PNG) no tamanho de pixels do modelo escolhido. |
| Rotas em `app.py` | `GET /spools/<id>/label.png` e `GET /api/niimbot/registry`. |
| Configurações (admin) | Seleção de modelo e tamanho (`niimbot_model`, `niimbot_label_size`). |
| `deploy/vendor-niimbot.sh` | Atualiza as duas cópias vendoradas a partir de uma tag fixa. |

> JS e Python compartilham **um único** arquivo de registro (`niimbot_registry.json`):
> não há mais espelhamento manual entre `registry.json` e o Python — os dois vêm da
> mesma tag, sincronizados pelo script.

## Como funciona (fim a fim)

1. O servidor renderiza a etiqueta como **PNG 1-bit** em `/spools/<id>/label.png`
   (QR + marca/material/família/ID), no tamanho de pixels do modelo selecionado.
2. O botão **Imprimir Niimbot** (detalhe do spool e fila) chama o adaptador, que
   **identifica a impressora** (`Niimbot.identify`), resolve o modelo (por `id`/`task`)
   e a variante de pixel (mesmo tamanho físico, DPI da impressora) a partir do
   `/api/niimbot/registry`, e pede o `label.png` na resolução resolvida (`?size=`).
3. O driver (`static/niimbot.js`) conecta por Web Bluetooth, faz o threshold do PNG
   para 1-bit e envia pela variante de task certa (`v4` para B1 Pro, `b1` para B1) —
   ver `../niimbot-web-bluetooth/docs/protocol-v4.md`. As mensagens visíveis vêm
   traduzidas do servidor (campo `i18n` do registro); o driver é só em inglês.

## Requisitos

- **Chrome ou Edge** em **HTTPS** (produção) ou `localhost`. Web Bluetooth não existe
  em Firefox/Safari — o botão fica desabilitado com aviso.
- Fonte `fonts-dejavu-core` no servidor (para o texto da etiqueta ficar nítido).

## Re-sincronizar o driver com o upstream (pinned + scripted)

A atualização é **deliberada e reproduzível** — um comando, fixado numa tag:

```bash
deploy/vendor-niimbot.sh            # última release publicada
deploy/vendor-niimbot.sh v1.2.0     # uma tag específica
```

O script baixa `src/niimbot.js` + `registry.json` da tag escolhida, carimba o
tag/commit de origem nos dois e os grava em `static/niimbot.js` e
`niimbot_registry.json`. Depois: revisar `git diff`, **bump de versão + CHANGELOG**,
commit e deploy normal. (Requer `curl` e `python3`.)

## Adicionar um modelo ou tamanho

1. No upstream `registry.json` (canônico) — incluindo o campo `task` (`v4`/`b1`) e,
   se for um protocolo novo, o ramo correspondente em `src/niimbot.js`.
2. Rode `deploy/vendor-niimbot.sh` — re-vendora driver + registro juntos.
3. Os dropdowns e o endpoint de bitmap passam a oferecer o novo modelo/tamanho
   automaticamente (sem editar `niimbot_registry.py`).

### Liberar um modelo `_untested` (ex.: M2-H)

Entradas com a chave `_untested` no JSON são **ocultadas** por `niimbot_registry.py`
(não aparecem nos dropdowns nem na API). Para liberar: valide no hardware (confirme o
`name_prefix` BLE e os pixels reais), remova a chave `_untested` no `registry.json`
upstream e re-vendore.

[iscarelli/niimbot-web-bluetooth]: https://github.com/iscarelli/niimbot-web-bluetooth
