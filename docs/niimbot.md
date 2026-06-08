# Impressão direta Niimbot (Web Bluetooth)

Impressão de etiquetas **direto do navegador** numa Niimbot, sem app intermediário.
Disponível desde a **v1.11.0**.

## Validado em hardware

Combinações de **modelo + tamanho** confirmadas imprimindo em impressora real:

| Modelo | model id | Task / protocolo | DPI | Tamanho | Pixels | Status |
|---|---|---|---|---|---|---|
| **Niimbot B1** (e B1 SE) | 4096 | `b1` (protocolo 3) | 203 | 50 × 30 mm | 384 × 240 | ✅ validado |
| **Niimbot B1 Pro** | 4097 | `v4` | 300 | 50 × 30 mm | 584 × 354 | ✅ validado |
| **Niimbot M2-H** | 4608 | `b1` | 300 | 50 × 30 mm | 567 × 354 | ✅ validado |

> **Apenas estes modelos são aceitos.** Na conexão, o app identifica o `model id` da
> impressora; se não for um dos validados acima, a impressão é **recusada com aviso**
> — para nunca imprimir errado numa Niimbot não suportada. Outros **tamanhos** de
> etiqueta além de 50 × 30 mm ainda não foram validados (no roadmap).

## Como o usuário usa

O seletor de impressora é **um item só** — **"Niimbot B1 / B1 Pro / M2-H"** (rótulo
gerado dos modelos validados) — e o usuário escolhe apenas o **tamanho físico** da
etiqueta. Na conexão, a impressora exata é **identificada automaticamente** (model id)
e o app resolve internamente o modelo e a resolução (DPI/pixels) certos — sem escolher
modelo nem variante. O filtro Bluetooth usa a **união** dos nomes anunciados (B1 + M2),
listando as Niimbot validadas; a confirmação final é pelo `model id`.

> A variante de pixel é escolhida pelo **modelo dono** (mapa `size_model`), não só
> pelo DPI: B1 Pro e M2-H são ambos 300 dpi mas com larguras diferentes (584 vs 567
> px), então o DPI sozinho não basta.

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
| Rotas em `routes/spools.py` | `GET /spools/<id>/label.png` e `GET /api/niimbot/registry`. |
| Configurações (admin) | Seleção de família de impressora e tamanho (`niimbot_printer_family`, `niimbot_label_size`). |
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
commit e deploy normal. (Requer `curl` e `python3`/`py`.)

## Adicionar um modelo ou tamanho

1. No upstream `registry.json` (canônico) — incluindo o campo `task` (`v4`/`b1`) e,
   se for um protocolo novo, o ramo correspondente em `src/niimbot.js`.
2. Rode `deploy/vendor-niimbot.sh` — re-vendora driver + registro juntos.
3. Os dropdowns e o endpoint de bitmap passam a oferecer o novo modelo/tamanho
   automaticamente (sem editar `niimbot_registry.py`).

### Entradas `_untested` — modelos vs. tamanhos

- **Modelos** com a chave `_untested` ficam **ocultos** (`niimbot_registry.py` só
  expõe os validados) — não viram família nem aparecem no seletor. Para liberar:
  valide no hardware, remova `_untested` do modelo no `registry.json` upstream,
  re-vendore.
- **Tamanhos** são tratados diferente: a variante de pixel **não é oferecida** ao
  usuário (é resolvida pelo modelo dono via `size_model`), então um `_untested` num
  *size* **não** o esconde da resolução — `LABEL_SIZES` inclui todas as variantes
  concretas; só o dropdown de tamanho **físico** usa as visíveis. Assim a M2-H
  funciona mesmo com `T50x30_m2h` ainda marcado `_untested` no upstream.

> **Pendência de limpeza:** no upstream v1.3.0 o **modelo** `m2h` já está validado
> (sem `_untested`, com `_note`), mas o **tamanho** `T50x30_m2h` ainda carrega
> `_untested` — provável resquício. Recomendado removê-lo no `registry.json` upstream
> e re-vendorar, para a documentação refletir que o tamanho também foi validado.

[iscarelli/niimbot-web-bluetooth]: https://github.com/iscarelli/niimbot-web-bluetooth
