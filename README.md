# TK Video Generate

V0.1 is a local mock batch video generation workbench. It does not call Seedance
or any real video generation API. The mock provider turns the uploaded first
frame into a short H.264/yuv420p MP4 with FFmpeg.

## Run

```bash
cd /Users/andy_server/projects/andy/tk_video_generate
source .venv/bin/activate
streamlit run app.py --server.address 127.0.0.1 --server.port 8502 --server.headless true
```

Use port `8502`; port `8501` is reserved because it was already occupied during
environment checks.

## Manual V0.1 Acceptance

1. Open the Streamlit app.
2. Upload up to 10 PNG/JPG first-frame images.
3. Add one prompt per uploaded image.
4. Choose duration `3`, `5`, or `10` seconds.
5. Choose aspect ratio `9:16`, `1:1`, or `16:9`.
6. Set concurrency from `1` to `5`; the default is `3`.
7. Enter the displayed confirmation text exactly, then submit the batch.
8. Confirm that queued tasks move to running and then complete or fail.
9. Successful tasks finish as `SUCCEEDED`.
10. Use `[mock-fail]` in a prompt to force `MOCK_FORCED_FAILURE`.
11. Use `[mock-timeout]` in a prompt to simulate a delayed timeout failure.
12. Refresh the page and confirm batches, tasks, video previews, and downloads
    are still available.
13. Retry a failed task and confirm its retry count increases. V0.1 does not
    support editing task prompts, so deterministic mock failures fail again.
14. Download a single MP4, `request.json`, `result.json`, and the batch ZIP.

## CLI Verification

```bash
python -m ruff check .
python -m pytest -q
python scripts/manual_mock_validation.py
```

The manual validation script creates a three-task mock batch:

- normal prompt: succeeds with a playable 9:16 MP4 at 540x960
- `[mock-fail]`: fails with `MOCK_FORCED_FAILURE`
- `[mock-timeout]`: waits briefly and fails with `MOCK_TIMEOUT`

## Current Limits

- No real Seedance integration.
- Workers run only while the application process is alive.
- This is a single-machine, single-process prototype.
- No user accounts or permission system.
