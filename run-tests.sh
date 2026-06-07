#!/usr/bin/env bash
# Roda a suíte de testes (Mac / Linux).
# Na primeira vez cria o ambiente virtual .venv e instala as dependências;
# nas próximas, só roda os testes. Uso:
#   ./run-tests.sh            # roda tudo, modo verboso
#   ./run-tests.sh -k weigh   # só os testes cujo nome casa com "weigh"
#   ./run-tests.sh -s         # mostra também os prints/saída dos testes
set -euo pipefail
cd "$(dirname "$0")"          # entra na raiz do projeto (onde este script está)

PY=./.venv/bin/python
if [ ! -x "$PY" ]; then
  echo "==> Criando ambiente virtual (.venv) — só na primeira vez…"
  python3 -m venv .venv
  "$PY" -m pip install --quiet --upgrade pip
  "$PY" -m pip install --quiet -r requirements.txt -r requirements-dev.txt
fi

echo "==> Rodando testes…"
# -v: lista cada teste e o resultado.  PYTHONPATH=raiz: permite "import app".
PYTHONPATH="$(pwd)" "$PY" -m pytest tests -v "$@"
