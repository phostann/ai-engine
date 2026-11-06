# AI Engine

基于 FastAPI 的异步大模型网关，包含：

- OpenAI 兼容的流式聊天接口
- SSE 流式响应
- Pydantic 请求与响应校验
- Pydantic Settings 配置管理
- HTTPX 连接池、超时和重试
- asyncio 并发、取消和资源生命周期管理
- ContextVar 请求追踪
- pytest 异步测试

## 快速开始

```powershell
uv sync
uv run ai-engine
```

服务启动后访问：

```text
GET http://127.0.0.1:8000/health
```

## 常用命令

```powershell
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

## 学习文档

- [项目知识总纲](docs/project-knowledge-map.md)

只记录各知识点的学习进度（未开始 / 进行中 / 已完成）与对应课程文档，不重复课程内容。

- 课程原文：`docs/lessons/NN-*.md`

每次课程的讲解、考题、作答与批改原文，按序号归档。
