# 火山方舟视频 Provider

项目通过火山方舟异步视频生成 API 创建任务、轮询状态，并在成功后立即把 MP4
下载到 `storage/outputs/video`。默认 Provider 仍为 Mock；只有显式修改配置才会产生
真实网络请求和费用。

## 配置

在 `backend/.env` 中增加：

```dotenv
VIDEO_PROVIDER=volcengine_ark
ARK_API_KEY=your_ark_api_key
ARK_VIDEO_MODEL=doubao-seedance-2-0-260128
ARK_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
ARK_REQUEST_TIMEOUT=60
ARK_VIDEO_POLL_INTERVAL=5
ARK_VIDEO_POLL_NETWORK_RETRIES=3
ARK_VIDEO_POLL_RETRY_BASE_DELAY=2
ARK_VIDEO_GENERATION_TIMEOUT=900
ARK_VIDEO_MAX_DOWNLOAD_MB=200
```

`ARK_VIDEO_POLL_NETWORK_RETRIES` 只用于已经取得厂商任务 ID 后的 GET
轮询网络异常；重试等待默认依次为 2、4、8 秒。创建任务的 POST 不会自动重试，
避免重复创建厂商任务和重复计费。

模型 ID 必须以火山方舟控制台中当前账号实际开通的模型为准。若 Seedance 2.0
尚未对账号开放，可替换 `ARK_VIDEO_MODEL`，无需修改代码。修改配置后重启视频
Celery Worker；FastAPI 和图片 Worker 不需要切换 Provider。

## 参数映射

- 参考生成图片映射为 `image_url`，角色为 `reference_image`。
- 首帧图片角色为 `first_frame`。
- 分辨率映射为 `480p` 或 `720p`。
- 比例映射为 `16:9` 或 `9:16`。
- 固定时长写入 `duration`；智能时长不传该字段。
- 是否生成声音写入 `generate_audio`。
- 本地 JPG/JPEG/PNG 会转换为 Base64 data URL，不会把本机路径发送给厂商。

Provider 会轮询 `queued` / `running` 状态，处理 `succeeded`、`failed` 和
`cancelled`，并把鉴权、限流、余额不足、内容安全、模型不存在和超时等情况转换为
稳定的 `ARK_*` 错误码。厂商返回 usage 时写入已有 `provider_usage`；未返回时保持
`UNKNOWN`，不推测费用或 token。

## 测试

普通测试完全模拟 HTTP，不调用火山方舟：

```powershell
Set-Location backend
.\.venv\Scripts\python.exe -m pytest -q
```

真实联调是显式付费测试。确认账号余额、模型权限和费用上限后执行：

```powershell
$env:ARK_VIDEO_LIVE_TEST="1"
.\.venv\Scripts\python.exe -m pytest -q -m live `
  tests/test_volcengine_ark_video_provider_live.py
```

联调测试固定使用 480P、5 秒、无声音，结束后可移除当前 PowerShell 会话中的开关：

```powershell
Remove-Item Env:ARK_VIDEO_LIVE_TEST
```

接口依据：

- [创建视频生成任务 API](https://api.volcengine.com/api-docs/view?action=CreateContentsGenerationsTasks&serviceCode=ark&version=2024-01-01)
- [查询视频生成任务 API](https://api.volcengine.com/api-docs/view?action=GetContentsGenerationsTask&serviceCode=ark&version=2024-01-01)
