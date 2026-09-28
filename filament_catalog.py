"""Catálogo de filamentos (SpoolmanDB).

Duas cópias possíveis, resolvidas em ORDEM DE PREFERÊNCIA a cada acesso:

1. `data/spoolman_catalog.json` — cópia gravada em RUNTIME pelo refresh diário
   (`spoolmandb_refresh.run_scheduled_refresh`, via `deploy/backup-cron.py`) ou pelo
   botão "Atualizar catálogo" em `/admin/update`. Usada quando existe, é válida e sua
   data `fetched` é >= a do snapshot vendorado (nunca regride para uma cópia mais velha).
2. `spoolman_catalog.json` (raiz do repo) — snapshot VENDORADO, atualizado por
   `deploy/vendor-spoolmandb.sh` e committado no git. Fallback sempre disponível
   (preserva a operação offline: sem rede, o catálogo nunca fica vazio à toa).
3. Nenhuma válida → listas VAZIAS (o botão "Importar do catálogo" não aparece).

FAIL-SAFE: nenhuma das duas faltando/corrompida impede o `import app` — o recurso
apenas fica inerte. Carregamento é LAZY com checagem de mtime (`os.stat` nas duas
cópias a cada acesso): os workers do gunicorn (2, sem memória compartilhada) enxergam
um refresh escrito por outro processo sem reiniciar, e o custo é dois `stat()` por
acesso — só reabre e re-parseia o JSON quando algum mtime muda.

Exposto ao cliente via `GET /api/filament-catalog` para o picker do formulário de
filamento. Ver `docs/spoolmandb.md`.
"""
import json
import os
import threading

import logger as log_cfg

_log = log_cfg.get_logger("spool.catalog")

VENDORED_PATH = os.path.join(os.path.dirname(__file__), "spoolman_catalog.json")


def runtime_path():
    """Caminho da cópia gravada em runtime (ao lado do banco — mesmo diretório de
    dados usado por `backup.BACKUPS_DIR`, respeita `SPOOL_DB_PATH` nos testes).

    Importa `database` NA CHAMADA (não no topo do módulo): os testes reimportam
    `database` a cada caso (apontando `DB_PATH` para um banco temporário novo,
    ver tests/conftest.py) trocando a entrada em `sys.modules` — mas este módulo
    não é reimportado junto, então um `import database as db` de topo ficaria
    prendendo, para sempre, a referência do PRIMEIRO teste que o importou."""
    import database as db
    return db.DB_PATH.parent / "spoolman_catalog.json"


_lock = threading.Lock()
_state = {
    "brands": [], "materials": [], "filaments": [],
    "fetched": "", "source": "",   # "server" | "vendored" | ""
    "sig": "unset",                # (mtime_vendorado, mtime_runtime) da última carga
}


def _mtime(path):
    try:
        return os.stat(path).st_mtime
    except OSError:
        return None


def _load_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _valid(data):
    return isinstance(data, dict) and isinstance(data.get("filaments"), list) and bool(data["filaments"])


def _pick():
    """Decide qual cópia usar AGORA, sem tocar no cache: runtime se válida e não-mais-
    velha que a vendorada; senão vendorada; senão nenhuma."""
    try:
        vendored = _load_json(VENDORED_PATH)
        if not _valid(vendored):
            vendored = None
    except Exception:
        vendored = None

    try:
        runtime = _load_json(runtime_path())
        if not _valid(runtime):
            runtime = None
    except Exception:
        runtime = None

    if runtime is not None and (vendored is None
                                 or (runtime.get("fetched") or "") >= (vendored.get("fetched") or "")):
        return runtime, "server"
    if vendored is not None:
        return vendored, "vendored"
    return None, ""


def _ensure_fresh():
    sig = (_mtime(VENDORED_PATH), _mtime(runtime_path()))
    with _lock:
        if sig == _state["sig"]:
            return
        data, source = _pick()
        if data:
            _state["brands"] = list(data.get("brands") or [])
            _state["materials"] = list(data.get("materials") or [])
            _state["filaments"] = list(data.get("filaments") or [])
            _state["fetched"] = data.get("fetched") or ""
            _state["source"] = source
        else:
            _state["brands"], _state["materials"], _state["filaments"] = [], [], []
            _state["fetched"], _state["source"] = "", ""
            if sig != (None, None):
                _log.warning("filament_catalog.load_failed",
                             vendored=VENDORED_PATH, runtime=str(runtime_path()))
        _state["sig"] = sig


def get_brands() -> list:
    _ensure_fresh()
    return _state["brands"]


def get_materials() -> list:
    _ensure_fresh()
    return _state["materials"]


def get_filaments() -> list:
    _ensure_fresh()
    return _state["filaments"]


def info() -> dict:
    """Data/fonte do snapshot em uso agora — para a seção de catálogo em /admin/update."""
    _ensure_fresh()
    return {"fetched": _state["fetched"], "source": _state["source"]}


def available() -> bool:
    """True se há catálogo carregado (controla a exibição do botão de import)."""
    _ensure_fresh()
    return bool(_state["filaments"])


def __getattr__(name):
    # PEP 562 — mantém `catalog.BRANDS` / `.MATERIALS` / `.FILAMENTS` funcionando
    # como propriedades VIVAS (recarregadas via _ensure_fresh) para quem já lê os
    # antigos atributos de módulo, em vez de um valor congelado no import.
    if name == "BRANDS":
        return get_brands()
    if name == "MATERIALS":
        return get_materials()
    if name == "FILAMENTS":
        return get_filaments()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
