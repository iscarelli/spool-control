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

# Modelos de impressora e tamanhos de etiqueta visíveis (sem metadados/untested).
PRINTER_MODELS = _visible(_DATA.get("models", {}))
LABEL_SIZES = _visible(_DATA.get("sizes", {}))

# Defaults do JSON; se o default tiver sido filtrado (untested), cai na 1ª chave.
DEFAULT_MODEL = _DATA.get("default_model") if _DATA.get("default_model") in PRINTER_MODELS \
    else next(iter(PRINTER_MODELS))
DEFAULT_SIZE = _DATA.get("default_size") if _DATA.get("default_size") in LABEL_SIZES \
    else next(iter(LABEL_SIZES))


def get_model(key: str) -> dict:
    return PRINTER_MODELS.get(key, PRINTER_MODELS[DEFAULT_MODEL])


def get_size(key: str) -> dict:
    return LABEL_SIZES.get(key, LABEL_SIZES[DEFAULT_SIZE])
