$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..\backend")
$concurrency = if ($env:VIDEO_WORKER_CONCURRENCY) { $env:VIDEO_WORKER_CONCURRENCY } else { "1" }
& .\.venv\Scripts\celery.exe -A app.tasks.celery_app:celery_app worker -Q video --concurrency=$concurrency --loglevel=INFO --pool=solo

