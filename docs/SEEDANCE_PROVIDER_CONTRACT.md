# Seedance Provider Contract

Documentation access date: 2026-07-24

This document records the V0.2.1 BytePlus ModelArk Seedance API contract used by this project. It is a provider integration contract, not permission to execute paid API calls.

## Official Documentation URLs

- Create video generation task: https://docs.byteplus.com/en/docs/ModelArk/1520757
- Retrieve a video generation task: https://docs.byteplus.com/en/docs/ModelArk/1521309
- Base URL and authentication: https://docs.byteplus.com/en/docs/ModelArk/1298459
- Model billing: https://docs.byteplus.com/en/docs/ModelArk/1544106#8f25f772

## Confirmed API Surface

| Item | Confirmed value |
|---|---|
| Base URL | `https://ark.ap-southeast.bytepluses.com/api/v3` |
| Submit endpoint | `POST /contents/generations/tasks` |
| Retrieve endpoint | `GET /contents/generations/tasks/{id}` |
| Authorization header | `Authorization: Bearer $ARK_API_KEY` |
| Content-Type | `application/json` |
| Model identifier field | `model` |
| Submit task id path | response body `id` |
| Retrieve status path | response body `status` |
| Result video URL path | response body `content.video_url` |
| Failure error path | response body `error.code`, `error.message` |

The official create-task documentation says `model` is the ID of the model to call, and that an endpoint ID can also be used for model invocation. The current implementation treats `SEEDANCE_MODEL` as the value sent in the official `model` field. Whether this value is a model ID or endpoint ID depends on the operator configuration.

## Image Input Contract

The official `content.image_url.url` field accepts:

- public image URL.
- Base64 encoded image data URI in the form `data:image/<image format>;base64,<Base64 encoding>`.
- asset ID in the form `asset://<ASSET_ID>`.

This V0.2.1 implementation uses URL-only real mode:

- real Seedance tasks require a task-specific HTTPS `image_url`.
- local first-frame uploads are retained only as local preview/audit files.
- the Provider sends `content[].image_url.url` from the current task's `image_url`.
- the Provider does not use a global environment image URL.
- the Provider does not send local server file paths.

Base64/data URI submission is officially supported by the field, but this project does not implement local-file-to-base64 submission in V0.2.1. Object-storage or asset publishing is also not implemented in V0.2.1.

## Prompt And Request Structure

Prompt is sent as a text content item:

```json
{
  "type": "text",
  "text": "A controlled slow camera movement around the product."
}
```

First-frame image-to-video is sent as an image content item:

```json
{
  "type": "image_url",
  "image_url": {
    "url": "https://example.com/first-frame.png"
  },
  "role": "first_frame"
}
```

The official documentation says first-frame image-to-video uses one `image_url` object with `role` set to `first_frame` or left blank. V0.2.1 sets `role` to `first_frame` to make the task intent explicit.

## De-Sensitized Submit Request Example

```json
{
  "model": "seedance-model-or-endpoint-id",
  "content": [
    {
      "type": "text",
      "text": "A controlled slow camera movement around the product."
    },
    {
      "type": "image_url",
      "image_url": {
        "url": "[REDACTED_URL_PRESENT]"
      },
      "role": "first_frame"
    }
  ],
  "duration": 5,
  "ratio": "9:16"
}
```

## De-Sensitized Retrieve Response Example

```json
{
  "id": "task-id",
  "model": "seedance-model-or-endpoint-id",
  "status": "succeeded",
  "content": {
    "video_url": "[REDACTED_URL_PRESENT]"
  },
  "resolution": "720p",
  "ratio": "9:16",
  "duration": 5,
  "error": null
}
```

## Internal To Official Field Mapping

| Internal field | Official field |
|---|---|
| `AppConfig.seedance_base_url` | base URL |
| `AppConfig.seedance_api_key` | `Authorization: Bearer <key>` |
| `AppConfig.seedance_model` | request body `model` |
| `VideoTask.prompt` | `content[]` item with `type=text`, `text` |
| `VideoTask.image_url` | `content[]` item with `type=image_url`, `image_url.url`, `role=first_frame` |
| `VideoTask.duration_seconds` | request body `duration` |
| `VideoTask.aspect_ratio` | request body `ratio` |
| `ProviderSubmission.provider_task_id` | submit response `id` |
| `ProviderPollResult.status` | retrieve response `status` mapped to internal status |
| `ProviderPollResult.result_url` | retrieve response `content.video_url` |
| `ProviderPollResult.error_code` | retrieve response `error.code` |
| `ProviderPollResult.error_message` | retrieve response `error.message` |

## Official Status To Internal Status Mapping

| Official status | Internal status |
|---|---|
| `queued` | `queued` |
| `running` | `running` |
| `succeeded` | `succeeded` |
| `failed` | `failed` |
| `cancelled` | `cancelled` |
| `expired` | `failed` |
| unknown value | failed with `PROVIDER_UNKNOWN_STATUS` |

Unknown status values must not be treated as success.

## Parameters Confirmed From Official Documentation

| Field | Confirmed values / notes |
|---|---|
| `resolution` | `480p`, `720p`, `1080p`, `4k`; support varies by model |
| `ratio` | `16:9`, `4:3`, `1:1`, `3:4`, `9:16`, `21:9`, `adaptive` |
| `duration` | integer seconds; Seedance 2.0 series supports `[4,15]` or `-1`; Seedance 1.0 Pro/Pro Fast supports `[2,12]`; Seedance 1.5 Pro supports `[4,12]` or `-1` |
| `frames` | alternative to `duration`; not supported by Seedance 2.0 series or Seedance 1.5 Pro |
| `watermark` | boolean |
| `generate_audio` | boolean for Seedance 2.0 series and Seedance 1.5 Pro |
| `execution_expires_after` | integer seconds, default `172800`, range `[3600, 259200]` |

V0.2.1 currently sends only `model`, `content`, `duration`, and `ratio`.

## Timeouts, Rate Limits, Errors, And Billing

| Topic | Current confirmation |
|---|---|
| Task expiration | Official `execution_expires_after` defaults to 172800 seconds and accepts `[3600, 259200]` |
| HTTP timeout | SDK/client timeout is local operator config, not an official task timeout |
| Rate limits | UNCONFIRMED in the provider contract; official docs say endpoint IDs can expose rate limits |
| Error response | Retrieve response exposes `error.code` and `error.message` |
| Submit HTTP error format | UNCONFIRMED beyond HTTP status and possible JSON `error` body |
| Pricing formula | UNCONFIRMED for this configured model/endpoint in code |
| Pre-submit cost estimate | UNCONFIRMED; implementation keeps `estimated_cost=None` |

## Current Model Price / Billing Basis

UNCONFIRMED.

The official documentation has a Model Billing section, but V0.2.1 does not implement a verified price formula for the operator's configured `model` or endpoint ID. Therefore the app and smoke script must not claim that a local value is a Provider-enforced cost ceiling.

## Fields Not To Guess

Do not guess:

- whether `SEEDANCE_MODEL` is a model name, endpoint ID, or another deployment identifier for a specific account.
- exact price formula for the configured model/endpoint.
- endpoint-specific rate limits.
- account-specific quota.
- whether signed URLs from a private object store will remain accessible long enough for task execution.
- whether local files should be converted to Base64 for production use without separate approval.
- object-storage publishing configuration.

## V0.2.1 Chosen Mode

V0.2.1 implements URL-only real mode:

```text
operator-provided task image_url
-> VideoTask.image_url
-> Provider request content[].image_url.url
```

The local uploaded first frame is not sent to Seedance in URL-only real mode.
