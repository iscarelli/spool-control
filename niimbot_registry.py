"""Registro de modelos de impressora Niimbot e tamanhos de etiqueta.

Carrega `niimbot_registry.json`, que é **vendorado verbatim** de
iscarelli/niimbot-web-bluetooth (público) — a fonte de verdade canônica. JS e
Python compartilham esse único arquivo: o driver `static/niimbot.js` e este
módulo vêm sempre da **mesma tag** (refresh via `deploy/vendor-niimbot.sh`),
então não há mais espelhamento manual a manter. Exposto ao cliente via
`GET /api/niimbot/registry` para o `static/niimbot.js`. Ver `docs/niimbot.md`.

Entradas marcadas com a chave `_untested` (derivadas da niimbluelib, não
validadas em hardware — hoje a M2-H) são **ocultadas** aqui: não aparecem nos
dropdowns nem na API até serem confirmadas. Para liberar uma, valide no hardware
e remova a chave `_untested` no JSON upstream + re-vendore.

Para adicionar um modelo ou tamanho novo, edite o repo upstream e rode o script
de sync — os dropdowns e o endpoint de bitmap passam a oferecê-lo
automaticamente. Se o protocolo do novo modelo diferir, o driver já escolhe a
variante de task pelo campo `task` (`v4` ou `b1`).
"""

import json
import os

_REGISTRY_PATH = os.path.join(os.path.dirname(__file__), "niimbot_registry.json")


def _visible(entries: dict) -> dict:
    """Remove chaves de metadados (`_comment`, `_source`, …) e entradas marcadas
    como `_untested` — só sobra o que é seguro oferecer ao usuário."""
    return {
        k: v
        for k, v in entries.items()
        if not k.startswith("_") and not (isinstance(v, dict) and "_untested" in v)
    }


with open(_REGISTRY_PATH, encoding="utf-8") as _fh:
    _DATA = json.load(_fh)

# Modelos visíveis (sem metadados/untested) — controlam quais FAMÍLIAS aparecem.
PRINTER_MODELS = _visible(_DATA.get("models", {}))

# Tamanhos: TODAS as variantes concretas (inclusive `_untested`) ficam disponíveis
# para RESOLUÇÃO interna, render e get_size — a variante NÃO é oferecida ao usuário,
# é escolhida automaticamente a partir da impressora detectada, então o `_untested`
# (que serve p/ não oferecer algo não validado num dropdown) não se aplica à
# resolução. O dropdown de tamanho FÍSICO usa só as visíveis (`_VISIBLE_SIZES`).
LABEL_SIZES = {k: v for k, v in _DATA.get("sizes", {}).items() if not k.startswith("_")}
_VISIBLE_SIZES = _visible(_DATA.get("sizes", {}))

# Defaults do JSON; se o default tiver sido filtrado, cai na 1ª chave.
DEFAULT_MODEL = _DATA.get("default_model") if _DATA.get("default_model") in PRINTER_MODELS \
    else next(iter(PRINTER_MODELS))
DEFAULT_SIZE = _DATA.get("default_size") if _DATA.get("default_size") in LABEL_SIZES \
    else next(iter(LABEL_SIZES))


# Dono (modelo) de cada variante concreta de tamanho — desfaz a ambiguidade quando
# dois modelos têm o mesmo DPI (ex.: B1 Pro e M2-H, ambos 300 dpi / 50×30, mas
# larguras 584 vs 567 px). Convenção do upstream: a chave é "<base>" (modelo padrão)
# ou "<base>_<sufixo>" com o sufixo = chave do modelo (b1 → _b1, m2h → _m2h).
def _size_owner(size_key: str) -> str:
    for _mk in sorted(PRINTER_MODELS, key=len, reverse=True):
        if size_key.endswith("_" + _mk):
            return _mk
    return DEFAULT_MODEL


SIZE_MODEL = {_sk: _size_owner(_sk) for _sk in LABEL_SIZES}

# ── Tamanhos FÍSICOS (mm), agnósticos de impressora ──────────────────────────
# A etiqueta física é a mesma (ex.: 50 × 30 mm) na B1 e na B1 Pro; só muda a
# resolução em pixels conforme o DPI da impressora. O usuário escolhe só o tamanho
# físico; o `static/niimbot-spool.js` identifica a impressora na conexão e resolve
# a variante concreta de `LABEL_SIZES` com o DPI certo. Aqui deduplicamos as
# variantes por (w_mm, h_mm) — o representante é a variante com o DPI do modelo
# padrão (p/ o render server-side default ficar coerente).
_DEFAULT_DPI = PRINTER_MODELS.get(DEFAULT_MODEL, {}).get("dpi")

_rep_key: dict = {}
for _k, _s in _VISIBLE_SIZES.items():
    _dims = (_s.get("w_mm"), _s.get("h_mm"))
    if _dims not in _rep_key or _s.get("dpi") == _DEFAULT_DPI:
        _rep_key[_dims] = _k


def _fmt_mm(v) -> str:
    return ("%g" % v) if v is not None else "?"


PHYSICAL_SIZES = {
    _k: {"label": f"{_fmt_mm(_d[0])} × {_fmt_mm(_d[1])} mm", "w_mm": _d[0], "h_mm": _d[1]}
    for _d, _k in _rep_key.items()
}

# Representante físico do tamanho padrão (chave também presente em LABEL_SIZES).
DEFAULT_PHYSICAL_SIZE = _rep_key.get(
    (LABEL_SIZES[DEFAULT_SIZE].get("w_mm"), LABEL_SIZES[DEFAULT_SIZE].get("h_mm")),
    next(iter(PHYSICAL_SIZES)),
)

# ── Famílias de impressora (item do seletor) ─────────────────────────────────
# O usuário escolhe a FAMÍLIA (ex.: "Niimbot B1 / B1 Pro"), não o modelo exato —
# B1 e B1 Pro anunciam o mesmo nome BLE e diferem só no DPI, que o cliente detecta
# na conexão e resolve sozinho. Agrupamos os modelos visíveis pelo prefixo BLE
# (`name_prefixes`): mesma família = mesmo prefixo. Isso funde B1+B1 Pro num item e
# deixa espaço p/ outras famílias (ex.: M2-H) quando saírem do `_untested`. A chave
# da família é o 1º prefixo; o rótulo é gerado dos modelos membros.
PRINTER_FAMILIES: dict = {}
for _mk, _m in PRINTER_MODELS.items():
    _prefixes = list(_m.get("name_prefixes") or [])
    _fk = _prefixes[0] if _prefixes else _mk
    _fam = PRINTER_FAMILIES.setdefault(_fk, {"label": "", "name_prefixes": [], "models": []})
    _fam["models"].append(_mk)
    for _p in _prefixes:
        if _p not in _fam["name_prefixes"]:
            _fam["name_prefixes"].append(_p)
for _fk, _fam in PRINTER_FAMILIES.items():
    _shorts = sorted({PRINTER_MODELS[_mk]["label"].replace("Niimbot ", "")
                      for _mk in _fam["models"]})
    _fam["label"] = "Niimbot " + " / ".join(_shorts)

# Família padrão = a que contém o modelo padrão.
DEFAULT_FAMILY = next(
    (_fk for _fk, _fam in PRINTER_FAMILIES.items() if DEFAULT_MODEL in _fam["models"]),
    next(iter(PRINTER_FAMILIES)),
)


def get_model(key: str) -> dict:
    return PRINTER_MODELS.get(key, PRINTER_MODELS[DEFAULT_MODEL])


def get_size(key: str) -> dict:
    return LABEL_SIZES.get(key, LABEL_SIZES[DEFAULT_SIZE])
