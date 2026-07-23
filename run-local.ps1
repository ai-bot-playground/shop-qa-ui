# run-local.ps1 — uruchamia shop-qa-ui NATYWNIE na hoście (bez kontenera).
#
# Dlaczego natywnie, a nie w kontenerze:
#   Funkcja "Otwórz PR" (src/sandbox.py) operuje na LOKALNYCH klonach repo —
#   robi `git fetch`/`git worktree` (zapis do .git), `git push` (Windows
#   Credential Manager) oraz `gh pr create`. Kontener 8502 montował /workspace
#   jako read-only, nie miał `gh` ani tokenu GitHub, więc PR-y padały na
#   "cannot open '.git/FETCH_HEAD': Read-only file system". Na hoście repo są
#   zapisywalne, `gh` jest zalogowany, a `git push` korzysta z GCM — działa.
#
# Użycie:
#   pwsh -File run-local.ps1            # port 8502 (jak dotychczasowy kontener)
#   pwsh -File run-local.ps1 -Port 8501
[CmdletBinding()]
param(
  [int]$Port = 8502
)
$ErrorActionPreference = 'Stop'

# Katalog tego skryptu = katalog shop-qa-ui.
$here = $PSScriptRoot
Set-Location $here

# Root repozytoriów = katalog nadrzędny (ai-bot-playground z siostrzanymi shop-*).
# Sandbox/PR rozwiązuje lokalne klony przez SHOP_REPOS_DIR/<nazwa-repo>.
$reposRoot = (Resolve-Path (Join-Path $here '..')).Path

$venvPy = Join-Path $here '.venv\Scripts\python.exe'
if (-not (Test-Path $venvPy)) {
  Write-Host "[run-local] Brak .venv — tworzę i instaluję zależności…"
  python -m venv (Join-Path $here '.venv')
  & $venvPy -m pip install --upgrade pip
  & $venvPy -m pip install -r (Join-Path $here 'requirements.txt')
  if ($LASTEXITCODE -ne 0) { throw "pip install nie powiódł się" }
}

# Klucze API (OPENROUTER_*) czyta app przez python-dotenv z ./.env.
$env:SHOP_REPOS_DIR = $reposRoot
# Telemetria tokenów: natywnie serwis jest pod localhost:8088 (port-forward-ui.ps1).
if (-not $env:TOKEN_METRICS_URL) { $env:TOKEN_METRICS_URL = 'http://localhost:8088' }

Write-Host "[run-local] SHOP_REPOS_DIR = $env:SHOP_REPOS_DIR"
Write-Host "[run-local] UI -> http://localhost:$Port"

# Argumenty jako tablica + splatting — unika kruchości kontynuacji linii backtickiem
# (w Windows PowerShell 5.1 spacja po backticku psuje parsowanie).
$stArgs = @(
  '-m', 'streamlit', 'run', (Join-Path $here 'app.py'),
  '--server.port', "$Port",
  '--server.address', '127.0.0.1',
  '--server.headless', 'true',
  '--browser.gatherUsageStats', 'false'
)
& $venvPy @stArgs
