# TikTok 运营制作：Windows + CentOS 7 虚拟机完整启动与真实验收手册

本文适用于以下真实部署拓扑：

```text
Windows 宿主机
├─ Vue 3 / Vite 前端
├─ FastAPI 后端
├─ Celery 图片 Worker
├─ Celery 视频 Worker
└─ storage 本地文件
        │
        │ VMware 虚拟网络
        ▼
CentOS 7 虚拟机
└─ Docker
   ├─ MySQL 8
   └─ Redis
```

目标是从完整停止状态启动 VMware、CentOS Docker 基础设施和 Windows 应用，并通过
浏览器逐项验收图片和视频业务。

> 真实 Provider 会产生费用。项目启动本身不会调用厂商；只有从页面提交生成任务时
> 才会调用。开始前请确认厂商余额、模型权限、限流规则和费用上限。

## 1. 项目路径与软件要求

本文默认项目位于：

```text
D:\work\tiktok\tiktok-operations-studio
```

在 Windows PowerShell 中进入项目根目录并检查应用运行环境：

```powershell
Set-Location D:\work\tiktok\tiktok-operations-studio
py -3.12 --version
node --version
npm --version
```

Windows 不需要安装或启动 Docker Desktop。建议使用 Python 3.12 和 Node.js 20
LTS。

启动 VMware 和 CentOS 7 后，在虚拟机终端检查：

```bash
docker --version
docker compose version
```

较旧的 CentOS Docker 环境可能使用独立命令：

```bash
docker-compose --version
```

后文以 `docker compose` 为例；如果虚拟机只有 `docker-compose`，将命令中的
`docker compose` 替换为 `docker-compose`。

如果 PowerShell 阻止项目脚本运行，可仅为当前窗口临时放开：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
```

项目应存在：

```text
backend\.venv
frontend\node_modules
```

如果 Python 虚拟环境不存在：

```powershell
Set-Location backend
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Set-Location ..
```

如果前端依赖不存在：

```powershell
Set-Location frontend
npm install
Set-Location ..
```

## 2. 配置 VMware 网络

### 2.1 获取 CentOS 虚拟机 IP

在 CentOS 执行：

```bash
hostname -I
ip -4 addr
```

记录 Windows 能访问的 IPv4 地址，本文用 `<CENTOS_VM_IP>` 表示，例如
`192.168.137.128`。建议在 VMware 中使用 Host-only、NAT 或 Bridged 网络，并为
虚拟机设置稳定地址或 DHCP 保留，避免重启后 IP 改变。

### 2.2 从 Windows 验证虚拟机

先测试主机可达：

```powershell
ping <CENTOS_VM_IP>
```

如果虚拟机策略禁止 ICMP，ping 失败不一定代表网络不通；启动容器后应以端口测试为准。

## 3. 正确配置两端 `.env`

### 3.1 CentOS Docker Compose 的 `.env`

CentOS 需要保存 `docker-compose.yml` 和它自己的 `.env`。例如：

```text
/opt/tiktok-operations-studio-infra/
├─ docker-compose.yml
└─ .env
```

可以从 Windows 把项目中的 Compose 文件复制到虚拟机：

```powershell
scp .\docker-compose.yml <CENTOS_USER>@<CENTOS_VM_IP>:/tmp/docker-compose.yml
```

然后在 CentOS 中创建基础设施目录、移动文件，并创建 `.env`：

```bash
sudo mkdir -p /opt/tiktok-operations-studio-infra
sudo mv /tmp/docker-compose.yml /opt/tiktok-operations-studio-infra/docker-compose.yml
sudo chown -R "$USER":"$USER" /opt/tiktok-operations-studio-infra
cd /opt/tiktok-operations-studio-infra
vi .env
```

CentOS 的 `.env` 至少包含：

```dotenv
MYSQL_PORT=3306
MYSQL_DATABASE=tiktok_operations
MYSQL_USER=tiktok
MYSQL_PASSWORD=请设置数据库业务用户密码
MYSQL_ROOT_PASSWORD=请设置不同的root密码
REDIS_PORT=6379
```

这个 `.env` 只供 CentOS Docker Compose 使用，不应保存 OpenAI 或火山方舟 Key。

### 3.2 Windows 后端 `.env`

路径：

```text
D:\work\tiktok\tiktok-operations-studio\backend\.env
```

Windows 的 FastAPI 和两个 Worker 都读取此文件。它必须同时包含虚拟机连接配置和
Provider 配置：

```dotenv
MYSQL_HOST=<CENTOS_VM_IP>
MYSQL_PORT=3306
MYSQL_DATABASE=tiktok_operations
MYSQL_USER=tiktok
MYSQL_PASSWORD=必须与CentOS的MYSQL_PASSWORD一致

REDIS_HOST=<CENTOS_VM_IP>
REDIS_PORT=6379
REDIS_DB=0

STORAGE_ROOT=../storage
IMAGE_WORKER_CONCURRENCY=2
VIDEO_WORKER_CONCURRENCY=1

VIDEO_PROVIDER=volcengine_ark
ARK_API_KEY=你的真实火山方舟API_Key
ARK_VIDEO_MODEL=doubao-seedance-2-0-mini-260615
ARK_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
ARK_REQUEST_TIMEOUT=60
ARK_VIDEO_POLL_INTERVAL=5
ARK_VIDEO_GENERATION_TIMEOUT=900
ARK_VIDEO_MAX_DOWNLOAD_MB=200
```

图片 Provider 根据测试目标二选一。

无费用的完整图片流程：

```dotenv
IMAGE_PROVIDER=mock
```

真实 OpenAI 图片调用：

```dotenv
IMAGE_PROVIDER=openai
OPENAI_API_KEY=你的OpenAI_API_Key
OPENAI_IMAGE_MODEL=gpt-image-2
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_REQUEST_TIMEOUT=180
```

ChatGPT Plus 与 OpenAI API 计费相互独立。API 平台没有余额时，真实图片请求可能
返回额度不足；这不影响 Mock 图片流程和火山视频流程。

`MYSQL_HOST` 和 `REDIS_HOST` 不能填写 `127.0.0.1`，因为数据库和 Redis 不在
Windows；必须填写 `<CENTOS_VM_IP>`。`STORAGE_ROOT` 保持 Windows 本地路径，因为
上传文件、图片结果和火山视频结果都由 Windows Worker 保存。

项目根目录 `.env` 对这种分机部署不是必需的。若根目录也存在 `.env`，后端会先读
根目录文件，再由 `backend\.env` 的同名值覆盖。建议把 Windows 应用配置统一放在
`backend\.env`，避免混淆。所有 `.env` 都不得提交到 Git。

### 3.3 安全确认配置

下面的命令只显示“密钥是否存在”，不会输出密钥：

```powershell
Set-Location backend
.\.venv\Scripts\python.exe -c "from app.core.config import Settings; s=Settings(); print({'image_provider': s.image_provider, 'video_provider': s.video_provider, 'openai_key_configured': bool(s.openai_api_key.strip()), 'ark_key_configured': bool(s.ark_api_key.strip()), 'ark_video_model': s.ark_video_model, 'database': f'{s.mysql_host}:{s.mysql_port}/{s.mysql_database}', 'redis': s.redis_url})"
Set-Location ..
```

视频部分预期包含：

```text
'video_provider': 'volcengine_ark'
'ark_key_configured': True
'ark_video_model': 'doubao-seedance-2-0-mini-260615'
```

输出中的 database 和 redis 地址应为 CentOS 虚拟机 IP，而不是 `127.0.0.1`。

## 4. 配置 CentOS 防火墙

MySQL 和 Redis 需要能被 Windows 访问，但不应暴露到公网。推荐使用 VMware
Host-only 网络，或用 firewalld 只允许 Windows 宿主机 IP。

在 Windows 查询 VMware 网卡地址：

```powershell
Get-NetIPAddress -AddressFamily IPv4 |
  Where-Object InterfaceAlias -Like "VMware*"
```

记录能访问虚拟机的 Windows 地址，本文用 `<WINDOWS_VMNET_IP>` 表示。在 CentOS
执行：

```bash
sudo firewall-cmd --permanent \
  --add-rich-rule='rule family="ipv4" source address="<WINDOWS_VMNET_IP>/32" port protocol="tcp" port="3306" accept'
sudo firewall-cmd --permanent \
  --add-rich-rule='rule family="ipv4" source address="<WINDOWS_VMNET_IP>/32" port protocol="tcp" port="6379" accept'
sudo firewall-cmd --reload
sudo firewall-cmd --list-all
```

不要把 3306、6379 转发到公网。当前 Redis 配置没有密码，必须限制在可信的 VMware
私有网络内。

## 5. 可选：启动前运行项目检查

建议首次真实验收前执行：

```powershell
powershell -ExecutionPolicy Bypass -File `
  .\.codex\skills\tiktok-operations-development\scripts\check-project.ps1
```

它会检查后端测试、Alembic、前端类型、Lint 和构建。标记为 `live` 的测试默认跳过，
不会调用 OpenAI 或火山方舟。

## 6. 在 CentOS 启动 MySQL 和 Redis

启动 VMware 和 CentOS 后，在虚拟机执行：

```bash
cd /opt/tiktok-operations-studio-infra
docker compose up -d mysql redis
docker compose ps
```

等待 `mysql` 和 `redis` 显示为 `healthy`。MySQL 首次启动可能需要 20～60 秒，
可以重复执行：

```bash
docker compose ps
```

查看基础设施日志：

```bash
docker compose logs --tail 100 mysql
docker compose logs --tail 100 redis
```

然后回到 Windows PowerShell，测试端口：

```powershell
Test-NetConnection <CENTOS_VM_IP> -Port 3306
Test-NetConnection <CENTOS_VM_IP> -Port 6379
```

两次输出都应显示：

```text
TcpTestSucceeded : True
```

如果容器 healthy 但 Windows 端口测试失败，优先检查 VMware 网络模式、CentOS IP、
firewalld 和端口映射。

## 7. 在 Windows 执行数据库迁移

每次拉取到新的迁移后都应执行；重复执行是安全的：

```powershell
Set-Location backend
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\alembic.exe current
Set-Location ..
```

`upgrade head` 成功且 `current` 显示最新 revision，表示数据库已准备好。

迁移命令会从 Windows 直接连接 CentOS MySQL。

## 8. 在 Windows 完整启动应用

准备 4 个独立 PowerShell 窗口。MySQL 和 Redis 已在 Docker 后台运行，不需要额外
占用窗口。

### 窗口 1：FastAPI 后端

```powershell
Set-Location D:\work\tiktok\tiktok-operations-studio
.\scripts\start-backend.ps1
```

正常时 Uvicorn 监听 `http://127.0.0.1:8000`。另开窗口验证：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health
```

预期返回 `status: ok`。浏览器还可以访问：

- 健康检查：`http://127.0.0.1:8000/api/health`
- Swagger：`http://127.0.0.1:8000/docs`

### 窗口 2：图片 Celery Worker

```powershell
Set-Location D:\work\tiktok\tiktok-operations-studio
.\scripts\start-image-worker.ps1
```

正常日志应显示 Redis 连接成功、监听 `image` 队列并进入 `ready`。即使当前只测试
视频，也建议启动图片 Worker，让整个项目保持完整运行。

### 窗口 3：视频 Celery Worker

```powershell
Set-Location D:\work\tiktok\tiktok-operations-studio
.\scripts\start-video-worker.ps1
```

正常日志应显示 Redis 连接成功、监听 `video` 队列并进入 `ready`。Provider 配置在
Worker 进程中读取；修改 `backend\.env` 后，必须按 `Ctrl+C` 停止并重新启动对应
Worker。

### 窗口 4：Vue 前端

```powershell
Set-Location D:\work\tiktok\tiktok-operations-studio\frontend
npm run dev
```

浏览器访问：

```text
http://localhost:5173
```

Vite 会把 `/api` 请求代理到 `http://127.0.0.1:8000`。

## 9. 开始付费测试前的快速检查

- CentOS 的 `docker compose ps` 中 MySQL、Redis 均为 healthy；
- Windows 到虚拟机的 3306、6379 端口测试成功；
- `/api/health` 返回 `{"status":"ok"}`；
- 图片 Worker 显示 ready；
- 视频 Worker 显示 ready；
- 前端页面可以打开；
- 浏览器开发者工具 Network 中没有持续的连接失败；
- `backend\.env` 的 Provider 与本轮测试目标一致。

## 10. 浏览器验收：图片功能

### 10.1 第一轮：Mock 成功闭环

先设置 `IMAGE_PROVIDER=mock` 并重启图片 Worker，然后：

1. 打开“生成图片”，保留默认任务卡；
2. 输入简单提示词；
3. 选择 `9:16`、数量 `1`；
4. 不上传参考图；
5. 提交并确认；
6. 观察 `PENDING` → `RUNNING` → `SUCCESS`；
7. 确认结果图片出现；
8. 下载并确认文件可打开。

这轮验证前端、API、MySQL、Redis、Celery、存储、轮询和下载，不产生厂商费用。

### 10.2 第二轮：上传与批量

继续使用 Mock：

1. 上传一张真实 JPG 或 PNG 并确认预览；
2. 新增第二张任务卡；
3. 输入不同提示词并选择不同比例、数量；
4. 批量提交；
5. 确认任务独立显示状态和结果；
6. 逐张下载。

上传规则：

- JPG、JPEG、PNG；
- 单张不超过 10MB；
- 每任务最多 5 张参考图；
- 一批最多 10 个任务。

### 10.3 第三轮：OpenAI 真实图片

只有确认 OpenAI API 已开通计费后，再设置 `IMAGE_PROVIDER=openai` 并重启图片
Worker。先做单任务、单图片测试。如果 API 平台没有余额，任务应正确显示
`OPENAI_BILLING_LIMIT_REACHED` 或 `OPENAI_QUOTA_EXCEEDED`；这属于真实错误链路
验证，不代表本地项目启动失败。

## 11. 浏览器验收：火山方舟真实视频

确认：

```dotenv
VIDEO_PROVIDER=volcengine_ark
ARK_API_KEY=你的真实密钥
ARK_VIDEO_MODEL=doubao-seedance-2-0-mini-260615
```

然后重启视频 Worker。

### 11.1 第一轮：最低成本文生视频

1. 打开“生成视频”，只保留一张任务卡；
2. 不上传参考图；
3. 输入简短、合规的提示词；
4. 选择 `480P`、固定时长 `5 秒`；
5. 选择 `9:16` 或 `16:9`；
6. 关闭声音；
7. 提交并确认。

示例提示词：

```text
一架纸飞机在整洁的白色桌面上缓慢滑行，柔和自然光，固定镜头，画面稳定。
```

预期流程：

- 前端任务进入 `PENDING`；
- Worker 领取后进入 `RUNNING`；
- Provider 创建火山任务并轮询；
- 成功后 Worker 下载 MP4 到本地；
- 前端轮询到 `SUCCESS` 并显示视频；
- 下载 MP4 后可以正常播放。

视频生成明显慢于图片。只要 Worker 仍在轮询且没有错误，不要重复提交。

### 11.2 第二轮：首帧图

1. 选择“首帧图”；
2. 上传且只上传 1 张 JPG/PNG；
3. 选择 480P、5 秒、关闭声音；
4. 提交；
5. 确认生成结果与首帧主体或构图有关；
6. 下载并播放。

缺图或上传多张时，前端或后端应阻止提交。

### 11.3 第三轮：参考生成

1. 选择“参考生成”；
2. 先上传 1～2 张参考图；
3. 在提示词中明确参考的主体、风格或场景；
4. 提交并检查结果；
5. 第一轮不建议直接使用 5 张图，以便控制请求大小和排查难度。

### 11.4 第四轮：参数与批次

前三轮成功后，再逐项测试：

- 720P；
- 10 秒；
- 15 秒；
- 开启声音；
- 两个任务组成一个批次；
- 一个成功、一个失败时的批次状态；
- 页面预览和单文件下载。

不要一次组合所有高成本参数。每轮只改变一个变量，更便于定位问题并控制费用。

## 12. 完整验收清单

### 基础设施

- [ ] MySQL healthy
- [ ] Redis healthy
- [ ] Alembic 位于 head
- [ ] FastAPI health 正常
- [ ] 图片 Worker ready
- [ ] 视频 Worker ready
- [ ] Vue 页面正常加载

### 图片

- [ ] 默认任务卡、添加和删除正常
- [ ] 最多 10 张卡限制正常
- [ ] JPG/PNG 上传和预览正常
- [ ] 非图片、超大图片被拒绝
- [ ] 比例与数量 1/2/4 正常
- [ ] Mock 单任务和批量成功
- [ ] 图片预览、下载正常
- [ ] OpenAI 真实成功或正确显示计费错误

### 视频

- [ ] 文生视频成功
- [ ] 首帧图只能上传一张
- [ ] 参考图模式正常
- [ ] 480P 和 720P 按计划验证
- [ ] 5/10/15 秒按计划验证
- [ ] 声音开关按计划验证
- [ ] 批量提交与状态轮询正常
- [ ] MP4 页面播放、下载正常
- [ ] 厂商错误显示稳定错误码

## 13. 日志和文件位置

实时日志：

- FastAPI 请求：后端窗口；
- 图片执行：图片 Worker；
- 火山任务创建与状态：视频 Worker；
- 前端编译和代理：Vite；
- MySQL/Redis：CentOS 中的 `docker compose logs`。

本地文件：

```text
storage\uploads\image
storage\uploads\video
storage\outputs\image
storage\outputs\video
storage\temp
```

数据库只保存相对路径。火山视频 URL 可能过期，所以 Provider 会在成功后立即下载到
`storage\outputs\video`。

## 14. 常见故障

### CentOS Docker Compose 提示缺少 MYSQL 变量

确认 `/opt/tiktok-operations-studio-infra/.env` 存在，并且在同一目录中执行
`docker compose`。

### MySQL 显示 Access denied

确认 CentOS `.env` 与 Windows `backend\.env` 的数据库名、用户名和密码一致。
MySQL 数据卷首次创建后，修改 `.env` 不会自动修改数据卷里的既有密码。

不要为了排错直接执行 `docker compose down -v`，它会删除数据库数据。应先确认
是否有需要保留的数据，再决定更新用户密码或重建开发数据卷。

### Redis 连接失败

```powershell
Test-NetConnection <CENTOS_VM_IP> -Port 6379
```

同时在 CentOS 检查：

```bash
cd /opt/tiktok-operations-studio-infra
docker compose ps
docker compose logs --tail 100 redis
```

### 页面提交后一直 PENDING

通常是 Worker 未启动或队列错误：

- 图片任务需要 `start-image-worker.ps1`；
- 视频任务需要 `start-video-worker.ps1`。

同时检查 Worker 是否成功连接 Redis。

### 火山 Provider 错误

- `ARK_API_KEY_MISSING`：Key 未被 Worker 读取，保存配置后重启 Worker；
- `ARK_MODEL_NOT_FOUND`：检查模型 ID 和当前项目的模型权限；
- `ARK_AUTH_ERROR`：检查 Key、项目归属和权限；
- `ARK_QUOTA_EXCEEDED`：检查余额或配额；
- `ARK_RATE_LIMITED`：降低并发并稍后重试；
- `ARK_CONTENT_SAFETY_BLOCKED`：更换合规提示词或素材；
- `ARK_GENERATION_TIMEOUT`：先到方舟控制台确认原任务状态，不要立即重复付费提交。

本机视频 Worker 默认并发 1，适合真实联调。

### 视频成功但页面无法播放

检查：

1. `storage\outputs\video` 是否存在 MP4；
2. 浏览器 Network 中预览接口是否为 200；
3. 后端是否出现 `RESULT_FILE_NOT_FOUND`；
4. 不要手动移动数据库已经记录的输出文件。

### Windows 无法连接虚拟机端口

按顺序检查：

1. VMware 和 CentOS 是否正在运行；
2. `<CENTOS_VM_IP>` 是否在重启后改变；
3. MySQL、Redis 容器是否 healthy；
4. `docker-compose.yml` 是否映射 3306 和 6379；
5. CentOS firewalld 是否允许 Windows VMware 网卡地址；
6. VMware 网络模式是否允许宿主机访问虚拟机。

### Windows 应用端口被占用

```powershell
Get-NetTCPConnection -LocalPort 8000,5173 `
  -ErrorAction SilentlyContinue
```

Windows 本机只需要 FastAPI 8000 和 Vite 5173。MySQL 3306 与 Redis 6379 位于
CentOS 虚拟机。

## 15. 正确停止项目

先在 Windows 依次停止 Vite、视频 Worker、图片 Worker和 FastAPI。然后进入 CentOS：

```bash
cd /opt/tiktok-operations-studio-infra
docker compose stop
```

确认容器停止后再关闭 CentOS 和 VMware。`docker compose stop` 会保留数据卷；
不要把 `docker compose down -v` 当作日常停止方式，其中 `-v` 会删除数据卷。

## 16. 日常启动速查

第一步，启动 VMware 和 CentOS，在 CentOS 执行：

```bash
cd /opt/tiktok-operations-studio-infra
docker compose up -d mysql redis
docker compose ps
```

第二步，在 Windows 确认远程基础设施：

```powershell
Test-NetConnection <CENTOS_VM_IP> -Port 3306
Test-NetConnection <CENTOS_VM_IP> -Port 6379
```

第三步，在 Windows 四个窗口分别执行：

```powershell
.\scripts\start-backend.ps1
```

```powershell
.\scripts\start-image-worker.ps1
```

```powershell
.\scripts\start-video-worker.ps1
```

```powershell
Set-Location frontend
npm run dev
```

最后访问 `http://localhost:5173`。
