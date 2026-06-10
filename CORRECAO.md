# Correção de preços corrompidos (bug pré-v1.33.0)

## Causa

O handler de `submit` do JavaScript em `spools/form.html` convertia o formato BR
"21,60" para "21.60" antes de enviar. A função `_parse_price` então removia o ponto
como separador de milhar e gravava 2160.0 em vez de 21.60.

Corrigido na v1.33.0: handler removido. Novos lançamentos gravam corretamente.
Os registros já gravados com valores errados precisam ser corrigidos manualmente.

---

## Script de correção

```python
#!/usr/bin/env python3
"""
fix_prices.py — corrige preços corrompidos pelo bug do decimal (pré v1.33.0)

O bug: "21,60" → JS convertia para "21.60" → _parse_price removia o ponto
como milhar → gravava 2160.0 em vez de 21.60.

Heurística de detecção: preços com casas decimais .0 (número inteiro) e
valor >= 100 são suspeitos. O script lista todos para revisão antes de
aplicar qualquer correção.

Uso:
  python fix_prices.py --db /opt/spool-control/data/spool.db   # listar
  python fix_prices.py --db /opt/spool-control/data/spool.db --apply  # corrigir
"""

import sqlite3
import argparse

def detect_corrupted(conn):
    cur = conn.execute("""
        SELECT s.id, s.name, f.brand, f.material, f.family,
               s.purchase_price
        FROM spools s
        JOIN filaments f ON s.filament_id = f.id
        WHERE s.purchase_price IS NOT NULL
          AND s.purchase_price > 0
        ORDER BY s.id
    """)
    suspects = []
    for row in cur.fetchall():
        sid, name, brand, material, family, price = row
        if price == int(price) and price >= 100:
            suspects.append({
                "id": sid,
                "spool": f"{name or '—'} ({material} — {brand} / {family})",
                "atual": price,
                "div_100": price / 100,
                "div_1000": price / 1000,
            })
    return suspects

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True, help="Caminho para spool.db")
    parser.add_argument("--apply", action="store_true",
                        help="Aplica as correções (sem isso só lista)")
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row

    suspects = detect_corrupted(conn)

    if not suspects:
        print("Nenhum preço suspeito encontrado.")
        conn.close()
        return

    print(f"{'ID':>4}  {'Spool':<45}  {'Atual':>12}  {'÷100':>10}  {'÷1000':>10}")
    print("-" * 90)
    for s in suspects:
        print(f"{s['id']:>4}  {s['spool']:<45}  "
              f"{s['atual']:>12.2f}  {s['div_100']:>10.2f}  {s['div_1000']:>10.2f}")

    if not args.apply:
        print(f"\n{len(suspects)} spool(s) suspeito(s). Revise acima.")
        print("Para corrigir interativamente, rode com --apply")
        conn.close()
        return

    print(f"\nCorreção interativa — pressione Enter para pular, d/D para ÷100, m/M para ÷1000,")
    print("ou digite o valor correto manualmente (ex: 97.00).")
    print()

    updates = []
    for s in suspects:
        resp = input(
            f"[{s['id']}] {s['spool']}\n"
            f"  Atual: {s['atual']:.2f}   [d] ÷100 = {s['div_100']:.2f}   "
            f"[m] ÷1000 = {s['div_1000']:.2f}\n"
            f"  Ação (Enter=pular / d / m / valor): "
        ).strip()

        if resp == "":
            print("  → pulado")
        elif resp.lower() == "d":
            updates.append((s["div_100"], s["id"]))
            print(f"  → será corrigido para {s['div_100']:.2f}")
        elif resp.lower() == "m":
            updates.append((s["div_1000"], s["id"]))
            print(f"  → será corrigido para {s['div_1000']:.2f}")
        else:
            try:
                val = float(resp)
                updates.append((val, s["id"]))
                print(f"  → será corrigido para {val:.2f}")
            except ValueError:
                print("  → valor inválido, pulado")
        print()

    if not updates:
        print("Nenhuma alteração a aplicar.")
        conn.close()
        return

    print(f"\nAplicando {len(updates)} correção(ões)...")
    with conn:
        for val, sid in updates:
            conn.execute(
                "UPDATE spools SET purchase_price = ? WHERE id = ?",
                (val, sid)
            )
    print("Concluído. Recomendado rodar VACUUM/checkpoint:")
    print("  sqlite3 spool.db 'PRAGMA wal_checkpoint(TRUNCATE); VACUUM;'")
    conn.close()

if __name__ == "__main__":
    main()
```

---

## Como usar em produção

### 1. Copiar o script para o LXC

```bash
scp -i ~/.ssh/claude_proxmox CORRECAO.md claude@10.1.0.16:/tmp/fix_prices.py
# ou extraia o bloco Python acima para um arquivo fix_prices.py local, depois:
scp -i ~/.ssh/claude_proxmox fix_prices.py claude@10.1.0.16:/tmp/
ssh -i ~/.ssh/claude_proxmox claude@10.1.0.16 \
  "sudo /usr/sbin/pct push 117 /tmp/fix_prices.py /tmp/fix_prices.py"
```

### 2. Listar suspeitos (só leitura, sem alterar nada)

```bash
ssh -i ~/.ssh/claude_proxmox claude@10.1.0.16 \
  "sudo /usr/sbin/pct exec 117 -- python3 /tmp/fix_prices.py \
   --db /opt/spool-control/data/spool.db"
```

### 3. Corrigir interativamente

```bash
ssh -i ~/.ssh/claude_proxmox claude@10.1.0.16 -t \
  "sudo /usr/sbin/pct exec 117 -- python3 /tmp/fix_prices.py \
   --db /opt/spool-control/data/spool.db --apply"
```

Para cada spool suspeito o script mostra o valor atual e as duas sugestões de correção:

| Tecla | Ação |
|---|---|
| Enter | Pula (não altera) |
| `d` | Divide por 100 — caso mais comum ("97,00" → 9700 → corrige para 97.00) |
| `m` | Divide por 1000 — se o original tinha separador de milhar ("1.234,56" → 1234560 → corrige para 1234.56) |
| valor | Digite o número correto manualmente (ex: `97.00`) |

### 4. Checkpoint após a correção (opcional mas recomendado)

```bash
ssh -i ~/.ssh/claude_proxmox claude@10.1.0.16 \
  "sudo /usr/sbin/pct exec 117 -- sqlite3 /opt/spool-control/data/spool.db \
   'PRAGMA wal_checkpoint(TRUNCATE); VACUUM;'"
```
