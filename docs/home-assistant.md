# Integração com o Home Assistant

O Spool Control expõe endpoints **somente leitura** para o Home Assistant (HA) acompanhar o
estoque de filamentos: total em kg, quantos rolos estão acabando, quebra por material/local e
detalhe de cada rolo. A integração usa a plataforma **REST nativa** do HA (polling) — **sem MQTT,
sem add-on, sem custom component**.

## 1. Pegue a chave de API do Home Assistant

No Spool Control, vá em **Admin → Integrações**. No cartão **Home Assistant**:

1. Clique no olho 👁 para **revelar** a chave e no clipe 📋 para **copiá-la**.
2. A chave do HA é **somente leitura** — ela consulta o estoque, mas **não** consegue gravar
   pesagens (isso é exclusivo da chave da balança). As duas chaves são independentes: gerar uma
   nova chave do HA **não** afeta a balança.

> Trocou a chave por engano ou quer rotacionar? Clique em **Gerar nova chave** — basta atualizar o
> `secrets.yaml` (passo 2) com a chave nova.

## 2. Guarde a chave no `secrets.yaml`

No diretório de configuração do HA, em `secrets.yaml`:

```yaml
spool_api_key: "COLE_A_CHAVE_AQUI"
```

## 3. Endpoints disponíveis

Substitua `https://spool.example.com` pela URL do seu Spool Control (a mesma de **Admin →
Integrações**). Todos exigem o cabeçalho `X-API-Key`.

| Endpoint | O que retorna |
|---|---|
| `GET /api/summary` | Totais (rolos ativos, filamentos, **peso líquido em g e kg**, nominal), contagem de estoque baixo e quebra por material |
| `GET /api/low-stock` | Lista dos rolos abaixo do limite configurado (o que está acabando) |
| `GET /api/stock` | Estoque agregado por material **e** por local |
| `GET /api/spools/<id>` | Detalhe de um rolo específico |

Exemplo de teste no terminal:

```bash
curl -H "X-API-Key: COLE_A_CHAVE_AQUI" https://spool.example.com/api/summary | jq
```

```json
{
  "ok": true,
  "generated_at": "2026-06-08T15:00:00Z",
  "totals": { "active_spools": 42, "filaments": 18,
              "net_weight_g": 31850, "net_weight_kg": 31.85, "nominal_weight_g": 42000 },
  "low_stock": { "count": 5, "threshold_g": 200, "threshold_pct": 20 },
  "by_material": [ { "material": "PLA", "spool_count": 20, "net_weight_g": 15000 } ]
}
```

## 4. Configure os sensores (`configuration.yaml`)

Adicione ao `configuration.yaml` (ou a um pacote/`!include`):

```yaml
rest:
  # Visão geral — um poll vira vários sensores
  - resource: https://spool.example.com/api/summary
    scan_interval: 300            # a cada 5 min (estoque muda devagar)
    headers:
      X-API-Key: !secret spool_api_key
    sensor:
      - name: "Filamento — estoque total"
        unique_id: spool_total_kg
        value_template: "{{ value_json.totals.net_weight_kg }}"
        unit_of_measurement: "kg"
        state_class: measurement
        icon: mdi:printer-3d-nozzle
      - name: "Filamento — rolos ativos"
        unique_id: spool_active_spools
        value_template: "{{ value_json.totals.active_spools }}"
        state_class: measurement
      - name: "Filamento — estoque baixo (qtd)"
        unique_id: spool_low_stock_count
        value_template: "{{ value_json.low_stock.count }}"
        state_class: measurement
        icon: mdi:alert

  # Lista do que está acabando — o estado é a contagem; a lista vai nos atributos
  - resource: https://spool.example.com/api/low-stock
    scan_interval: 600
    headers:
      X-API-Key: !secret spool_api_key
    sensor:
      - name: "Filamentos acabando"
        unique_id: spool_low_stock_list
        value_template: "{{ value_json.count }}"
        json_attributes:
          - spools
          - threshold_g
          - threshold_pct
```

Após salvar, **reinicie o HA** (ou use *Developer Tools → YAML → Restart*). Os sensores aparecem
como `sensor.filamento_estoque_total`, `sensor.filamentos_acabando`, etc.

> **Sensor por material (opcional):** como `by_material` é uma lista, crie um *template sensor* a
> partir do `sensor.filamento_estoque_total` (que pode carregar os atributos) ou exponha o que
> precisar via `value_template` filtrando pela lista. Para a maioria dos casos os sensores acima já
> bastam.

## 5. Exemplo de automação — avisar quando algo estiver acabando

```yaml
automation:
  - alias: "Filamento acabando — notificar"
    trigger:
      - platform: numeric_state
        entity_id: sensor.filamentos_acabando
        above: 0
    action:
      - service: notify.notify
        data:
          title: "Estoque de filamento baixo"
          message: >
            {{ states('sensor.filamentos_acabando') }} rolo(s) abaixo do limite:
            {% for s in state_attr('sensor.filamentos_acabando', 'spools') %}
            {{ s.code }} {{ s.brand }} {{ s.material }} ({{ s.remaining_pct }}%){% if not loop.last %},{% endif %}
            {% endfor %}
```

Exemplo de card Lovelace (markdown) listando o que está acabando:

```yaml
type: markdown
content: >
  ### Filamentos acabando ({{ states('sensor.filamentos_acabando') }})
  {% for s in state_attr('sensor.filamentos_acabando', 'spools') %}
  - **{{ s.code }}** {{ s.brand }} {{ s.material }} — {{ s.net_weight_g }} g ({{ s.remaining_pct }}%) @ {{ s.location }}
  {% endfor %}
```

## Notas

- **HTTPS recomendado.** Use a URL pública (atrás do Traefik). Em rede local sem HTTPS, o HA também
  consegue consultar `http://IP:8001`, mas a chave trafega em claro — prefira HTTPS.
- **Limite de estoque baixo** vem de **Admin → Configurações** (gramas e %); os endpoints já
  refletem esses valores em `threshold_g`/`threshold_pct`.
- **Segurança:** a chave do HA é read-only. Se vazar, gere uma nova em **Admin → Integrações** e
  atualize o `secrets.yaml` — a balança continua funcionando normalmente.
- **Escrita** (registrar pesagem) **não** é feita pelo HA — isso é a API da balança/estação
  (`POST /api/weigh`, chave de escopo write). Ver `docs/estudo_balanca_qrcode.md`.
