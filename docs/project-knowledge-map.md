# ai-engine 项目知识总纲

本文件只维护学习进度，不复述知识点内容。知识点讲解、考题、作答与批改原文统一归档在 `docs/lessons/` 目录。

## 学习进度

状态：`未开始` / `进行中` / `已完成`，`进行中` 同时最多一个。
来源：`课程存档`、`代码改进点`、`推荐方向`、`代码扫描`、`依赖升级`。
`已完成` 必须挂接 `lessons/` 下的课程文档（表格中为可点击链接）。
表顺序即学习顺序，调整顺序用 `scripts/progress.py move`；表格由项目技能 `knowledge-learning` 读写，请勿手工调整列顺序。
新增知识点只在表中追加一行；学完后把状态改为 `已完成` 并挂接对应课程文档。

| ID | 知识点 | 状态 | 来源 | 课程文档 | 最近更新 |
| --- | --- | --- | --- | --- | --- |
| pyproject-packaging | pyproject.toml 与 Python 项目打包 | 已完成 | 课程存档 | [01-pyproject-packaging](lessons/01-pyproject-packaging.md) | 2026-11-05 |
| modules-packages-imports | Python 包、模块与导入机制 | 已完成 | 课程存档 | [02-modules-packages-imports](lessons/02-modules-packages-imports.md) | 2026-11-05 |
| lifespan-resource-lifecycle | lifespan 与资源生命周期 | 已完成 | 课程存档 | [03-lifespan-resource-lifecycle](lessons/03-lifespan-resource-lifecycle.md) | 2026-11-05 |
| fastapi-depends | FastAPI 依赖注入 Depends | 已完成 | 课程存档 | [04-fastapi-depends](lessons/04-fastapi-depends.md) | 2026-11-05 |
| contextvar | ContextVar 与异步上下文隔离 | 已完成 | 课程存档 | [05-contextvar](lessons/05-contextvar.md) | 2026-11-05 |
| pydantic-model-boundaries | Pydantic 模型边界、字段声明与约束 | 已完成 | 课程存档 | [06-pydantic-model-boundaries](lessons/06-pydantic-model-boundaries.md) | 2026-11-05 |
| pydantic-validators-config | Pydantic 校验器、ValidationError 与 ConfigDict | 已完成 | 课程存档 | [07-pydantic-validators-config](lessons/07-pydantic-validators-config.md) | 2026-11-05 |
| pydantic-serialization-schema | Pydantic 序列化、Schema、判别联合与 TypeAdapter | 已完成 | 课程存档 | [08-pydantic-serialization-schema](lessons/08-pydantic-serialization-schema.md) | 2026-11-05 |
| pydantic-settings | pydantic-settings 与配置管理 | 已完成 | 课程存档 | [09-pydantic-settings](lessons/09-pydantic-settings.md) | 2026-11-05 |
| fastapi-request-response | FastAPI 请求、响应与异常边界 | 已完成 | 课程存档 | [10-fastapi-request-response](lessons/10-fastapi-request-response.md) | 2026-11-05 |
| sse-async-generators | SSE、异步生成器与流式取消 | 已完成 | 课程存档 | [11-sse-async-generators](lessons/11-sse-async-generators.md) | 2026-11-05 |
| asyncio-tasks-cancellation | asyncio 任务生命周期、取消、结构化并发与超时 | 已完成 | 课程存档 | [12-asyncio-tasks-cancellation](lessons/12-asyncio-tasks-cancellation.md) | 2026-11-05 |
| async-iteration-protocol | 异步迭代协议、异步生成器与 async for | 已完成 | 课程存档 | [13-async-iteration-protocol](lessons/13-async-iteration-protocol.md) | 2026-11-05 |
| decorators | Python 装饰器与异步装饰器 | 已完成 | 课程存档 | [14-decorators](lessons/14-decorators.md) | 2026-11-05 |
| exceptions | Python 异常体系与错误边界 | 已完成 | 课程存档 | [15-exceptions](lessons/15-exceptions.md) | 2026-11-05 |
| typing-generics | Python 类型系统与泛型 | 已完成 | 课程存档 | [16-typing-generics](lessons/16-typing-generics.md) | 2026-11-05 |
| context-managers | 上下文管理器、ExitStack 与 AsyncExitStack | 已完成 | 课程存档 | [17-context-managers](lessons/17-context-managers.md) | 2026-11-05 |
| httpx | HTTPX、连接池、超时、重试与流式请求 | 已完成 | 课程存档 | [18-httpx](lessons/18-httpx.md) | 2026-11-05 |
| pytest-async | pytest 与异步测试 | 已完成 | 课程存档 | [19-pytest](lessons/19-pytest.md) | 2026-11-05 |
| fastapi-asgi-lifecycle | FastAPI / ASGI 请求生命周期与响应边界 | 已完成 | 课程存档 | [20-fastapi-asgi-request-lifecycle](lessons/20-fastapi-asgi-request-lifecycle.md) | 2026-11-05 |
| logging-tracing | 日志、追踪与可观测性 | 已完成 | 推荐方向 | [21-observability-logging-tracing](lessons/21-observability-logging-tracing.md) | 2026-11-05 |
| security | 安全威胁建模与信任边界 | 进行中 | 推荐方向 | [22-security](lessons/22-security.md) | 2026-11-05 |
| concurrency-backpressure | 并发队列、限流与背压 | 未开始 | 推荐方向 | - | - |
| architecture-boundaries | 架构边界与依赖倒置 | 未开始 | 推荐方向 | - | - |
| code-review-refactor | 综合代码审查与小型重构 | 未开始 | 推荐方向 | - | - |
| token-budget-guard | TokenBudgetGuard 的设计与实现 | 未开始 | 代码改进点 | - | - |
| sse-disconnect | SSE 断连处理与 aclosing 收尾 | 未开始 | 代码改进点 | - | - |
| error-taxonomy | 异常分类重构：从宽泛捕获到领域异常 | 未开始 | 代码改进点 | - | - |
| retry-scope | 重试范围、幂等性与 Retry-After | 未开始 | 代码改进点 | - | - |
| exitstack-cancel | AsyncExitStack 取消回滚与资源泄漏 | 未开始 | 代码改进点 | - | - |
