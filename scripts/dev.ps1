<#
.SYNOPSIS
    Development tasks for Laboratory Innovation Brain (Windows equivalent of the Makefile).

.EXAMPLE
    .\scripts\dev.ps1 check
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet('install', 'spec', 'test', 'test-all', 'lint', 'fmt', 'typecheck', 'check',
                 'db-up', 'db-down', 'migrate', 'clean', 'help')]
    [string]$Task = 'help'
)

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$py = Join-Path $repo '.venv\Scripts\python.exe'

function Assert-Venv {
    if (-not (Test-Path $py)) {
        throw "venv not found. Run: .\scripts\dev.ps1 install"
    }
}

Push-Location $repo
try {
    switch ($Task) {
        'install' {
            python -m venv .venv
            & $py -m pip install --upgrade pip
            & $py -m pip install -e ".[dev,postgres]"
        }
        'spec'      { Assert-Venv; & $py -m pytest tests/spec -q }
        'test'      { Assert-Venv; & $py -m pytest }
        'test-all'  {
            Assert-Venv
            $env:LAB_BRAIN_TEST_POSTGRES = '1'
            & $py -m pytest
        }
        'lint'      { Assert-Venv; & $py -m ruff check src tests }
        'fmt'       { Assert-Venv; & $py -m ruff format src tests }
        'typecheck' { Assert-Venv; & $py -m mypy }
        'check'     {
            Assert-Venv
            & $py -m pytest tests/spec -q
            if ($LASTEXITCODE -ne 0) { throw 'spec conformance failed — slice is blocked (AGT-015)' }
            & $py -m ruff check src tests
            if ($LASTEXITCODE -ne 0) { throw 'lint failed' }
            & $py -m mypy
            if ($LASTEXITCODE -ne 0) { throw 'typecheck failed' }
            & $py -m pytest
            if ($LASTEXITCODE -ne 0) { throw 'tests failed' }
            Write-Host 'all checks passed' -ForegroundColor Green
        }
        'db-up'     { docker compose up -d }
        'db-down'   { docker compose down }
        'migrate'   { Assert-Venv; & $py scripts/migrate.py }
        'clean'     {
            foreach ($d in '.pytest_cache', '.mypy_cache', '.ruff_cache', 'htmlcov') {
                if (Test-Path $d) { Remove-Item -Recurse -Force $d }
            }
            if (Test-Path '.coverage') { Remove-Item -Force '.coverage' }
        }
        default {
            @'
Tasks:
  install    Create .venv and install with dev extras
  spec       Spec conformance only (T-SPEC-001 / T-SPEC-002)
  test       Default suite: no Postgres / Lumerical / network (AGT-007)
  test-all   Full suite including backend-dependent tests
  lint       Ruff lint
  fmt        Ruff format
  typecheck  mypy strict
  check      spec + lint + typecheck + test
  db-up      Start PostgreSQL + pgvector
  db-down    Stop PostgreSQL
  migrate    Apply versioned migrations
  clean      Remove caches
'@ | Write-Host
        }
    }
}
finally {
    Pop-Location
}
