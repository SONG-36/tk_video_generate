# 后端

从项目根目录复制 `.env.example` 为 `.env`，进入本目录创建 Python 3.12
虚拟环境并安装 `requirements.txt`。开发服务器使用
`uvicorn app.main:app --reload` 启动，API 文档位于 `/docs`。

图片业务默认使用 Mock Provider。设置 `IMAGE_PROVIDER=openai`、
`OPENAI_API_KEY` 和 `OPENAI_IMAGE_MODEL` 后，图片 Worker 才会请求 OpenAI。
数据库升级使用 `alembic upgrade head`，不要使用 `create_all` 代替迁移。
