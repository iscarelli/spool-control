# Niimbot — memória de trabalho / handoff

> Estado consolidado para retomar o desenvolvimento em **qualquer máquina**.
> Última atualização: **2026-06-03**. Doc de uso (separado): [`docs/niimbot.md`](niimbot.md).

## O que foi feito

Impressão de etiquetas **direto do navegador** numa **Niimbot B1 Pro** (300 dpi,
protocolo V4) — sem app intermediário, via **Web Bluetooth**. Validado em hardware
real (funcionou). Botão **Imprimir Niimbot** no detalhe do spool e na fila de
etiquetas, ao lado do PDF (que continua intacto).

## Versões / estado

| Item | Valor |
|---|---|
| Versão em produção | **v1.11.1** (deployada e verificada) |
| Release no GitHub | `v1.11.1` (Latest) |
| Produção | https://spool.lojinharacer.com.br (LXC 117 / 10.1.0.29) |
| Feature introduzida em | v1.11.0 · linha divisória engrossada em v1.11.1 |

## Dois repositórios (relação upstream ↔ vendor)

| Repo | Visibilidade | Papel |
|---|---|---|
| **iscarelli/spool-control** | público | App. Integra a impressão (rotas, templates, render PNG) + **cópia vendorada** do driver. |
| **iscarelli/niimbot** (`../niimbot`) | **privado** | **Upstream** do driver: `src/niimbot.js`, `docs/protocol-v4.md`, `registry.json`, `demo/index.html`. |

**Por que vendorar:** o deploy clona o repo **público anonimamente** no servidor,
então o repo privado não pode ser puxado lá — o driver precisa estar versionado
dentro do spool-control. `static/niimbot.js` é cópia verbatim de
`../niimbot/src/niimbot.js` (só o cabeçalho difere, marcando "VENDORADO").

## Mapa de arquivos (spool-control)

| Arquivo | Papel |
|---|---|
| `labels.py` → `generate_label_png()` | Renderiza etiqueta **PNG 1-bit** (PIL): QR + marca/material/família/ID. |
| `niimbot_registry.py` | Registro de modelos/tamanhos (espelha `../niimbot/registry.json`). |
| `app.py` | Rotas `GET /spools/<id>/label.png` e `GET /api/niimbot/registry`. Settings salvam `niimbot_model` / `niimbot_label_size`. |
| `static/niimbot.js` | Driver Web Bluetooth **vendorado** — não editar aqui. |
| `static/niimbot-spool.js` | Adaptador deste app: busca o registro + liga os botões. |
| `templates/spools/detail.html` | Botão "Imprimir Niimbot" (`data-niimbot-url`) + carrega os 2 scripts. |
| `templates/reports/label_queue.html` | Botão de fila (`data-niimbot-urls`, JSON) + os 2 scripts. |
| `templates/admin/settings.html` | Selects de modelo + tamanho. |
| `deploy/update-lxc.sh` | **Já corrigido** p/ copiar `niimbot_registry.py` (linha de cp). |

## Protocolo V4 (resumo — detalhes em `../niimbot/docs/protocol-v4.md`)

- **BLE:** Service `e7810a71-73ae-499d-8c15-faa9aef0c3f2`, Characteristic
  `bef8d6c9-9c21-4c9e-b632-bd58c1009f9f`. Conexão inicial: `03 55 55 C1 01 01 C1 AA AA`.
- **Frame:** `[55 55 cmd len ...data crc AA AA]`, `crc = cmd ^ len ^ data`.
- **Fluxo:** SetDensity(0x21→0x31) → SetLabelType(0x23→0x33) → PrintStart(0x01→0x02)
  → PrintStatus(0xA3 one-way) → SetPageSize(0x13→0x14) → linhas (0x84 vazia /
  0x85 com pixels, run-length) → 0xE3→0xE4 → **poll 0xA3→0xB3 até page≥1** →
  PrintEnd(0xF3→0xF4).
- **Crítico:** sem o poll antes do PrintEnd, a etiqueta sai cortada no meio.
- **T50×30 @ 300 dpi:** 584×354 px, stride 73, MSB-first, 1=preto, sem dithering
  (threshold luminância < 128).

## Como testar

1. **Chrome/Edge** em **HTTPS** (produção) ou `localhost` — Web Bluetooth não
   existe em Firefox/Safari.
2. Ligar a B1 Pro, etiqueta 50×30 carregada.
3. Detalhe do spool ou Fila → **Imprimir Niimbot** → parear (nome começa com `B1`).
4. Console (F12) loga handshake + status do poll. Etiqueta deve sair completa.

## Gotchas / requisitos de ambiente

- **Servidor precisa de `fonts-dejavu-core`** (já instalado no LXC 117) — senão o
  texto da etiqueta cai num fallback feio.
- O `update-lxc.sh` instalado no servidor já é a versão que copia
  `niimbot_registry.py` (resolvido o ovo-galinha do 1º deploy).
- **Deploy** (CLI, padrão): `ssh -i ~/.ssh/claude_proxmox claude@10.1.0.16
  "sudo /usr/sbin/pct exec 117 -- bash /opt/spool-control/deploy/update-lxc.sh"`.
  `10.1.0.16` é o **nó Proxmox** (ponte); o app roda no **LXC 117**.

## Manutenção

- **Re-sincronizar o driver:** ao mudar o protocolo no repo privado,
  `cp ../niimbot/src/niimbot.js static/niimbot.js` e recolocar o cabeçalho
  "VENDORADO". Refletir mudanças de `registry.json` em `niimbot_registry.py`.
- **Novo modelo/tamanho:** editar `../niimbot/registry.json` (canônico) →
  espelhar em `niimbot_registry.py`. Se o protocolo diferir do V4, adicionar ramo
  no driver e re-sincronizar.

## Pendências / próximos passos (niimbot)

- Trabalhar no repo `../niimbot` (refinos do driver, demo, mais modelos/tamanhos).
- Avaliar suporte a outros modelos (203 dpi: B1/B21/D110) — variante de protocolo.
- (Opcional) Tornar o registro Python um loader de `registry.json` para eliminar a
  duplicação manual entre os dois repos.
