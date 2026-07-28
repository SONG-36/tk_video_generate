# TikTok 运营制作

公司内部单机使用的 TikTok 图片与视频批量生成工具。图片和视频均已完成批量任务、
参考图上传、异步执行、状态轮询、结果展示与下载闭环。图片支持 Mock/OpenAI
Provider，视频支持 Mock/火山方舟 Provider。

## 技术栈

- 前端：Vue 3、TypeScript、Vite、Element Plus、Axios、Pinia、Vue Router
- 后端：Python 3.12、FastAPI、Pydantic、SQLAlchemy 2、Alembic、PyMySQL
- 异步任务：Celery、Redis
- 数据库：MySQL 8
- 存储：项目本地 `storage` 目录
- 测试：pytest、FastAPI TestClient

## 图片生成流程

1. 前端将任务参数和参考图作为一个 multipart 批次提交。
2. 后端先校验整批任务和所有图片；任一失败时不创建任务、不投递 Celery。
3. 数据库创建批次、任务、图片详情和参考图记录。
4. Celery 图片 Worker 调用配置的图片 Provider。
5. 无参考图时调用图片生成；有参考图时调用图片编辑。
6. Base64 图片保存到 `storage/outputs/image`，每张图片对应一条结果记录。
7. 前端每两秒轮询批次，完成后展示并允许逐张下载。

默认 `IMAGE_PROVIDER=mock`，可在不产生第三方费用的情况下完整体验流程。

## 目录

```text
tiktok-operations-studio/
├─ frontend/                 Vue 前端
├─ backend/
│  ├─ app/
│  │  ├─ api/               HTTP 路由
│  │  ├─ core/              配置、数据库、日志、异常
│  │  ├─ models/            SQLAlchemy 模型
│  │  ├─ repositories/      数据访问
│  │  ├─ services/          业务与文件存储服务
│  │  ├─ providers/         图片/视频 Provider 抽象及厂商适配
│  │  └─ tasks/             Celery 异步任务
│  ├─ alembic/              数据库迁移
│  └─ tests/                后端测试
├─ storage/                 上传、输出和临时文件
├─ scripts/                 Windows 启动脚本
├─ docker-compose.yml
└─ .env.example
```

## 环境要求

- Python 3.12
- Node.js 16+ 与 npm（建议 Node.js 20 LTS）
- Docker Desktop（用于 MySQL 8 与 Redis；也可自行安装对应服务）

## 首次安装（Windows PowerShell）

在项目根目录执行：

```powershell
Copy-Item .env.example .env

Set-Location backend
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt

Set-Location ..\frontend
npm install
Set-Location ..
```

如果 PowerShell 阻止激活脚本，可在当前窗口执行：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
```

## 启动基础服务

先修改 `.env` 中的示例密码，再执行：

```powershell
docker compose up -d mysql redis
docker compose ps
```

数据保存在 Compose 命名卷中。停止服务用 `docker compose stop`，连同数据卷删除
需显式执行 `docker compose down -v`，请谨慎使用。

## 数据库迁移

MySQL 健康后：

```powershell
Set-Location backend
.\.venv\Scripts\Activate.ps1
alembic upgrade head
alembic current
```

应用不会在启动时调用 `create_all`，数据库结构只由 Alembic 管理。

各业务表的用途、关系、字段含义和常用排查 SQL 见
[数据库字典](docs/database-dictionary.md)。

## 启动开发服务

打开三个或四个 PowerShell 窗口。

FastAPI：

```powershell
.\scripts\start-backend.ps1
```

也可在 `backend` 目录手动执行：

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

图片与视频 Worker：

```powershell
.\scripts\start-image-worker.ps1
.\scripts\start-video-worker.ps1
```

Windows 开发环境使用 Celery `solo` 池；生产部署需根据目标系统重新评估池类型。
Worker 并发值分别由 `IMAGE_WORKER_CONCURRENCY` 和
`VIDEO_WORKER_CONCURRENCY` 环境变量控制。

前端：

```powershell
Set-Location frontend
npm run dev
```

浏览器访问 `http://localhost:5173`。健康检查位于
`http://127.0.0.1:8000/api/health`，接口文档位于
`http://127.0.0.1:8000/docs`。

需要在 Windows 运行应用、在 CentOS 虚拟机运行 Docker 基础设施，并通过浏览器
逐项验收图片、视频和真实 Provider 时，请使用
[Windows + CentOS 虚拟机完整启动与真实验收手册](docs/local-full-stack-testing-guide.md)。

## 启用 OpenAI 图片 Provider

默认配置不会访问 OpenAI。需要真实生成时，在 `.env` 中设置：

```dotenv
IMAGE_PROVIDER=openai
OPENAI_API_KEY=your_api_key
OPENAI_IMAGE_MODEL=gpt-image-2
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_REQUEST_TIMEOUT=180
```

不要提交包含真实密钥的 `.env`。图片比例由 Provider 映射到 OpenAI 支持的尺寸：
`1:1` 使用 `1024x1024`，`3:4` 和 `9:16` 使用竖图 `1024x1536`。输出固定为 PNG。

## 启用火山方舟视频 Provider

默认视频流程使用 Mock，不会产生第三方费用。真实生成时，在 `backend/.env` 中设置：

```dotenv
VIDEO_PROVIDER=volcengine_ark
ARK_API_KEY=your_ark_api_key
ARK_VIDEO_MODEL=doubao-seedance-2-0-260128
ARK_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
```

模型 ID 以火山方舟控制台对当前账号实际开放的模型为准。完整参数、错误处理和显式
付费联调方式见 [火山方舟视频 Provider 文档](docs/volcengine-ark-video-provider.md)。

## 图片 API

- `POST /api/image/batches`：multipart 批次提交，表单字段 `payload` 为 JSON，
  参考图字段为 `references_0`、`references_1` 等。
- `POST /api/image/tasks/{task_id}/references`：为待执行图片任务追加单张参考图。
- `GET /api/image/batches/{batch_id}/status`：查询批次、任务及结果。
- `GET /api/files/download/{result_id}`：下载单张结果；加 `?inline=true` 用于预览。

## 检查与测试

后端：

```powershell
Set-Location backend
.\.venv\Scripts\Activate.ps1
pytest -q
alembic upgrade head --sql
```

前端：

```powershell
Set-Location frontend
npm run type-check
npm run lint
npm run build
```

## 配置与存储约定

所有运行配置从 `.env` 或环境变量读取。不要提交 `.env`，也不要在代码中保存密码、
API Key 或真实数据库地址。数据库中的媒体路径必须相对于 `STORAGE_ROOT`，例如
`outputs/image/123.png`，不能保存 Windows 绝对路径。

`FileStorageService` 会在应用启动时确保上传、输出和临时目录存在。

## 常见问题

**数据库连接失败**

确认已复制 `.env`、Compose 服务健康，且 `.env` 的 MySQL 用户、密码和端口与
容器配置一致。修改首次初始化后的 MySQL 密码变量不会自动修改数据卷中的账号；
开发阶段可手动更新账号，或在确认无重要数据后重建数据卷。

**Redis 或 Celery 无法连接**

先用 `docker compose ps` 确认 Redis 健康；检查 `REDIS_HOST`、`REDIS_PORT`
和 `REDIS_DB`。Windows Worker 应保留 `--pool=solo`。

**Node.js 构建警告或依赖安装失败**

当前依赖支持 Node.js 16，但推荐使用 Node.js 20 LTS。切换 Node 版本后删除本项目
`frontend/node_modules` 并重新执行 `npm install`。

**上传图片后无法提交**

提示词不能为空；仅接受扩展名与 MIME 类型都匹配的 JPG、JPEG、PNG；单张最大
10MB；参考生成最多 5 张，首帧图模式只能 1 张。任一任务失败会阻止整个批次。

## 下一阶段

建议在完成真实账号联调后增加任务取消、可控重试、并发锁、费用价格快照、限流、
监控和端到端浏览器测试，并根据实际额度设置并发与费用上限策略。
