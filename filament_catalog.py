"""Catálogo de filamentos (SpoolmanDB) — vendorado.

Carrega `spoolman_catalog.json`, um snapshot vendorado de
github.com/Donkie/SpoolmanDB (licença MIT), atualizado por `deploy/vendor-spoolmandb.sh`.
Não há download em runtime/deploy (preserva o deploy à prova de falhas, o CSP e a operação
offline). Exposto ao cliente via `GET /api/filament-catalog` para o picker do formulário de
filamento. Ver `docs/spoolmandb.md`.

FAIL-SAFE: se o arquivo faltar ou estiver corrompido, expõe listas VAZIAS e loga um aviso —
o `import app` nunca falha por causa do catálogo; o recurso apenas fica inerte (o botão
"Importar do catálogo" não aparece) e o resto do app funciona normalmente.
"""
import json
import os
import logger as log_cfg

_log = log_cfg.get_logger("spool.catalog")
_PATH = os.path.join(os.path.dirname(__file__), "spoolman_catalog.json")

BRANDS: list = []
MATERIALS: list = []
FILAMENTS: list = []
SOURCE: str = ""

try:
    with open(_PATH, encoding="utf-8") as _fh:
        _DATA = json.load(_fh)
    BRANDS = list(_DATA.get("brands") or [])
    MATERIALS = list(_DATA.get("materials") or [])
    FILAMENTS = list(_DATA.get("filaments") or [])
    SOURCE = _DATA.get("_source", "")
except Exception:
    _log.warning("filament_catalog.load_failed", path=_PATH, exc_info=True)


def available() -> bool:
    """True se há catálogo carregado (controla a exibição do botão de import)."""
    return bool(FILAMENTS)
