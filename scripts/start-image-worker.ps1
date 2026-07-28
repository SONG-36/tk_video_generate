$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..\backend")
$concurrency = if ($env:IMAGE_WORKER_CONCURRENCY) { $env:IMAGE_WORKER_CONCURRENCY } else { "2" }
& .\.venv\Scripts\celery.exe -A app.tasks.celery_app:celery_app worker -Q image --concurrency=$concurrency --loglevel=INFO --pool=solo

