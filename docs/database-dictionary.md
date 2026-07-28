# TikTok 运营制作数据库字典

## 一、快速理解

数据库围绕“批次 → 任务 → 参数、素材、结果、用量”组织：

```text
generation_batch（一次批量提交）
└─ generation_task（批次中的一张任务卡）
   ├─ image_generation_task_detail（图片参数，图片任务才有）
   ├─ video_generation_task_detail（视频参数，视频任务才有）
   ├─ task_reference_image（参考图片，可有多张）
   ├─ generation_result（生成文件，可有多条）
   └─ provider_usage（厂商用量与费用，最多一条）
```

关键规则：

- 一个批次包含 1～10 个任务；
- 一张前端任务卡对应一条 `generation_task`；
- 图片任务只关联 `image_generation_task_detail`；
- 视频任务只关联 `video_generation_task_detail`；
- 一张参考图对应一条 `task_reference_image`；
- 一张生成图片对应一条 `generation_result`；
- 一个视频任务成功后通常只有一条视频结果；
- 任务重新执行时会删除旧 `generation_result`，不保留结果历史；
- 厂商没有返回 usage 时，`provider_usage.usage_source` 为 `UNKNOWN`，不会伪造 Token
  或金额。

`alembic_version` 是 Alembic 自己维护的迁移版本表，不属于业务数据。

## 二、表关系

| 表 | 用途 | 主要关系 |
|---|---|---|
| `generation_batch` | 一次批量提交的汇总记录 | 一对多 `generation_task` |
| `generation_task` | 每张图片/视频任务卡的公共信息与执行状态 | 属于批次，是其余业务表的中心 |
| `image_generation_task_detail` | 图片比例、数量、格式 | 与图片任务一对一 |
| `video_generation_task_detail` | 视频参考模式、分辨率、比例、时长、声音 | 与视频任务一对一 |
| `task_reference_image` | 图片或视频任务上传的参考图 | 与任务多对一 |
| `generation_result` | 本地生成结果文件 | 与任务多对一 |
| `provider_usage` | 厂商用量和费用 | 与任务一对一 |

## 三、字段说明

### 1. `generation_batch`

一次点击“批量提交”创建一条。

| 字段 | 含义 |
|---|---|
| `id` | 批次主键 |
| `batch_type` | `IMAGE` 图片批次；`VIDEO` 视频批次 |
| `status` | `PENDING`、`RUNNING`、`SUCCESS`、`PARTIAL_SUCCESS`、`FAILED` |
| `total_tasks` | 批次任务总数 |
| `success_tasks` | 成功任务数 |
| `failed_tasks` | 失败任务数 |
| `created_at` | 创建时间 |
| `updated_at` | 最后更新时间 |

`PARTIAL_SUCCESS` 表示同一批次中既有成功任务又有失败任务。

### 2. `generation_task`

图片与视频共用的任务主表。提示词、Provider、状态和错误都在这里。

| 字段 | 含义 |
|---|---|
| `id` | 任务主键 |
| `batch_id` | 所属批次 |
| `task_type` | `IMAGE` 或 `VIDEO` |
| `status` | `PENDING`、`RUNNING`、`SUCCESS`、`FAILED` |
| `prompt` | 用户提交的提示词 |
| `provider` | 实际执行的 Provider，例如 `mock`、`openai`、`volcengine_ark` |
| `model` | 实际调用的模型 ID |
| `provider_task_id` | 厂商请求 ID 或异步任务 ID，排查厂商问题时使用 |
| `error_code` | 项目标准化错误码 |
| `error_message` | 失败原因摘要 |
| `started_at` | Worker 开始执行时间 |
| `finished_at` | 成功或失败的结束时间 |
| `created_at` | 创建时间 |
| `updated_at` | 最后更新时间 |

任务刚创建时 Provider 相关字段可以为空；Worker 真正执行后才会填写。

### 3. `image_generation_task_detail`

只有图片任务存在该记录，`task_id` 唯一。

| 字段 | 含义 |
|---|---|
| `id` | 图片参数记录主键 |
| `task_id` | 对应 `generation_task.id` |
| `aspect_ratio` | `PORTRAIT_9_16`、`PORTRAIT_3_4`、`SQUARE_1_1` |
| `image_count` | 生成数量：1、2 或 4 |
| `output_format` | 当前固定为 `PNG` |

### 4. `video_generation_task_detail`

只有视频任务存在该记录，`task_id` 唯一。

| 字段 | 含义 |
|---|---|
| `id` | 视频参数记录主键 |
| `task_id` | 对应 `generation_task.id` |
| `reference_mode` | `REFERENCE` 参考生成；`FIRST_FRAME` 首帧图 |
| `resolution` | `P480` 或 `P720`，业务上显示为 480P/720P |
| `aspect_ratio` | `LANDSCAPE_16_9` 或 `PORTRAIT_9_16` |
| `duration_mode` | `FIXED` 固定时长；`SMART` 智能时长 |
| `fixed_duration` | 固定模式为 5、10、15；智能模式为空 |
| `output_sound` | 是否要求生成同步声音 |
| `output_format` | 当前固定为 `MP4` |

### 5. `task_reference_image`

图片任务与视频任务共用。一张上传图片保存一条记录。

| 字段 | 含义 |
|---|---|
| `id` | 参考图主键 |
| `task_id` | 所属任务 |
| `file_path` | 相对 `STORAGE_ROOT` 的路径，不是 Windows 绝对路径 |
| `file_name` | 用户上传时的原始文件名 |
| `file_size` | 字节数 |
| `mime_type` | 校验后的类型，例如 `image/png` |
| `created_at` | 上传记录创建时间 |

删除任务时，参考图数据库记录会级联删除。实际文件由业务服务按流程维护。

### 6. `generation_result`

一条记录只代表一个生成文件，不把多个文件塞进同一字段。

| 字段 | 含义 |
|---|---|
| `id` | 结果主键，也是下载接口使用的 `result_id` |
| `task_id` | 所属任务 |
| `result_type` | `IMAGE` 或 `VIDEO` |
| `file_path` | 相对 `STORAGE_ROOT` 的文件路径 |
| `file_name` | 浏览器下载时使用的名称 |
| `file_size` | 字节数 |
| `created_at` | 结果保存时间 |

下载接口：

```text
GET /api/files/download/{result_id}
```

图片任务生成 4 张图片时会有 4 条结果；视频任务通常有 1 条。任务重跑会替换旧结果。

### 7. `provider_usage`

每个任务最多一条，用于记录厂商 usage 和后续费用核算。

| 字段 | 含义 |
|---|---|
| `id` | 用量记录主键 |
| `task_id` | 对应任务，唯一 |
| `provider` | Provider 名称 |
| `model` | 模型 ID |
| `input_tokens` | 厂商返回的输入 Token |
| `output_tokens` | 厂商返回的输出 Token |
| `total_tokens` | 厂商返回的总 Token |
| `billing_unit` | 计费单位，如 token、image、second |
| `billing_quantity` | 计费用量 |
| `unit_price` | 单价 |
| `original_currency` | 原始币种，如 USD、CNY |
| `original_amount` | 原始币种金额 |
| `exchange_rate` | 换算人民币的汇率 |
| `amount_cny` | 人民币金额 |
| `usage_source` | `PROVIDER`、`LOCAL_CALCULATION`、`UNKNOWN` |
| `pricing_snapshot` | 当时使用的价格规则 JSON 快照 |
| `created_at` | 创建时间 |

当前阶段厂商没有提供的数据保持为空，不进行推测。

## 四、常用排查 SQL

查看最近的批次：

```sql
SELECT id, batch_type, status, total_tasks, success_tasks, failed_tasks, created_at
FROM generation_batch
ORDER BY id DESC
LIMIT 20;
```

查看某批次的任务：

```sql
SELECT id, batch_id, task_type, status, provider, model,
       provider_task_id, error_code, error_message, started_at, finished_at
FROM generation_task
WHERE batch_id = 你的批次ID
ORDER BY id;
```

查看某任务的参考图与结果：

```sql
SELECT id, task_id, file_name, file_path, file_size
FROM task_reference_image
WHERE task_id = 你的任务ID;

SELECT id, task_id, result_type, file_name, file_path, file_size
FROM generation_result
WHERE task_id = 你的任务ID;
```

查看某任务的厂商用量：

```sql
SELECT task_id, provider, model, input_tokens, output_tokens, total_tokens,
       usage_source, original_amount, original_currency, amount_cny
FROM provider_usage
WHERE task_id = 你的任务ID;
```

## 五、让数据库客户端显示新注释

代码中的注释由 Alembic `0004` 迁移写入 MySQL。Windows 后端正确连接 CentOS
MySQL 后执行：

```powershell
Set-Location D:\work\tiktok\tiktok-operations-studio\backend
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\alembic.exe current
```

迁移成功后，在数据库客户端中刷新表结构或重新连接，即可看到表注释和字段注释。

