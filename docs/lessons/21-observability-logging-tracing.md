# 日志、追踪与可观测性（待复测）

> 本文逐字转录自原始课程对话，只添加角色标题和来源信息，未改写、删减或二次总结。
>
- 返回：[课程原文索引](README.md)
- 原始消息序号：`3257`、`3312`、`3319`、`3324`、`3331`、`3336`

## 用户（原始消息 3257）

继续下一科

## 助手（原始消息 3312）

**本课知识点：日志、追踪与可观测性**

前面已经学过：

- `ContextVar` 如何隔离请求上下文
- `trace_id` 如何通过 FastAPI 依赖注入
- lifespan 如何管理全局资源
- HTTPX 如何请求上游服务
- SSE 如何持续输出响应

这一课把这些内容组合起来，回答一个生产问题：

> 线上出现异常时，如何快速知道“哪个请求、在哪个阶段、因为什么、耗时多久、影响了什么”？

---

## 1. 可观测性的三大支柱

通常把可观测性分成三类信号：

```text
Logs    日志：离散事件
Metrics 指标：可聚合数值
Traces  追踪：请求跨服务、跨阶段的调用链
```

### Logs

日志适合回答：

- 某个错误具体是什么
- 哪个请求失败了
- 某个分支是否执行
- 上游返回了什么状态
- 重试了几次

例如：

```text
请求 req-123 调用上游模型超时，重试 2 次后失败
```

### Metrics

指标适合回答：

- QPS 是多少
- P95 延迟是多少
- 错误率是否升高
- 当前并发连接有多少
- 429 的比例是否异常

例如：

```text
http_requests_total{status="500"} = 120
http_request_duration_seconds{p95} = 2.4
```

指标不应该保存每个请求的完整文本，因为基数会爆炸。

### Traces

追踪适合回答：

- 一个请求经过了哪些服务
- 每个阶段耗时多少
- 请求 A 调用了哪个上游请求 B
- 时间主要消耗在网关、上游模型还是数据库

一个 trace 通常包含多个 span：

```text
HTTP 请求 trace_id=abc
├── middleware span
├── route span
├── dependency span
├── upstream HTTP span
└── SSE stream span
```

当前项目只有 `trace_id`，还没有完整的 span 体系。这是从“请求级日志关联”走向“分布式追踪”的下一步。

---

## 2. 为什么不能继续用 `print`

项目里目前还有一些 `print`：

- `src/ai_engine/core/decorators.py`
- `src/ai_engine/core/context.py`

例如：

```python
print(f"⏱️ [Trace] 函数 {func.__name__} 执行耗时: {elapsed:.2f} ms")
```

它的问题不是“不能输出”，而是无法进入统一日志系统：

- 没有日志级别
- 没有 logger 名称
- 没有 handler
- 没有 formatter
- 没有 trace_id
- 不能按环境调整级别
- 不能被日志采集器统一解析
- 不能通过 `caplog` 测试
- 不能输出异常堆栈
- 不能方便地输出 JSON 字段
- 不能统一脱敏

`print` 适合临时调试，不适合服务端生产日志。

---

## 3. Python logging 的核心模型

Python 日志系统可以简化成：

```text
Logger
    ↓
LogRecord
    ↓
Handler
    ↓
Formatter
    ↓
输出位置
```

### Logger

Logger 是日志入口：

```python
import logging

logger = logging.getLogger("ai_engine")
```

项目中使用：

```python
logger = logging.getLogger("ai_engine")
```

实际模块可以使用更具体的名称：

```python
logger = logging.getLogger(__name__)
```

例如：

```text
ai_engine.api.v1.chat
ai_engine.core.http_client
ai_engine.services.llm_client
```

这样可以通过 logger 名称过滤日志：

```python
logging.getLogger("ai_engine.core.http_client").setLevel(logging.DEBUG)
```

### LogRecord

调用：

```python
logger.info("开始处理请求")
```

时，logging 会创建一条 `LogRecord`，其中包含：

- 时间
- 级别
- logger 名称
- 消息
- 文件名
- 行号
- 线程信息
- 异常信息
- `extra` 添加的自定义字段

项目的 `TraceIdFilter` 就是给 `LogRecord` 注入：

```python
record.trace_id = _trace_id_var.get("system")
```

### Handler

Handler 决定日志最终写到哪里：

```python
logging.StreamHandler(sys.stdout)
logging.FileHandler("app.log")
logging.handlers.RotatingFileHandler(...)
```

容器环境通常优先写到 stdout，由 Docker、Kubernetes 或日志采集器收集。

### Formatter

Formatter 决定日志格式：

```python
logging.Formatter(
    "[%(asctime)s] [%(levelname)s] [%(trace_id)s] %(name)s: %(message)s"
)
```

如果 formatter 引用了：

```text
%(trace_id)s
```

但某个 handler 对应的 LogRecord 没有 `trace_id` 属性，格式化时就会报错。

---

## 4. Logger 层级、传播与有效级别

Logger 名称是点分层级的：

```text
ai_engine
ai_engine.api
ai_engine.api.v1
ai_engine.api.v1.chat
```

`ai_engine.api.v1.chat` 是 `ai_engine.api.v1` 的子 logger。

### 有效级别

如果 `ai_engine` 没有设置 level，它会向上查找父 logger，直到找到有效级别。

例如 root 设置为 `INFO`：

```python
logging.getLogger().setLevel(logging.INFO)
```

那么：

```python
logger = logging.getLogger("ai_engine")
logger.debug("不会输出")
logger.info("会输出")
```

### propagation

默认情况下，子 logger 处理完自己的 handler 后，还会把 record 传给父 logger：

```python
logger.propagate = True
```

所以如果 root 上挂了 handler，`ai_engine` 的日志会传到 root handler。

项目当前依赖这个机制：

```text
logger = logging.getLogger("ai_engine")
    ↓
没有自己的 handler
    ↓
propagate=True
    ↓
root handler 输出日志
```

### 重复输出

如果同时做了：

```text
ai_engine 自己的 handler
+
propagate=True
+
root 也有 handler
```

就可能输出两次。

常见修复是：

```python
logger.propagate = False
```

但只有在明确需要隔离 logger 时才这样做。

---

## 5. Handler、Filter、Formatter 的执行关系

对一条日志，大致顺序是：

```text
logger.info(...)
    ↓
创建 LogRecord
    ↓
level 判断
    ↓
logger filters
    ↓
交给 handler
    ↓
handler filters
    ↓
formatter 格式化
    ↓
写入目标
```

项目的 `TraceIdFilter` 是挂在 handler 上的：

```python
handler.addFilter(TraceIdFilter())
```

因此每条交给该 handler 的记录，在格式化前都会获得：

```python
record.trace_id = ...
```

### 当前实现的一个潜在问题

`logger.py` 中的类型注解是：

```python
def filter(self, record: LogRecord) -> bool | LogRecord:
```

`logging.Filter.filter()` 通常应返回布尔值：

- `True`：允许通过
- `False`：过滤掉

虽然当前运行可能正常，但返回类型表达不够准确，建议改成：

```python
def filter(self, record: LogRecord) -> bool:
    record.trace_id = _trace_id_var.get("system")
    return True
```

---

## 6. 日志级别如何选

常见级别：

```text
DEBUG
INFO
WARNING
ERROR
CRITICAL
```

### DEBUG

适合：

- 详细分支
- 请求内部状态
- 重试细节
- 临时诊断信息

不要在生产默认打开大量 DEBUG。

### INFO

适合：

- 服务启动
- 请求开始或结束
- 配置加载完成
- 连接池初始化
- 流式会话完成

### WARNING

适合：

- 客户端断开
- 可恢复的重试
- 接近限制
- 降级行为

例如：

```python
logger.warning("客户端断开，已停止推流")
```

### ERROR

适合：

- 当前请求失败
- 上游不可恢复错误
- 数据校验后仍发生的业务错误
- 关键依赖不可用

### CRITICAL

适合：

- 进程无法继续运行
- 关键基础设施完全不可用

不要把所有异常都打成 ERROR 或 CRITICAL，否则告警会失去意义。

---

## 7. `logger.error` 与 `logger.exception`

错误写法：

```python
try:
    ...
except Exception as exc:
    logger.error(f"请求失败: {exc}")
```

它只记录了字符串，通常没有完整 traceback。

更推荐：

```python
try:
    ...
except Exception:
    logger.exception("请求处理失败")
```

`logger.exception()` 等价于：

```python
logger.error("请求处理失败", exc_info=True)
```

它会保留：

- 异常类型
- 异常消息
- traceback
- 调用栈

但注意：`logger.exception()` 应该放在 `except` 块内。

如果要在其他位置记录已有异常，可以使用：

```python
logger.error("请求处理失败", exc_info=exc)
```

或者：

```python
logger.error(
    "请求处理失败",
    exc_info=(type(exc), exc, exc.__traceback__),
)
```

### 项目中的一个问题

当前 `chat.py` 中：

```python
logger.exception(f"流式推流中途发生不可逆异常: {exc}")
```

这通常会同时把异常文本写进 message，又通过 traceback 再输出一次。

更好的写法：

```python
logger.exception("流式推流中途发生不可逆异常")
```

让异常信息由 `exc_info` 负责输出。

---

## 8. 结构化日志

当前项目输出的是文本格式：

```text
[2026-11-05 12:00:00] [INFO] [req-123] ai_engine...: 请求开始
```

开发环境可读性不错，但生产环境通常更适合 JSON 日志：

```json
{
  "timestamp": "2026-11-05T04:00:00Z",
  "level": "INFO",
  "logger": "ai_engine.api.v1.chat",
  "trace_id": "req-123",
  "message": "request_finished",
  "method": "POST",
  "path": "/api/v1/chat/completions/stream",
  "status_code": 200,
  "duration_ms": 842.3
}
```

结构化日志的好处：

- 日志系统可按字段查询
- 可以过滤 `trace_id`
- 可以统计 `duration_ms`
- 可以按 `status_code` 聚合
- 可以避免用正则解析自然语言
- 可以统一脱敏

### `extra` 的使用

可以这样添加字段：

```python
logger.info(
    "upstream_request",
    extra={
        "method": "POST",
        "path": "/chat/completions",
        "attempt": 1,
    },
)
```

但这些字段只有 formatter 或 JSON formatter 配置后才会显示。

### `extra` 的保留字段冲突

不要使用 logging 已占用的字段名：

```python
extra={"name": ...}       # 可能冲突
extra={"message": ...}    # 可能冲突
extra={"levelname": ...}  # 可能冲突
```

更安全的字段名：

```text
trace_id
request_id
span_id
method
path
status_code
duration_ms
attempt
upstream_status
error_code
```

---

## 9. trace_id 的作用

`trace_id` 用来把同一次请求的多条日志关联起来。

例如：

```text
[INFO] [req-a1b2] 请求进入
[INFO] [req-a1b2] 开始调用上游模型
[WARNING] [req-a1b2] 上游超时，准备重试
[INFO] [req-a1b2] 重试成功
[INFO] [req-a1b2] SSE 流结束
```

没有 trace_id 时，多条并发请求的日志会混在一起：

```text
开始调用上游模型
开始处理流式会话
上游超时
客户端断开
...
```

有了 trace_id，才能还原：

```text
req-a1b2：上游超时 → 重试 → 完成
req-c3d4：客户端断开 → 停止推流
```

---

## 10. 当前项目的 trace_id 链路

项目使用：

```python
_trace_id_var: ContextVar[str] = ContextVar("trace_id", default="system")
```

依赖中：

```python
TraceIdDep = Annotated[
    str,
    Depends(get_request_trace_id, use_cache=True),
]
```

`get_request_trace_id` 做三件事：

1. 从 `X-Trace-ID` 请求头读取
2. 没有就生成新的 trace_id
3. 设置到 ContextVar，并在请求结束时重置

日志过滤器中：

```python
record.trace_id = _trace_id_var.get("system")
```

链路大致是：

```text
X-Trace-ID
    ↓
get_request_trace_id
    ↓
ContextVar.set()
    ↓
日志 Filter 读取
    ↓
LogRecord.trace_id
    ↓
Formatter 输出
```

---

## 11. 为什么有时中间件日志没有 trace_id

这是本课最重要的项目问题之一。

FastAPI 请求大致经过：

```text
middleware
    ↓
路由匹配
    ↓
依赖解析
    ↓
get_request_trace_id
    ↓
路由函数
```

如果 trace_id 是在**路由依赖**中设置的，那么位于它之前的中间件日志可能看到默认值：

```text
system
```

而不是请求真实的 trace_id。

因此需要区分目标：

### 只要求业务路由日志有 trace_id

当前依赖方式可以工作。

### 要求整个请求生命周期都有 trace_id

应在更外层中间件或纯 ASGI 中间件中提前设置。

例如：

```python
@app.middleware("http")
async def trace_middleware(request: Request, call_next):
    trace_id = request.headers.get("X-Trace-ID") or new_trace_id()
    token = _trace_id_var.set(trace_id)

    try:
        response = await call_next(request)
        response.headers["X-Trace-ID"] = trace_id
        return response
    finally:
        _trace_id_var.reset(token)
```

这样：

- 进入中间件的日志有 trace_id
- 路由日志有 trace_id
- 异常日志有 trace_id
- 响应头可以返回 trace_id
- 请求结束后恢复上一个上下文

同时要注意：如果中间件已经设置，路由依赖不要再无条件覆盖同一个 trace_id，避免上下文语义混乱。

---

## 12. ContextVar 在日志中的并发边界

ContextVar 解决的是“当前执行上下文”的隔离，不是数据库或全局对象的替代品。

### 异步任务

创建新任务时：

```python
task = asyncio.create_task(worker())
```

通常会让新任务获得当前上下文的一份副本。

因此：

```text
父任务 trace_id=req-123
子任务读取 trace_id
    ↓
通常也是 req-123
```

但子任务修改自己的 ContextVar：

```python
_trace_id_var.set("child")
```

通常不会反向修改父任务的值。

### 同步线程

ContextVar 不等于所有线程共享的全局变量。新线程默认不会自动继承当前线程的 ContextVar。

`asyncio.run_in_executor()` 通常需要显式传播上下文：

```python
context = contextvars.copy_context()
await loop.run_in_executor(None, context.run, sync_function)
```

而 `asyncio.to_thread()` 在较新 Python 中会处理上下文传播，但仍建议通过测试确认实际行为。

### 日志中的结论

```text
异步任务：ContextVar 通常随任务上下文复制
普通全局变量：所有任务共享，容易串号
新线程：不要假设自动继承，必要时显式复制上下文
```

---

## 13. 请求日志应该记录什么

推荐记录：

```text
trace_id
request_id
method
path
route
status_code
duration_ms
client_ip
user_id / tenant_id
model
stream
error_code
```

SSE 还要补充：

```text
first_token_ms
token_count
stream_completed
client_disconnected
upstream_status
retry_count
```

不要在通用日志中记录：

- 完整 prompt
- 完整模型输出
- `Authorization`
- API Key
- Cookie
- 密码
- 身份证号
- 手机号
- 其他敏感 PII

如果确实需要排查 prompt，应该：

- 只在受控环境打开
- 做字段脱敏
- 截断长度
- 记录哈希或摘要
- 设置保留期限和访问权限

---

## 14. 请求日志中间件示例

一个最小的结构可以是：

```python
@app.middleware("http")
async def request_log_middleware(request: Request, call_next):
    start = time.perf_counter()

    try:
        response = await call_next(request)
    except Exception:
        logger.exception(
            "request_failed",
            extra={
                "method": request.method,
                "path": request.url.path,
            },
        )
        raise
    finally:
        elapsed_ms = (time.perf_counter() - start) * 1000
        logger.info(
            "request_finished",
            extra={
                "method": request.method,
                "path": request.url.path,
                "duration_ms": round(elapsed_ms, 2),
            },
        )

    return response
```

但这个示例还不完整，因为 `response.status_code` 需要在拿到 response 后记录。

更完整：

```python
@app.middleware("http")
async def request_log_middleware(request: Request, call_next):
    start = time.perf_counter()

    try:
        response = await call_next(request)
    except Exception:
        logger.exception("request_failed")
        raise
    else:
        elapsed_ms = (time.perf_counter() - start) * 1000
        logger.info(
            "request_finished",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": round(elapsed_ms, 2),
            },
        )
        return response
```

### 不要默认读取 body

不要随手写：

```python
body = await request.body()
```

请求体是底层 ASGI 消息流的一部分。通用中间件读取它，可能影响下游，也会导致：

- 大请求占用内存
- SSE 请求被缓冲
- 文件上传无法流式处理
- 下游拿不到预期 body

日志只记录长度、方法、路径和状态即可。

---

## 15. SSE 日志的特殊性

普通 HTTP 请求是：

```text
request → route → response
```

SSE 是：

```text
request → route → 持续发送多个 response body chunk
```

所以 SSE 日志不能只看“HTTP 200 是否返回”。

流式请求可能：

1. 返回 200
2. 发送第一帧
3. 上游超时
4. 发送 error 事件
5. 客户端断开
6. 生成器取消

这些阶段应该分别记录：

```text
stream_started
first_token_sent
stream_error
client_disconnected
stream_completed
```

例如：

```python
logger.info(
    "stream_started",
    extra={"model": body.model},
)

logger.info(
    "stream_completed",
    extra={
        "token_chunks": emitted_tokens,
        "stream_completed": True,
    },
)
```

项目当前在客户端断开时使用 `break`，之后仍可能继续发送 `done` 帧。更合适的是直接：

```python
return
```

让 `aclosing()` 和 `finally` 完成关闭，并在日志中记录：

```text
stream_aborted_by_client
```

---

## 16. 上游 HTTP 日志

`http_client.py` 和 `llm_client.py` 是最需要观测的位置。

一次上游请求应该记录：

```text
upstream_request
    method
    host
    path
    model
    attempt
    timeout
```

一次响应应该记录：

```text
upstream_response
    status_code
    duration_ms
    retry_after
    response_bytes
```

失败时记录：

```text
upstream_timeout
upstream_connect_error
upstream_http_error
upstream_protocol_error
```

不要在日志中写：

```python
headers={"Authorization": "Bearer sk-..."}
```

也不要把完整上游响应 body 打进日志，因为可能包含模型输出和用户数据。

### 重试日志

`async_retry` 和 `request_with_jitter_retry` 应该记录：

- 当前是第几次尝试
- 最大尝试次数
- 错误类型
- 是否可重试
- 下一次等待时间
- 是否遵守 `Retry-After`

而不是只写：

```python
print("准备重试")
```

项目当前 `async_timer` 和 `async_retry` 使用 `print`，应逐步替换为 logger。

---

## 17. 什么是 trace、span 和 request_id

三个概念不要混用：

### request_id

一次 HTTP 请求的标识。

```text
request_id = req-123
```

### trace_id

一条完整调用链的标识，可能跨多个服务和多个 span。

```text
trace_id = 4bf92f3577b34da6a3ce929d0e0e4736
```

### span_id

调用链中某一个操作节点。

```text
span_id = 00f067aa0ba902b7
```

关系可以是：

```text
trace_id=abc
├── gateway span
├── auth span
├── upstream_llm span
└── redis span
```

当前项目只有一个 trace_id，适合作为教学和单服务关联，但还没有完整的分布式 trace 结构。

如果未来接入 OpenTelemetry，通常需要：

- 自动注入 trace/span
- 在 HTTPX 请求头传播上下文
- 在日志中同时输出 trace_id 和 span_id
- 将日志、指标和 trace 关联到同一个后端

---

## 18. 日志配置的生命周期

日志配置应该在应用启动时执行一次：

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging(debug=settings.debug)
    yield
```

不要在模块导入时反复配置：

```python
setup_logging()  # 每次 import 都执行，可能重复添加 handler
```

项目的 `setup_logging` 会：

```python
root_logger.handlers.clear()
root_logger.addHandler(handler)
```

这在应用启动阶段可以工作，但要注意：

- 它会影响整个进程的 root logger
- 可能覆盖测试框架或其他库的日志配置
- 如果测试多次调用，应该验证 handler 不会意外重复
- Uvicorn 自己的 logger 可能使用独立 handler，不一定会获得相同的 `trace_id` 格式

生产环境更推荐使用 `logging.config.dictConfig()` 统一管理：

```python
logging.config.dictConfig(LOGGING_CONFIG)
```

这样能清楚定义：

- formatter
- handler
- logger
- level
- propagation
- filter

---

## 19. 用 test 验证日志行为

不要只靠肉眼观察控制台。

pytest 提供 `caplog`：

```python
def test_mode(caplog):
    with caplog.at_level("INFO", logger="ai_engine"):
        logger.info("hello")

    assert "hello" in caplog.text
```

更精确地检查 LogRecord：

```python
record = caplog.records[0]
assert record.levelname == "INFO"
assert record.trace_id == "req-123"
```

可以验证：

- 日志级别是否正确
- trace_id 是否注入
- 是否包含异常堆栈
- 是否错误地记录了 API Key
- 并发请求是否串 trace_id
- 重试日志是否包含 attempt
- 请求日志是否包含 duration_ms

示例：

```python
def test_log_does_not_leak_secret(caplog):
    with caplog.at_level("INFO"):
        logger.info("api_key_configured")

    assert "sk-test" not in caplog.text
```

对于异步请求并发隔离，可以创建两个任务并分别设置 trace_id，确认日志记录不串。

---

## 20. 当前项目的可观测性改进清单

### logger.py

- 把 `TraceIdFilter.filter` 返回类型改为 `bool`
- 明确日志时间和时区
- 考虑 JSON formatter
- 明确 Uvicorn logger 是否也要统一格式
- 避免无保护地清空全局 root handler

### deps.py

- 明确 trace_id 是否由依赖设置
- 如果希望 middleware 日志也有 trace_id，应在更外层设置
- 校验客户端传入的 `X-Trace-ID` 长度和字符集

### chat.py

- `logger.exception` 不要再重复 `exc` 字符串
- 客户端断开时记录独立事件
- 区分 `ValueError`、上游超时、上游 HTTP 错误、协议错误
- 记录首帧耗时、token 块数、结束原因

### http_client.py

- 记录上游请求开始和结束
- 记录重试次数、退避时间、最终状态码
- 不记录 Authorization 和完整 body
- 记录 `Retry-After`

### decorators.py

- 把 `print` 替换成 logger
- 记录函数名、attempt、耗时、异常类型
- 日志中带上 `trace_id`
- 不要在日志中记录函数参数中的敏感值

### context.py

- 把演示性质的 `print` 替换成 logger
- 区分生命周期日志和业务日志
- 记录资源初始化和清理结果

---

## 21. 日志、指标、追踪怎么配合

一个生产请求应该同时产生：

```text
Log：
trace_id=abc request_finished status=200 duration_ms=842

Metric：
http_requests_total{status="200"} += 1
http_request_duration_seconds{route="/chat"} observe 0.842

Trace：
gateway span 842ms
    └── upstream_llm span 790ms
```

排查问题时：

```text
先看指标：错误率是否升高？
    ↓
再按 trace_id 查日志：哪个请求、哪个阶段？
    ↓
再查 trace：时间花在网关还是上游？
```

三者不是互相替代，而是互相定位。

---

## 本课核心结论

- 日志用于离散事件，指标用于聚合趋势，追踪用于调用链定位。
- Python logging 的核心是 Logger、LogRecord、Handler、Formatter、Filter。
- `trace_id` 只有在整个请求生命周期内提前设置，才能覆盖所有日志。
- `ContextVar` 适合请求上下文，但不是所有线程和任务都会自动继承。
- `logger.exception()` 保留 traceback，`logger.error()` 不一定。
- 结构化日志应记录字段，不记录完整敏感正文。
- SSE 不能只看 HTTP 200，必须记录首帧、结束、错误和客户端断开。
- `print` 无法进入统一日志系统，生产代码应改用 logger。
- 日志本身也需要测试，`caplog` 可以验证级别、trace_id 和敏感信息。
- 当前项目下一步应优先改造 `logger.py`、`chat.py`、`http_client.py` 和重试装饰器。

---

## 验收问题

按编号回答，我会逐题批改：

1. Logs、Metrics、Traces 各自最适合回答什么问题？
2. Logger、Handler、Formatter、Filter 分别负责什么？
3. 为什么只给 root logger 加 handler，`ai_engine` 的日志也能输出？
4. `logger.error()` 和 `logger.exception()` 的关键区别是什么？
5. 为什么当前依赖中设置的 `trace_id`，可能无法覆盖最外层 middleware 的日志？
6. ContextVar 在异步子任务、`run_in_executor()` 和新线程中分别是什么传播行为？
7. 通用请求日志为什么不应该随便执行 `await request.body()`？
8. SSE 请求应该额外记录哪些日志事件或字段？
9. 哪些字段不应该进入生产日志？如果必须排查 prompt，应该怎么处理？
10. 如何用 pytest 验证日志中的 trace_id、异常堆栈和敏感信息脱敏？

## 用户（原始消息 3319）

1. Logs 适合记录发生了什么， Metrics 适合记录指标，从而反应系统健康状态 ， Traces 适合记录全链路，方便追踪问题，发现整个系统较慢的部分 2. Logger 就是日志组件，Handler 是指如何打印日志，Formatter 是指日志以何种格式显示， Filter 是给日志挂一个 record 3. 因为日志可以冒泡 4. logger.error 不一定会携带 traceback 而 logger.exception 一定会携带 5. 因为trace_id 在当前项目中是作为 请求的依赖的，所以外层中间件获取不到  6. 异步子任务会复制一份，run_in_executor 和新线程不会自动继承，需要手动传递 7. body 通常只能读取一次，另外 body 中可能包含敏感信息，防止泄露 8. 记录首字时间，重试次数等 9. prompt key 用户密钥等敏感信息都不应该进入日志，需要排查 prompt 可以进行脱敏处理 10 . 使用 caplog 做测试进行验证

## 助手（原始消息 3324）

**批改：7.5/10**

第 1、3、4、5、6 题基本正确；第 2 题有明显概念偏差；第 7 题方向对，但“只能读取一次”不够准确；第 8、9、10 题回答过简。

---

**1. 正确**

- Logs：记录离散事件，回答“发生了什么”
- Metrics：可聚合数值，回答“系统整体是否健康、趋势如何”
- Traces：记录跨服务、跨阶段的调用链，回答“慢在哪里、失败在哪一段”

补充一句：

```text
Metrics 发现异常
→ Logs 定位具体请求和错误
→ Traces 定位耗时发生在哪个阶段
```

---

**2. 部分正确，需要修正**

你的表述中，`Logger` 和 `Handler` 的职责不够准确。

### Logger

Logger 是日志入口，不是单纯的“日志组件”。

```python
logger = logging.getLogger("ai_engine")
logger.info("request_started")
```

它负责：

- 提供日志调用方法
- 判断日志级别
- 创建 `LogRecord`
- 执行 logger 级别的过滤器
- 把记录交给 handler 或父 logger

### Handler

Handler 决定日志发送到哪里，不是“如何打印”。

例如：

```python
logging.StreamHandler()
logging.FileHandler()
RotatingFileHandler()
```

常见目标：

- stdout
- 文件
- Syslog
- 远程日志服务

### Formatter

Formatter 决定日志最终以什么格式显示：

```python
logging.Formatter(
    "[%(asctime)s] [%(levelname)s] [%(trace_id)s] %(message)s"
)
```

它负责：

- 时间格式
- 字段排列
- 文本日志格式
- JSON 日志序列化

### Filter

Filter 不是“给日志挂一个 record”。

Filter 是挂在 logger 或 handler 上的处理器，用来：

- 判断记录是否允许通过
- 修改或补充 `LogRecord`
- 按字段过滤日志

当前项目中的：

```python
class TraceIdFilter(logging.Filter):
    def filter(self, record: LogRecord) -> bool:
        record.trace_id = _trace_id_var.get("system")
        return True
```

它的作用是：

```text
LogRecord
    ↓
读取 ContextVar
    ↓
补充 record.trace_id
    ↓
返回 True，允许日志通过
```

所以更准确的说法是：

> Filter 负责对 LogRecord 做过滤或补充，最终返回 True/False。

---

**3. 正确**

因为子 logger 默认会把日志传播给父 logger：

```python
logger = logging.getLogger("ai_engine")
logger.propagate = True
```

关系是：

```text
ai_engine
    ↓
root
```

root 上有 handler，所以 `ai_engine` 的日志最终会由 root handler 输出。

更准确地说：

> 日志由 logger 名称层级向上传播到祖先 logger，最终传播到 root。

---

**4. 正确**

`logger.error()` 默认不包含 traceback：

```python
logger.error("请求失败")
```

如果需要 traceback：

```python
logger.error("请求失败", exc_info=True)
```

`logger.exception()` 等价于：

```python
logger.error("请求失败", exc_info=True)
```

但 `logger.exception()` 应该放在 `except` 块中：

```python
try:
    ...
except Exception:
    logger.exception("请求失败")
```

否则它可能记录不到真实异常。

---

**5. 正确**

当前项目的 trace_id 是由路由依赖设置的：

```text
middleware
    ↓
路由匹配
    ↓
依赖解析
    ↓
get_request_trace_id
    ↓
ContextVar.set()
```

所以最外层中间件入口执行时，依赖还没有运行。

此时日志可能看到：

```text
system
```

而不是实际请求的 trace_id。

如果希望 middleware 日志也有 trace_id，就需要在更外层提前设置：

```python
@app.middleware("http")
async def trace_middleware(request: Request, call_next):
    trace_id = request.headers.get("X-Trace-ID") or new_trace_id()
    token = _trace_id_var.set(trace_id)
    try:
        return await call_next(request)
    finally:
        _trace_id_var.reset(token)
```

---

**6. 基本正确，但可以更精确**

- `asyncio.create_task()`：新任务通常获得当前上下文快照。
- `asyncio.to_thread()`：在现代 Python 中会传播当前上下文。
- `loop.run_in_executor()`：通常不自动传播，需要 `contextvars.copy_context()`。
- 新线程：默认不会自动继承当前线程的 ContextVar。

示例：

```python
context = contextvars.copy_context()
await loop.run_in_executor(None, context.run, sync_function)
```

---

**7. 部分正确**

你提到的两个原因都对，但“body 只能读取一次”要更精确。

请求体来自 ASGI 的 `receive` 消息流。Starlette 的 `Request` 在读取后可能缓存 body，所以不能简单认为任何情况下都绝对只能读一次。

但通用中间件仍然不应该随便执行：

```python
body = await request.body()
```

原因是多方面的：

- 可能与下游消费 `receive` 发生冲突
- 大请求会占用大量内存
- 文件上传无法流式处理
- SSE 或流式请求的生命周期会受到影响
- body 可能包含敏感信息
- 修改 body 后需要重新包装 `receive`

生产日志通常只记录：

```text
method
path
content-length
status_code
duration_ms
```

不记录完整 body。

---

**8. 不完整**

你提到了首字时间和重试次数，方向正确，但 SSE 还需要记录完整生命周期。

建议记录：

### 请求阶段

- `stream_requested`
- `model`
- 请求是否合法
- 是否命中 Token 限制

### 流式阶段

- `stream_started`
- `first_token_ms`
- `token_chunks`
- `output_chars`
- `duration_ms`

### 上游阶段

- `upstream_status`
- `upstream_timeout`
- `retry_count`
- `retry_delay`
- `error_code`

### 结束阶段

- `stream_completed`
- `stream_aborted_by_client`
- `stream_error`
- `finish_reason`
- 是否发送了 `done` 帧

重点是记录：

```text
首帧延迟
总时长
token 数量
结束原因
客户端是否断开
```

而不是记录完整 Prompt 和完整模型输出。

---

**9. 基本正确**

不应进入生产日志的内容包括：

- API Key
- `Authorization`
- Cookie
- 密码
- 完整 Prompt
- 完整模型输出
- 用户隐私数据
- 数据库连接字符串
- 身份证号、手机号等 PII

排查 Prompt 时不应直接打印全文，而应该：

- 在受控环境开启
- 只截取有限长度
- 对敏感字段脱敏
- 使用哈希或摘要
- 限制日志保留时间
- 限制访问权限
- 使用审计日志而不是普通调试日志

---

**10. 只说方向，不够完整**

`caplog` 是对的，但应该说明验证什么。

例如：

```python
def test_trace_id(caplog):
    caplog.set_level(logging.INFO, logger="ai_engine")

    logger.info("hello")

    record = caplog.records[0]
    assert record.trace_id == "req-123"
```

可以验证：

- 日志级别是否正确
- `record.trace_id` 是否存在
- 异常是否带 `exc_info`
- traceback 是否被记录
- 日志中是否泄露 API Key
- 重试日志是否包含 attempt
- 请求日志是否包含 duration_ms
- SSE 是否记录首字时间和结束原因

并发隔离测试：

```python
async def test_trace_isolation(caplog):
    async def worker(trace_id: str):
        _trace_id_var.set(trace_id)
        logger.info("worker_started")

    await asyncio.gather(
        worker("req-a"),
        worker("req-b"),
    )

    assert any(record.trace_id == "req-a" for record in caplog.records)
    assert any(record.trace_id == "req-b" for record in caplog.records)
```

还要验证敏感信息：

```python
assert "sk-test" not in caplog.text
```

---

**本课最需要记住的内容**

```text
Logger：日志入口
Handler：日志输出目的地
Formatter：日志格式
Filter：过滤或补充 LogRecord

Logs：发生了什么
Metrics：整体趋势如何
Traces：慢在哪个阶段

trace_id 必须在整个请求生命周期覆盖
    ↓
优先在 middleware 或纯 ASGI 层设置

SSE 不能只记录 HTTP 200
    ↓
还要记录首字、完成、错误和断开

日志测试不仅看文本
    ↓
用 caplog.records 验证字段和异常信息
```

下一课建议进入：**认证、授权、Secret、CORS 与安全边界**。回复“继续”开始。

## 用户（原始消息 3331）


# Response annotations:
Each item contains text selected from an earlier Codex response and may include a user comment. Treat items as Annotation 1, Annotation 2, and so on in array order. Use every selection as context and address every comment. For every annotation you address, include its inline directive `:codex-annotation{index="N"}`, where N is its one-based array position (for example, `:codex-annotation{index="1"}`). Do not use unstructured annotation labels.
<response-annotations>
[{"text":"但 logger.exception() 应该放在 except 块中：\n  Python\n \n\n\ntry:\n    ...\nexcept Exception:\n    logger.exception(\"请求失败\")","source":{"contentOffsets":{"startOffset":1600,"endOffset":1703},"messageId":"msg_18e510cefc1f9c2400000002","startOffset":1611,"endOffset":1715}}]
</response-annotations>

## My request:
logger.exception 是基于什么机制实现的保存异常堆栈信息

## 助手（原始消息 3336）

`:codex-annotation{index="1"}`

`logger.exception()` 本身不负责生成堆栈。它只是一个便捷入口，真正保存 traceback 的是 `logging` 的 `LogRecord` 和 `Formatter` 处理链。

调用过程大致是：

```text
logger.exception(...)
    ↓
Logger.exception()
    ↓
self.error(..., exc_info=True)
    ↓
Logger._log()
    ↓
sys.exc_info()
    ↓
LogRecord(exc_info=...)
    ↓
Handler.emit()
    ↓
Formatter.format()
    ↓
Formatter.formatException()
    ↓
traceback.print_exception()
```

## 1. `logger.exception()` 只是设置 `exc_info=True`

标准库中的实现可以理解为：

```python
def exception(self, msg, *args, exc_info=True, **kwargs):
    self.error(msg, *args, exc_info=exc_info, **kwargs)
```

所以：

```python
logger.exception("请求失败")
```

本质上近似于：

```python
logger.error("请求失败", exc_info=True)
```

区别只是 `logger.exception()` 默认帮你把 `exc_info` 设成了 `True`。

## 2. `Logger._log()` 获取当前异常

创建 `LogRecord` 时，`logging` 会处理 `exc_info`：

```python
if exc_info:
    if isinstance(exc_info, BaseException):
        exc_info = (
            type(exc_info),
            exc_info,
            exc_info.__traceback__,
        )
    elif not isinstance(exc_info, tuple):
        exc_info = sys.exc_info()
```

当传入的是 `True` 时，会调用：

```python
sys.exc_info()
```

它返回当前正在处理的异常三元组：

```python
(
    exception_type,
    exception_value,
    traceback_object,
)
```

也就是：

```text
异常类
异常实例
traceback 对象
```

然后这些信息会被写入 `LogRecord`：

```python
record.exc_info = exc_info
```

所以，`logger.exception()` 能保存堆栈的根本原因是：

> 它让 logging 在当前异常上下文中调用 `sys.exc_info()`，取得当前 traceback 对象。

## 3. Formatter 把 traceback 转成文本

Handler 最后会调用 Formatter：

```text
Handler.emit(record)
    ↓
Formatter.format(record)
```

`Formatter.format()` 大致会执行：

```python
if record.exc_info:
    if not record.exc_text:
        record.exc_text = self.formatException(record.exc_info)

if record.exc_text:
    message += "\n" + record.exc_text
```

`formatException()` 最终使用 `traceback` 模块把异常三元组格式化为字符串，大致相当于：

```python
traceback.print_exception(
    exc_type,
    exc_value,
    exc_tb,
)
```

因此最终日志中会出现：

```text
Traceback (most recent call last):
  File "...", line 10, in endpoint
    ...
ValueError: ...
```

如果存在异常链：

```python
try:
    ...
except ValueError as exc:
    raise RuntimeError("处理失败") from exc
```

`traceback` 也会把 `__cause__`、`__context__` 等信息打印出来。

## 4. 为什么应该放在 `except` 块中

`sys.exc_info()` 只有在当前正在处理异常时，才包含真实异常。

正确：

```python
try:
    await do_something()
except Exception:
    logger.exception("请求失败")
    raise
```

错误：

```python
try:
    await do_something()
except Exception as exc:
    ...

logger.exception("请求失败")
```

后者已经离开了异常处理块，`sys.exc_info()` 通常拿不到原来的 traceback。

如果必须在 `except` 块外记录已有异常，应显式传入：

```python
logger.error(
    "请求失败",
    exc_info=(type(exc), exc, exc.__traceback__),
)
```

或者：

```python
logger.error("请求失败", exc_info=exc)
```

后一种写法在较新版本 Python 中会自动转换为异常三元组。

## 5. 异步代码中的注意事项

不要在 `except` 块外另建任务，然后期望它自动继承当前异常：

```python
except Exception:
    asyncio.create_task(
        log_exception()
    )
```

`log_exception()` 中再调用 `logger.exception()` 时，不保证能取得原异常的 `sys.exc_info()`。

应该：

```python
except Exception:
    logger.exception("请求失败")
```

或者显式把异常传出去：

```python
except Exception as exc:
    logger.error(
        "请求失败",
        exc_info=(type(exc), exc, exc.__traceback__),
    )
```

## 一句话总结

`logger.exception()` 通过设置 `exc_info=True`，让 `logging._log()` 在当前 `except` 上下文中调用 `sys.exc_info()` 取得异常类型、异常实例和 traceback 对象，再由 `Formatter.formatException()` 使用 `traceback` 模块转换成最终日志文本。

