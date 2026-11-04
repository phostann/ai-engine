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

- [Python / FastAPI 项目知识地图](docs/python-fastapi-knowledge-map.md)

该文档按知识点整理了项目涉及的类型系统、装饰器、上下文管理、asyncio、
FastAPI、Pydantic、HTTPX 和异步测试，并记录了当前代码的改进方向。
