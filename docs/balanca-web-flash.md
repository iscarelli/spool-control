# Gravar o firmware da balança pela web

A página **Admin → Estação de pesagem** (`/admin/scale`, só admin) grava o firmware da
balança (ESP32‑C3) direto do navegador, via **Web Serial + esptool‑js** — o irmão do
gravador Niimbot (Web Bluetooth). Sem instalar PlatformIO, sem app.

> **Escopo atual:** só **gravação** de um binário genérico. A configuração de Wi‑Fi, URL
> e chave de API (provisionamento) virá numa próxima versão (firmware com Wi‑Fi STA +
> `POST /api/weigh` + handshake serial‑JSON; ver roadmap no fim).

## Requisitos do usuário

- **Chrome ou Edge no computador** (Web Serial não existe em Safari/Firefox nem em
  celular).
- **Secure context:** HTTPS (produção atrás do Traefik) **ou** `http://localhost` no dev.
- A balança ligada por USB. No diálogo do navegador, escolher a porta serial da placa.

## Como funciona

- O firmware é compilado e gravado em **4 pedaços separados, cada um no seu offset** —
  exatamente como o `pio upload`: `bootloader 0x0 · partitions 0x8000 · boot_app0 0xe000
  · app 0x10000`. Os pedaços (`bootloader.bin`, `partitions.bin`, `boot_app0.bin`,
  `app.bin`) + o manifesto `static/firmware/balanca-c3.json` (offsets, sha256) ficam em
  `static/firmware/`.
- **Gravar pedaços separados (e não uma imagem "merged" única em 0x0) é o que funciona
  com o esptool-js.** Uma imagem única grande falha no meio (o esptool-js erra o cálculo
  de endereço de bloco). Além disso, o `data` de cada pedaço é passado como **`Uint8Array`**
  — passar uma "binary string" faz o pako expandir os bytes ≥ 0x80 como UTF‑8 e o stub
  rejeita o bloco final com `ESP_TOO_MUCH_DATA` (0xC9). É assim que o ESP Web Tools / ESPHome
  fazem. Validado em hardware (ESP32‑C3 SuperMini).
- Os artefatos são **versionados no git** e servidos como estáticos. O deploy é por clone
  público + `git archive`, então **o que está no git é o que o site serve** — não há build
  no servidor (preserva o deploy à prova de falhas).
- O driver `esptool-js` é **vendorado** em `static/esptool.js` (sem CDN, sem download em
  runtime); o adaptador `static/esp-flash.js` importa o driver como módulo, lê o manifesto,
  baixa os pedaços e grava cada um no seu offset. As mensagens visíveis são traduzidas no
  servidor.

## Atualizar o binário quando o firmware mudar

```bash
# 1) Compila o firmware (env balanca-c3) e gera os pedaços + manifesto:
bash deploy/build-firmware-bin.sh
#    → static/firmware/{bootloader,partitions,boot_app0,app}.bin + balanca-c3.json
# 2) Revise o git diff, committe os artefatos, bump VERSION + CHANGELOG.
```

Requer PlatformIO (`pio`) no PATH; o `esptool.py` vem com a plataforma espressif32
(chamado via `pio pkg exec`). Offsets ESP32‑C3 Arduino: bootloader `0x0`, partições
`0x8000`, boot_app0 `0xe000`, app `0x10000`.

## Atualizar o esptool‑js vendorado

```bash
deploy/vendor-esptool.sh            # versão pinada (0.6.0)
deploy/vendor-esptool.sh 0.6.1      # uma versão específica
```

Baixa o `bundle.js` (ESM único) da versão fixa para `static/esptool.js`, carimbando a
origem. Sem download em runtime/deploy.

## Testar

- **Local (hardware real):** rode o app em `http://localhost:5000` (secure context para
  Web Serial), plugue o ESP32‑C3, abra `/admin/scale` no Chrome/Edge → **Conectar e
  gravar** → confirme o boot no monitor serial (`pio device monitor -e balanca-c3`, 115200).
- **Rede / staging (sem afetar produção):** `git push` da branch e, numa **LXC separada**,
  `bash /opt/spool-control/deploy/update-lxc.sh --ref <branch>` (o script clona o repo
  público no ref dado e aplica a árvore). Acesse via HTTPS e repita o flash. **Não** mexa
  na LXC 117 (produção).
- **Testes automatizados:** `tests/test_scale_flash.py` cobre o gate admin, a entrega do
  binário/manifesto e a presença do adaptador no HTML.

## Notas

- O ESP32‑C3 SuperMini usa **USB‑Serial/JTAG** nativo; o esptool‑js grava os pedaços nos
  seus offsets sem precisar do botão BOOT.
- `platformio.ini` fixa `upload_port=COM23` — irrelevante para o flash web; só afeta o
  `pio upload` manual. A porta real aparece no diálogo do navegador.

## Roadmap (próxima fase — provisionamento)

1. Firmware: Wi‑Fi STA + cliente HTTP `POST /api/weigh` + leitura de config no NVS
   (`Preferences`).
2. Handshake **serial‑JSON pequeno** logo após o flash: o site envia SSID/senha + URL +
   chave de API (lida de Admin → Integrações, integração `scale`) pela mesma sessão Web
   Serial; o firmware grava no NVS.
3. Fallback **SoftAP captive portal** para configurar Wi‑Fi sem Web Serial.
