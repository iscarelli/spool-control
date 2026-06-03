# Impressão direta Niimbot (Web Bluetooth)

Impressão de etiquetas **direto do navegador** numa **Niimbot B1 Pro** (300 dpi,
protocolo V4), sem app intermediário. Disponível desde a **v1.11.0**.

## Onde mora o quê

O **driver do protocolo** e o conhecimento de engenharia reversa vivem num
projeto dedicado e **privado**: **[iscarelli/niimbot]** (pasta local `../niimbot`).
Lá estão o driver genérico (`src/niimbot.js`), a documentação completa do
protocolo V4 (`docs/protocol-v4.md`), o registro canônico (`registry.json`) e uma
demo standalone.

Este projeto (spool-control) é **público** e o servidor de produção o clona
**anonimamente** — por isso não dá para puxar o repo privado no deploy. A
solução: o spool-control **vendora** (mantém uma cópia) do driver e adiciona só a
cola específica do app.

| Arquivo (spool-control) | Papel |
|---|---|
| `static/niimbot.js` | **Cópia vendorada** do driver `../niimbot/src/niimbot.js`. Não editar aqui. |
| `static/niimbot-spool.js` | Adaptador deste app: busca o registro e liga os botões da UI. |
| `niimbot_registry.py` | Registro (Python) espelhando `../niimbot/registry.json`. Alimenta as rotas. |
| `labels.py` → `generate_label_png()` | Renderiza a etiqueta 1-bit (PNG) — layout do spool-control. |
| Rotas em `app.py` | `GET /spools/<id>/label.png` e `GET /api/niimbot/registry`. |
| Configurações (admin) | Seleção de modelo e tamanho (`niimbot_model`, `niimbot_label_size`). |

## Como funciona (fim a fim)

1. O servidor renderiza a etiqueta como **PNG 1-bit** em `/spools/<id>/label.png`
   (QR + marca/material/família/ID), no tamanho de pixels do modelo selecionado.
2. O botão **Imprimir Niimbot** (detalhe do spool e fila de etiquetas) chama o
   adaptador, que pega modelo/tamanho de `/api/niimbot/registry`.
3. O driver (`static/niimbot.js`) conecta por Web Bluetooth, faz o threshold do
   PNG para 1-bit e envia via protocolo V4 (ver `../niimbot/docs/protocol-v4.md`).

## Requisitos

- **Chrome ou Edge** em **HTTPS** (produção) ou `localhost`. Web Bluetooth não
  existe em Firefox/Safari — o botão fica desabilitado com aviso.
- Fonte `fonts-dejavu-core` no servidor (para o texto da etiqueta ficar nítido).

## Re-sincronizar o driver com o upstream

Ao mudar o protocolo no repo privado, atualize a cópia vendorada:

```bash
cp ../niimbot/src/niimbot.js static/niimbot.js   # e re-adicione o cabeçalho "VENDORADO"
```

Se mudar modelos/tamanhos em `../niimbot/registry.json`, reflita em
`niimbot_registry.py` (mesmas chaves). Depois: bump de versão + deploy normal.

## Adicionar um modelo ou tamanho

1. No upstream `../niimbot/registry.json` (canônico).
2. Espelhe em `niimbot_registry.py` (este repo).
3. Se o protocolo do modelo novo diferir do V4, adicione o ramo no driver
   (`../niimbot/src/niimbot.js`) e re-sincronize.

[iscarelli/niimbot]: https://github.com/iscarelli/niimbot
