# Estudo: Estação de pesagem autônoma (ESP32 + leitor serial GM861-LED)

> **Status:** estudo (não implementado). Aguardando compra do hardware (GM861-LED + ESP32).
> Última atualização: 2026-06-02.

## Contexto

Hoje a pesagem de spools é manual: o operador abre `/weigh` (ou `/spools/<id>/weigh`)
no navegador, escaneia/digita o código e digita o peso. A meta é uma **estação física
autônoma**: o operador apenas **apoia o spool na balança**. A presença de peso dispara
a leitura do QR pelo leitor serial; o ESP32 extrai o `spool_id`, espera o peso
estabilizar e faz um `POST` ao Flask, que registra a pesagem. Sem tocar no computador.

O QR é gerado em `labels.py:35` (`{app_base_url}/spools/{id}`). Formato definido: **URL pública
por inteiro (domínio `spool.lojinharacer.com.br`) + ECC maior** (ver seção *QR / etiqueta*).

> **Decisão de hardware (confirmada):** leitor **GM861-LED** — rosca M25 (montagem
> rígida trivial num gabinete), 3,3V (liga direto no ESP32, sem level shifter) e luz de
> preenchimento que ajuda a ler etiqueta brilhante. Acionado por **Command Triggered
> Mode** (comando serial), não por câmera.

---

## Hardware

| Componente | Modelo | Observação |
|---|---|---|
| Microcontrolador | **ESP32 DevKit (WROOM)** | UART livre + GPIOs de sobra; sem restrição da ESP32-CAM |
| Leitor de QR | **GM861-LED** | Serial TTL 3,3V @9600 8N1, rosca M25, luz de preenchimento |
| Amplificador ADC | **HX711** | 24-bit, para a célula de carga |
| Célula de carga | **TAL220B 5kg** | 4 fios → HX711 |
| Display (opcional) | **SSD1306 OLED 0.96" I²C** | Feedback visual ao operador |

### Ligações (ESP32 WROOM)

| Periférico | Sinal | GPIO ESP32 | Obs. |
|---|---|---|---|
| GM861-LED | VCC / GND | 3V3 / GND | módulo é 3,3V — sem level shifter |
| GM861-LED | módulo TXD → ESP32 **RX2** | GPIO16 | UART2 |
| GM861-LED | módulo RXD ← ESP32 **TX2** | GPIO17 | UART2 |
| HX711 | DT / SCK | GPIO32 / GPIO33 | bit-bang via lib `HX711` |
| OLED | SDA / SCL | GPIO21 / GPIO22 | I²C padrão |

> UART0 (GPIO1/3, USB) fica livre para debug; o GM861 fica isolado na **UART2**.
> Pinos 5 (D-) e 6 (D+) do conector do GM861 são USB — **não usar**; ligar só TTL.

---

## QR / etiqueta (decidido: URL + ECC, base = domínio público)

O firmware só precisa do `spool_id`. Há um trade-off entre **uso humano** (escanear com
o celular abre a página do spool) e **confiabilidade do leitor** (payload mais curto =
QR com menos módulos = módulos maiores no mesmo tamanho físico = leitura mais robusta a
distância/curvatura/brilho).

| Opção de payload | Celular abre página? | QR no leitor | Parsing no ESP32 |
|---|---|---|---|
| **URL completa** (atual) `https://spool.lojinharacer.com.br/spools/42` | ✅ | mais denso | regex `/spools/(\d+)` |
| **ID puro** `42` | ❌ | mais robusto | `atoi` direto |
| **Prefixado** `SP42` / `s/42` | ❌ | robusto | tira o prefixo |

**Decisão (confirmada):** o QR usa a **URL pública por inteiro** — base
**`https://spool.lojinharacer.com.br`** (o domínio, nunca o IP interno nem `localhost`,
senão o celular não abre o spool) — e **ECC** subido para M/Q. Custo de parsing no ESP32 é nulo.

> ⚠️ **O default atual está errado pra esse uso:** `app_base_url` vem como
> `http://localhost:5000` (`database.py:102`). "Trocar a URL do QR como um todo" =
> garantir que `app_base_url` em **produção** seja `https://spool.lojinharacer.com.br`
> (setting editável em `/admin/settings`, `app.py:718`); opcionalmente trocar também o
> **default** em `database.py:102` pra nunca cair em localhost. *(O caminho `/spools/<id>`
> permanece — só a base muda.)*

> **Endereço (decidido):** o **QR** e o **POST da estação** usam o mesmo domínio público
> `https://spool.lojinharacer.com.br` (via Traefik). Implicações no ESP32:
> - `WiFiClientSecure` + `HTTPClient` em HTTPS;
> - na traga inicial, `client.setInsecure()` (pula validação de cert); em produção, *pin* da
>   CA **Let's Encrypt ISRG Root X1** via `setCACert()` (válida até ~2035);
> - ✅ **reachability na LAN (confirmado):** a rede tem **split-DNS/hairpin**, então
>   `spool.lojinharacer.com.br` resolve pro Traefik (`10.1.0.15`) de dentro da LAN e o HTTPS
>   funciona na estação. (*Fallback* só se um dia faltar: `SERVER` = `http://10.1.0.29:8001`,
>   HTTP direto no Gunicorn, sem TLS.)

> ⚠️ **Parsing robusto:** o ESP32 deve casar `/spools/(\d+)` **ancorado**, não "o primeiro
> número da string". (A rota `/weigh` atual usa `re.search(r'\d+', code)` em `app.py:492`,
> que pegaria `10` numa base_url tipo `http://10.1.0.29:5000`. O firmware não deve repetir
> esse atalho.)

---

## Parte 1 — Flask: endpoint de API JSON

Sem mudanças em `database.py`. Reaproveitar o que já existe:
- `db.get_spool(spool_id)` (`database.py:413`) — já devolve `brand`, `material`,
  `family`, `effective_tare_g`, `nominal_weight_g`, `current_net_g`, `last_weighed_at`.
- `db.add_weight_reading(spool_id, gross_weight_g, tare_weight_g, recorded_by, notes)`
  (`database.py:473`).
- `db.get_setting(key, default)` (`database.py:185`) para ler a chave de API.

A lógica espelha a rota existente `/weigh` (`app.py:487`) — incluindo a validação
`gross < tare` — mas responde **JSON** e autentica por **API key** em vez de sessão.

### Nova rota: `POST /api/weigh` (em `app.py`)

```
Headers: Content-Type: application/json
         X-API-Key: <chave>

Body: { "spool_id": 42, "gross_weight_g": 347.5 }

200: {
  "ok": true,
  "spool_id": 42,
  "filament": "eSUN PLA+ Vermelho",   // f"{brand} {material} {family}"
  "gross_weight_g": 347.5,
  "tare_g": 185.0,                     // effective_tare_g
  "net_weight_g": 162.5,
  "nominal_weight_g": 1000.0,
  "remaining_pct": 16.25
}

4xx: { "ok": false, "error": "mensagem" }   // 401 chave, 404 spool, 422 gross<tare
```

### Rota opcional: `GET /api/spools/<id>`
Devolve `filament`, `effective_tare_g`, `nominal_weight_g`, `current_net_g`,
`last_weighed_at` — para o OLED mostrar o spool **antes** de gravar (confirmação visual).

### Detalhes de implementação (`app.py`)
- Ler a chave de `os.environ.get("SPOOL_API_KEY", "")`. Se vazia, aceitar sem auth
  (facilita dev local). Alternativa: guardar como setting via `set_setting`/`get_setting`.
- `recorded_by="estação"` (distingue no histórico das pesagens manuais).
- `nominal_weight_g` pode ser `None`/0 → proteger o cálculo de `remaining_pct`.
- **Não** usar `@login_required` (é máquina-a-máquina, autentica por chave).

---

## Parte 2 — Firmware ESP32 (a balança é o gatilho)

### Bibliotecas
`WiFi.h`, `WiFiClientSecure.h`, `HTTPClient.h`, `ArduinoJson`, `bogde/HX711`,
`Adafruit_SSD1306` (opcional). Leitor GM861: **nenhuma lib** — é UART pura (`Serial2`).

### Configurar o GM861-LED uma única vez
Por padrão o módulo pode vir em modo automático/contínuo. Configurá-lo para
**Command Triggered Mode** (manual §3.4) — escaneando o **código de configuração** do
manual ou enviando o comando de setup. A partir daí, cada leitura é disparada por:

```
Trigger 1 leitura:  7E 00 08 01 00 02 01 AB CD
Resposta do módulo: 02 00 00 01 00 33 31   (ack, então escaneia e devolve o payload)
```

### Máquina de estados (loop principal)

```
BOOT → conecta WiFi → HX711.tare() (zera a balança vazia)

ESTADO IDLE:
  - lê HX711 (média de ~10 amostras)
  - se peso > LIMIAR (ex.: 50g)  → debounce ~300ms → estado LENDO_QR

ESTADO LENDO_QR:
  - envia 7E 00 08 01 00 02 01 AB CD na Serial2
  - aguarda payload até timeout 10s
  - extrai spool_id (regex ancorado em "/spools/(\d+)" — ver seção QR)
  - falhou? → OLED "QR não lido" → AGUARDA_REMOÇÃO

ESTADO PESANDO:
  - aguarda estabilidade: |amostra - média| ≤ 2g por 500ms
  - gross_weight_g = média estável

ESTADO ENVIANDO:
  - HTTPS POST /api/weigh { spool_id, gross_weight_g } + header X-API-Key (via Traefik)
  - OLED mostra "PLA+ Vermelho / 162.5g (16%)" a partir da resposta
  - erro de rede/TLS → OLED "Falha rede" → retry 1x

ESTADO AGUARDA_REMOÇÃO:
  - espera peso < LIMIAR (spool retirado) → volta a IDLE
  - (evita re-disparar no mesmo spool)
```

### Config do firmware (hardcoded ou NVS)
```cpp
const char* WIFI_SSID = "...";
const char* WIFI_PASS = "...";
const char* SERVER    = "https://spool.lojinharacer.com.br";   // POST via Traefik (HTTPS). Fallback LAN: http://10.1.0.29:8001
const char* API_KEY   = "...";
const float LIMIAR_G  = 50.0;
float SCALE_FACTOR    = 2280.0;   // calibrar com peso conhecido
```

---

## Ordem de implementação

1. ~~**QR** — subir o ECC em `labels.py` (mantendo a URL `app_base_url` = domínio público).~~ ✅ **feito em v1.2.1** — `ERROR_CORRECT_M` → `ERROR_CORRECT_Q`
2. ~~**Flask** — adicionar `POST /api/weigh` (+ `GET /api/spools/<id>`) em `app.py`.~~ ✅ **implementado** — isento de CSRF, auth por `X-API-Key`==`SPOOL_API_KEY`, `recorded_by="estação"`; 400/401/404/422. **URL pública garantida na instalação:** `public_base_url()` (env `APP_BASE_URL` quando a setting está vazia/localhost) + seed da setting a partir do env + `setup-inside.sh`/`proxmox-deploy.sh` sem default de domínio de terceiros (sem domínio → IP interno, com aviso de "rede local apenas") + `SPOOL_API_KEY` gerado no `spool.env`. Validação sem hardware: `tools/validate_qr_autoweigh.py`.
3. **Testar a API** via `curl` antes de tocar no hardware.
4. **ESP32** — montar HX711 + célula, calibrar (`SCALE_FACTOR`), validar leitura de peso.
5. **ESP32** — ligar GM861 na UART2, pôr em Command Triggered Mode, testar trigger+leitura.
6. **ESP32** — juntar tudo na máquina de estados; testar com etiqueta impressa real.
7. **Deploy** — `SPOOL_API_KEY` no `spool.env` do servidor + redeploy via `update-lxc.sh`.

---

## Verificação

- **API pelo domínio** (mesmo caminho do ESP32 — valida Traefik + TLS + API):
  ```bash
  curl -X POST https://spool.lojinharacer.com.br/api/weigh \
    -H "Content-Type: application/json" -H "X-API-Key: <key>" \
    -d '{"spool_id":1,"gross_weight_g":350}'
  ```
  → JSON com `net_weight_g` e `remaining_pct`; chave errada → 401; spool inexistente → 404.
- **Direto no app** (isola o Traefik): trocar a URL por `http://10.1.0.29:8001/api/weigh`
  (Gunicorn; dev local `app.run` usa `:5000`).
- **Reachability da estação:** de um device na LAN, `curl https://spool.lojinharacer.com.br/health`
  deve responder — confirma NAT hairpin/split-DNS (senão usar o fallback IP interno).
- **Persistência:** abrir o spool no browser → o histórico mostra a leitura com
  `recorded_by = "estação"`.
- **Trigger pela balança:** apoiar o spool → leitor dispara sozinho, OLED confirma, e a
  pesagem aparece no histórico sem nenhuma interação no PC.
- **Leitura do QR:** etiqueta impressa real lida pelo GM861-LED a ~5–25cm.

---

## Arquivos a modificar

| Arquivo | O que muda |
|---|---|
| `app.py` | +2 rotas de API JSON (`/api/weigh`, `/api/spools/<id>`); reusa helpers existentes |
| `labels.py` | subir o ECC do QR (mantendo a URL com domínio público) — ver seção QR |
| `database.py` | *(opcional)* default de `app_base_url` (`:102`) de `localhost` → domínio |
| produção (`/admin/settings`) | garantir `app_base_url = https://spool.lojinharacer.com.br` |
| `spool.env` (servidor) | +`SPOOL_API_KEY=<gerada>` |
| **firmware** (fora do repo Flask) | novo `esp32-estacao/estacao.ino`; POST HTTPS via `WiFiClientSecure` |

> Os *helpers* de `database.py` (`get_spool`, `add_weight_reading`) **não** mudam — já
> bastam. A única mexida possível ali é o default de `app_base_url` (opcional, `:102`).

---

## Manuais de referência (na pasta `docs/`)

- `GM861 GM861-LED Barcode reader module User Manual-V1.2.4.pdf`
- `GM861S GM861S-LED Barcode reader module User Manual-V1.2.4.pdf`
- `GM861XS Barcode reader module User Manual-V1.1.2.pdf`
- `GM861XS-0 Barcode reader module User Manual-V1.1.2.pdf`

> Todos os quatro suportam trigger por hardware (§3.3.1, Level/Edge) **e** por comando serial
> (§3.4, *Command Triggered Mode*). O **GM861-LED** foi o escolhido pela montagem M25 + 3,3V +
> luz de preenchimento.
