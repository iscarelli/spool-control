# Roda a suíte de testes (Windows / PowerShell).
# Na primeira vez cria o ambiente virtual .venv e instala as dependências;
# nas próximas, só roda os testes. Uso:
#   .\run-tests.ps1            # roda tudo, modo verboso
#   .\run-tests.ps1 -k weigh   # só os testes cujo nome casa com "weigh"
#   .\run-tests.ps1 -s         # mostra também os prints/saída dos testes
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot     # entra na raiz do projeto (onde este script está)

$py = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    Write-Host "==> Criando ambiente virtual (.venv) — só na primeira vez..."
    py -3 -m venv .venv
    & $py -m pip install --quiet --upgrade pip
    & $py -m pip install --quiet -r requirements.txt -r requirements-dev.txt
}

Write-Host "==> Rodando testes..."
# -v: lista cada teste e o resultado.  PYTHONPATH=raiz: permite "import app".
$env:PYTHONPATH = $PSScriptRoot
& $py -m pytest tests -v @args
