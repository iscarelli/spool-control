#!/usr/bin/env python3
r"""
Valida o QR da etiqueta para a PESAGEM AUTOMÁTICA (estação ESP32 + leitor serial),
sem precisar do hardware. Ver docs/estudo_balanca_qrcode.md.

O que ele garante:
  1. O QR é gerado com a MESMA função da etiqueta (labels._make_qr_image) usando a
     URL PÚBLICA (https://spool.lojinharacer.com.br/spools/<id>) — nunca IP privado.
  2. O QR renderizado é DECODIFICÁVEL por máquina (cv2.QRCodeDetector como proxy do
     leitor GM861) — round-trip: payload -> imagem -> decode == payload.
  3. O parser de spool_id é BLINDADO: ancora em '/spools/<id>', à prova de números
     no domínio/porta, querystring, sufixos e lixo. É a implementação de referência
     que o firmware do ESP32 deve espelhar (regex /spools/(\d+)).
  4. Simula a aritmética da pesagem (net = bruto - tara) que a API /api/weigh fará.

Uso:  py tools/validate_qr_autoweigh.py
Sai com código 0 se tudo passar; !=0 se algo falhar.
"""
import os
import re
import sys

try:                                  # console Windows (cp1252) -> força UTF-8
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import labels  # noqa: E402  (usa a MESMA geração de QR da etiqueta)

# URL pública — SEMPRE o domínio, nunca IP privado/localhost (crítico ao projeto).
PUBLIC_BASE = "https://spool.lojinharacer.com.br"

# ── Parser de referência (o ESP32 deve fazer igual: regex ancorado) ──────────
_SPOOLS_RE = re.compile(r"/spools/(\d+)\b")
_SP_RE = re.compile(r"^\s*SP[-_ ]?0*(\d+)\s*$", re.I)
_NUM_RE = re.compile(r"^\s*0*(\d+)\s*$")


def extract_spool_id(payload):
    """Extrai o spool_id do conteúdo lido. Ancora em '/spools/<id>'. Aceita também
    'SP-0001' e id puro. Retorna int ou None (nunca um id errado por engano)."""
    s = (payload or "").strip()
    m = _SPOOLS_RE.search(s)
    if m:
        return int(m.group(1))
    m = _SP_RE.match(s)
    if m:
        return int(m.group(1))
    m = _NUM_RE.match(s)
    if m:
        return int(m.group(1))
    return None


def decode_qr(pil_img):
    """Decodifica um PIL QR com cv2, simulando o leitor. Acrescenta zona de silêncio
    (quiet zone) branca, como na etiqueta real, p/ leitura confiável."""
    import numpy as np
    import cv2
    from PIL import Image

    pad = 40
    canvas = Image.new("L", (pil_img.width + 2 * pad, pil_img.height + 2 * pad), 255)
    canvas.paste(pil_img.convert("L"), (pad, pad))
    arr = np.array(canvas)
    data, _, _ = cv2.QRCodeDetector().detectAndDecode(arr)
    return data


def sim_weigh(gross_g, tare_g, nominal_g):
    """Espelha o cálculo de db.add_weight_reading + resposta da /api/weigh."""
    if gross_g < tare_g:
        return {"ok": False, "error": f"bruto {gross_g:.0f}g < tara {tare_g:.0f}g"}
    net = gross_g - tare_g
    pct = round(net / nominal_g * 100, 2) if nominal_g else 0
    return {"ok": True, "net_weight_g": round(net, 1), "remaining_pct": pct}


def main():
    ok = True

    print("=" * 70)
    print("1) ROUND-TRIP do QR — gera (URL pública) -> decodifica -> extrai id")
    print("=" * 70)
    # códigos pequenos e grandes (o id usa zfill(4) só como mínimo; cresce além de 9999)
    ids = [1, 7, 42, 9999, 10000, 123456, 9999999]
    for sid in ids:
        payload = f"{PUBLIC_BASE}/spools/{sid}"
        img = labels._make_qr_image(payload)
        decoded = decode_qr(img)
        got = extract_spool_id(decoded)
        passed = (decoded == payload) and (got == sid)
        ok &= passed
        print(f"  [{'OK ' if passed else 'FAIL'}] SP-{sid:04d} "
              f"v{img.width}px  decode={'==' if decoded == payload else '!='}payload  "
              f"id={got}")

    print()
    print("=" * 70)
    print("2) BLINDAGEM do parser — payloads adversários (id correto OU None)")
    print("=" * 70)
    cases = [
        (f"{PUBLIC_BASE}/spools/42", 42),                 # normal
        (f"{PUBLIC_BASE}/spools/42?src=qr", 42),          # querystring
        (f"{PUBLIC_BASE}/spools/42/weigh", 42),           # sufixo de rota
        ("http://10.1.0.29:8001/spools/5", 5),            # números no host/porta -> ainda 5
        ("https://spool.lojinharacer.com.br/spools/123456", 123456),
        ("SP-0007", 7),                                   # código impresso
        ("SP1234", 1234),                                 # variação sem hífen
        ("42", 42),                                       # id puro
        ("", None),                                       # vazio -> rejeita
        ("https://spool.lojinharacer.com.br/", None),     # sem id -> rejeita
        ("lixo aleatório 2026", None),                    # texto -> rejeita (NÃO vira 2026)
    ]
    for payload, expected in cases:
        got = extract_spool_id(payload)
        passed = got == expected
        ok &= passed
        print(f"  [{'OK ' if passed else 'FAIL'}] {str(payload)[:48]:48s} -> {got!r} "
              f"(esperado {expected!r})")

    print()
    print("=" * 70)
    print("3) Simulação da pesagem (aritmética da /api/weigh)")
    print("=" * 70)
    weigh_cases = [
        # gross, tare, nominal, espera ok?
        (347.5, 185.0, 1000.0, True),   # normal
        (185.0, 185.0, 1000.0, True),   # vazio (net 0)
        (150.0, 185.0, 1000.0, False),  # bruto < tara -> erro (igual ao app)
    ]
    for gross, tare, nominal, exp_ok in weigh_cases:
        r = sim_weigh(gross, tare, nominal)
        passed = r["ok"] == exp_ok
        ok &= passed
        detail = (f"net={r['net_weight_g']}g ({r['remaining_pct']}%)"
                  if r["ok"] else r["error"])
        print(f"  [{'OK ' if passed else 'FAIL'}] bruto={gross} tara={tare} -> {detail}")

    # Opcional: bate no servidor REAL (read-only, não grava) para validar a API
    # implantada sem hardware. Ative com:
    #   SPOOL_LIVE_BASE=https://spool.lojinharacer.com.br SPOOL_API_KEY=<key> \
    #     SPOOL_LIVE_ID=1 py tools/validate_qr_autoweigh.py
    live = os.environ.get("SPOOL_LIVE_BASE", "").strip()
    if live:
        import json
        import urllib.request
        print()
        print("=" * 70)
        print(f"4) API AO VIVO (read-only) — GET {live}/api/spools/<id>")
        print("=" * 70)
        sid = os.environ.get("SPOOL_LIVE_ID", "1")
        req = urllib.request.Request(f"{live.rstrip('/')}/api/spools/{sid}")
        key = os.environ.get("SPOOL_API_KEY", "").strip()
        if key:
            req.add_header("X-API-Key", key)
        try:
            with urllib.request.urlopen(req, timeout=8) as resp:
                body = json.loads(resp.read().decode())
            passed = resp.status == 200 and body.get("ok") is True
            ok &= passed
            print(f"  [{'OK ' if passed else 'FAIL'}] HTTP {resp.status} -> {body}")
        except Exception as e:
            ok = False
            print(f"  [FAIL] erro de rede/HTTP: {e}")

    print()
    print("=" * 70)
    print("RESULTADO:", "TUDO OK ✅" if ok else "FALHAS ❌")
    print("=" * 70)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
