param(
    [ValidateSet("all", "frontend", "backend")]
    [string]$Area = "all"
)

$ErrorActionPreference = "Stop"
$skillDir = Split-Path -Parent $PSScriptRoot
$projectRoot = [IO.Path]::GetFullPath((Join-Path $skillDir "..\..\.."))
$frontendRoot = Join-Path $projectRoot "frontend"
$backendRoot = Join-Path $projectRoot "backend"
$failures = [System.Collections.Generic.List[string]]::new()
$skipped = [System.Collections.Generic.List[string]]::new()

function Invoke-Check {
    param(
        [string]$Name,
        [string]$WorkingDirectory,
        [scriptblock]$Command
    )

    Write-Host "`n==> $Name" -ForegroundColor Cyan
    Push-Location $WorkingDirectory
    try {
        & $Command
        if ($LASTEXITCODE -ne 0) {
            $failures.Add("$Name (exit $LASTEXITCODE)")
        }
    }
    catch {
        $failures.Add("$Name ($($_.Exception.Message))")
    }
    finally {
        Pop-Location
    }
}

if ($Area -in @("all", "backend")) {
    $python = Join-Path $backendRoot ".venv\Scripts\python.exe"
    $alembic = Join-Path $backendRoot ".venv\Scripts\alembic.exe"
    if ((Test-Path -LiteralPath $python) -and (Test-Path -LiteralPath $alembic)) {
        Invoke-Check "Backend tests" $backendRoot {
            & $python -m pytest -q -p no:cacheprovider
        }
        Invoke-Check "Alembic offline migration" $backendRoot {
            $previousPreference = $ErrorActionPreference
            $ErrorActionPreference = "Continue"
            & $alembic upgrade head --sql *> $null
            $migrationExitCode = $LASTEXITCODE
            $ErrorActionPreference = $previousPreference
            if ($migrationExitCode -eq 0) {
                Write-Host "Alembic offline migration: OK" -ForegroundColor Green
            }
            else {
                exit $migrationExitCode
            }
        }
    }
    else {
        $skipped.Add("Backend checks: backend/.venv is missing")
    }
}

if ($Area -in @("all", "frontend")) {
    if (Test-Path -LiteralPath (Join-Path $frontendRoot "node_modules")) {
        Invoke-Check "Frontend type check" $frontendRoot { & npm run type-check }
        Invoke-Check "Frontend lint" $frontendRoot { & npm run lint }
        Invoke-Check "Frontend build" $frontendRoot { & npm run build }
    }
    else {
        $skipped.Add("Frontend checks: frontend/node_modules is missing")
    }
}

if ($skipped.Count -gt 0) {
    Write-Host "`nSkipped:" -ForegroundColor Yellow
    $skipped | ForEach-Object { Write-Host "- $_" }
}

if ($failures.Count -gt 0) {
    Write-Host "`nFailed:" -ForegroundColor Red
    $failures | ForEach-Object { Write-Host "- $_" }
    exit 1
}

Write-Host "`nAll available checks passed." -ForegroundColor Green
