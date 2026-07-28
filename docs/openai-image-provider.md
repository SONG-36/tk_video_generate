# OpenAI 图片 Provider 联调

当前图片真实 Provider 使用 OpenAI Image API：

- 无参考图：`POST /v1/images/generations`
- 有参考图：`POST /v1/images/edits`
- 默认模型：`gpt-image-2`
- 输出：PNG Base64
- 多图数量：`n`

## 配置

从项目根目录复制环境文件：

```powershell
Copy-Item .env.example .env
```

在 `.env` 中配置：

```dotenv
IMAGE_PROVIDER=openai
OPENAI_API_KEY=your_api_key
OPENAI_IMAGE_MODEL=gpt-image-2
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_REQUEST_TIMEOUT=180
OPENAI_ORGANIZATION=
OPENAI_PROJECT=
```

不要提交 `.env`。如果账户属于多个组织或项目，可填写可选的 organization/project
标识。使用 GPT Image 模型前，OpenAI 账户可能需要完成组织验证。

## 合约测试

普通测试不会访问 OpenAI：

```powershell
Set-Location backend
.\.venv\Scripts\python.exe -m pytest -q
```

## 真实 Provider 冒烟测试

真实测试会产生一次图片 API 调用和相应费用，只有显式设置开关才会运行：

```powershell
Set-Location backend
$env:OPENAI_LIVE_TEST = "1"
.\.venv\Scripts\python.exe -m pytest `
  tests/test_openai_image_provider_live.py -q -s
Remove-Item Env:OPENAI_LIVE_TEST
```

测试成功后，再启动后端、图片 Worker 和前端，通过正常图片页面分别验证：

1. 无参考图生成；
2. 单张参考图编辑；
3. 多张参考图编辑；
4. `n=1/2/4`；
5. `1:1`、`3:4`、`9:16`；
6. 额度不足、限流、安全拦截和超时错误。

官方资料：

- https://developers.openai.com/api/docs/guides/image-generation
- https://developers.openai.com/api/docs/models/gpt-image-2
