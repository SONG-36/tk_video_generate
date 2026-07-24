# TK Video Generate

Local batch video generation workbench with a V0.1 Mock provider and V0.2
single-task Seedance provider infrastructure.

## Mock Mode

- Free local simulation.
- Uses FFmpeg to turn the first frame into H.264/yuv420p MP4.
- Supports 1 to 10 tasks per batch.
- Supports concurrency 1 to 5.
- Supports `[mock-fail]` and `[mock-timeout]` deterministic failure tests.

## Seedance Mode

- Real paid API mode.
- V0.2 allows exactly 1 task and concurrency 1.
- No automatic real-task retry.
- No real batch generation.
- Requires official provider configuration from server environment variables.
- Current provider channel: BytePlus ModelArk Seedance.
- Official documentation source: https://docs.byteplus.com/en/docs/ModelArk/1520757
- Documentation access date: 2026-07-24.
- API surface implemented: ModelArk API v3 task submit and task query endpoints.
- Real submissions use a task-level Seedance image URL. The local uploaded image
  is stored as the local preview/audit file only and is not uploaded to
  BytePlus by this prototype.

## Configuration

Copy `.env.example` to a local `.env` only if your shell or process manager loads
it. The app itself does not auto-load `.env`.

Required for Seedance mode:

```dotenv
VIDEO_PROVIDER=byteplus_seedance
SEEDANCE_API_KEY=
SEEDANCE_BASE_URL=https://ark.ap-southeast.bytepluses.com/api/v3
SEEDANCE_MODEL=
REAL_VIDEO_MAX_COST_USD=1.00
```

macOS/Linux shells:

```bash
export SEEDANCE_API_KEY="..."
export SEEDANCE_MODEL="..."
```

Windows PowerShell:

```powershell
$env:SEEDANCE_API_KEY="..."
$env:SEEDANCE_MODEL="..."
```

Never commit `.env` or API keys. The app only displays configuration status as
`Configured` or `Missing`; it does not print key contents.

## Run

```bash
cd /Users/andy_server/projects/andy/tk_video_generate
source .venv/bin/activate
streamlit run app.py --server.address 0.0.0.0 --server.port 8503 --server.headless true
```

If port 8503 is occupied, choose another free port. Do not stop unrelated user
processes to free a port.

## Recovery

On startup:

- Mock `RUNNING` or `SUBMITTING` tasks are restored to `QUEUED`.
- Real tasks with a saved `provider_task_id` in `SUBMITTED`, `POLLING`, or
  `DOWNLOADING` recover to `POLLING`.
- Real `SUBMITTING` tasks without `provider_task_id` become `FAILED` with
  `SUBMISSION_STATE_UNCERTAIN`.

`SUBMITTING` is not automatically retried because the provider request may have
succeeded while local storage failed before saving the provider task id. Blind
retry could create duplicate paid jobs.

## Files

Task outputs are stored under:

```text
storage/outputs/<batch_id>/<task_id>/
```

Real provider tasks save:

- `first_frame.<ext>`
- `request.json` with sensitive fields redacted
- `provider_submit_response.json`
- `provider_poll_latest.json`
- `provider_poll_history.jsonl`
- `result.mp4`
- `result.json`

## Real Smoke Test

Dry Run does not access the network and does not call the real API:

```bash
python scripts/real_seedance_smoke.py \
  --dry-run \
  --image-url "https://example.com/first-frame.png" \
  --prompt "A controlled slow camera movement around the product."
```

Do not run this casually. It can call a real paid API.

```bash
python scripts/real_seedance_smoke.py \
  --allow-real-api \
  --human-confirm "CONFIRM REAL SMOKE" \
  --image-url "https://example.com/first-frame.png" \
  --local-preview-image /absolute/path/to/first-frame.png \
  --prompt "A controlled slow camera movement around the product." \
  --operator-max-cost-ack-usd 1.00
```

The script refuses to call the API unless all explicit confirmation arguments
are present. `--image-url` is the image sent in the Seedance payload.
`--local-preview-image` is only stored locally for preview and audit. It submits
exactly one task and does not perform batch generation.

Seedance cost estimation is currently unknown. The operator acknowledgment amount
is a local confirmation value, not a provider-enforced spending ceiling.

## Current Limits

- V0.2 real mode supports only one task.
- Maximum real-provider concurrency is 1.
- Workers run only while the app process is alive.
- Already submitted remote tasks may continue even if the local app stops.
- The app does not cancel remote tasks.
- The app does not request refunds.
- No user account or permission system.
- No real batch generation.
- No automatic fee reconciliation.
