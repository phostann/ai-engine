# Python 与 FastAPI 项目知识地图

本文档整理了 `ai-engine` 项目学习过程中涉及的核心 Python、asyncio、Pydantic、FastAPI、HTTPX 和测试知识。内容按知识点组织，不按学习天数划分。

建议阅读方式：

1. 先读“项目全景”和“请求调用链”，建立整体地图。
2. 再按知识点复习原理。
3. 遇到问题时查“常见陷阱”和“当前代码改进点”。
4. 最后使用末尾的复习清单自检。

## 1. 项目全景

项目发布名和真实包名不同：

```text
发布名：ai-engine
导入包名：ai_engine
源码目录：src/ai_engine
```

核心入口关系：

```text
uv run ai-engine
    ↓
pyproject.toml 中的 console script
    ↓
ai_engine.cli:main
    ↓
uvicorn.run("ai_engine.main:app", ...)
    ↓
FastAPI 应用
```

相关文件：

- [pyproject.toml](../pyproject.toml)
- [cli.py](../src/ai_engine/cli.py)
- [main.py](../src/ai_engine/main.py)

本地常用命令：

```powershell
uv sync
uv run ai-engine
uv run pytest
uv run ruff check .
```

健康检查：

```text
GET /health
→ {"status":"ok"}
```

## 2. 请求调用链

一次流式聊天请求大致经过：

```text
HTTP POST /api/v1/chat/completions/stream
    ↓
FastAPI 参数解析与 Pydantic 校验
    ↓
Depends 注入 LLMClient、trace_id
    ↓
generate_gateway_chat_stream()
    ↓
NativeLLMClient.chat_stream()
    ↓
ProductionHttpClient
    ↓
上游大模型 HTTP/SSE 服务
    ↓
EventSourceResponse
    ↓
客户端
```

关键文件：

- [chat.py](../src/ai_engine/api/v1/chat.py)
- [deps.py](../src/ai_engine/api/deps.py)
- [llm_client.py](../src/ai_engine/services/llm_client.py)
- [http_client.py](../src/ai_engine/core/http_client.py)

## 3. 模块、包与入口点

### 模块与包

- 模块是一个 Python 文件，例如 `config.py`。
- 包是包含多个模块的导入单元，通常由目录和 `__init__.py` 表示。
- `import ai_engine` 先执行包初始化文件。
- `import ai_engine.main` 导入子模块，并把它绑定到包的 `main` 属性。

包属性和子模块可能互相覆盖。例如包初始化中定义了一个叫 `main` 的函数，之后又导入 `ai_engine.main` 子模块，`ai_engine.main` 就会指向模块，而不是原来的函数。

工程规则：

- 包内公开函数尽量避免和子模块使用相同名称。
- 应用入口统一走 `ai_engine.cli:main`。
- Uvicorn 使用导入字符串 `"ai_engine.main:app"`，避免直接导入应用对象。

### 可编辑安装

可编辑安装会让 Python 能直接从源码目录加载包。工程项目通常通过 `.pth` 文件把 `src` 路径加入 `sys.path`。

由此可以理解：

- 修改源码后通常不需要重新安装包。
- `uv run` 使用的是项目环境中的入口点和依赖。
- `ai-engine` 是命令行入口名，不是 Python import 名。

## 4. Python 类型系统

### 类型注解不等于运行时校验

```python
x: int = "hello"
```

Python 运行时通常不会因为这条类型不匹配而报错。类型注解主要服务于：

- IDE 和静态类型检查器
- Pydantic、FastAPI 等运行时框架
- 代码可读性和接口契约

### Any 与 object

- `Any` 会关闭类型检查，操作不受限制。
- `object` 可以安全接收所有对象，但调用具体方法前必须通过 `isinstance()` 等方式收窄。
- 业务层应尽量少使用 `Any`。

项目中的宽松类型：

```python
messages: list[dict[str, Any]]
```

可以表达任意 ChatML 消息，但不能约束 `role`、`content` 等字段。

更严格的选择：

- 内部可信结构使用 `TypedDict`
- 外部不可信 JSON 使用 Pydantic 模型
- 外部服务调用可使用 `TypeAdapter` 做运行时校验

### TypeVar 与 ParamSpec

- `TypeVar` 表示某个值的类型。
- `ParamSpec` 表示完整的参数列表结构。

项目中的泛型并发函数：

```python
async def run_bounded_task_group[T, R](
    items: list[T],
    worker_fn: Callable[[T], Coroutine[Any, Any, R]],
) -> list[R]:
    ...
```

`T` 是输入元素类型，`R` 是 worker 返回类型。

装饰器使用 `ParamSpec` 保留被装饰函数的参数：

```python
def async_timer[**P, R](
    func: Callable[P, Coroutine[Any, Any, R]],
) -> Callable[P, Coroutine[Any, Any, R]]:
    ...
```

### Annotated

`Annotated[T, metadata]` 的运行时类型仍然是 `T`，其余参数是给工具读取的元数据。

项目示例：

```python
type NonEmptyStr = Annotated[
    str,
    Field(min_length=1, description="非空字符串"),
]
```

Pydantic 读取 `Field` 并生成验证规则。

FastAPI 依赖别名：

```python
TraceIdDep = Annotated[
    str,
    Depends(get_request_trace_id, use_cache=True),
]
```

FastAPI 读取 `Depends` 并执行依赖注入。

### Protocol

`Protocol` 使用结构化类型，不要求显式继承：

```python
class Renderer(Protocol):
    def render(self) -> str:
        ...
```

任何实现了 `render()` 的对象都可以在静态类型层面符合该协议。

`@runtime_checkable` 允许对协议使用 `isinstance()` 和 `issubclass()`，但运行时检查通常只确认成员是否存在，不检查完整签名、参数类型和返回值类型。

### cast

```python
value = cast(int, payload["id"])
```

`cast()` 只影响静态检查器，不转换、不校验、不抛异常。不可信输入应使用 Pydantic 或 `TypeAdapter`。

## 5. 装饰器

### 基本等价关系

```python
@decorator
def func():
    ...
```

等价于：

```python
def func():
    ...

func = decorator(func)
```

装饰器在函数定义时应用一次，通常在模块导入时执行。

### 多个装饰器的顺序

```python
@A
@B
def func():
    ...
```

等价于：

```python
func = A(B(func))
```

应用顺序是从下往上，调用顺序是从外往内。

项目中的：

```python
@async_timer
@async_retry(max_retries=3, base_delay=0.2)
async def check_model_health(...):
    ...
```

`async_timer` 在最外层，因此统计的是包含重试等待在内的总耗时。

### functools.wraps

`@functools.wraps(func)` 会保留：

- `__name__`
- `__qualname__`
- `__doc__`
- `__module__`
- `__annotations__`
- `__dict__`
- `__wrapped__`

反射工具可以通过 `__wrapped__` 找到原函数。

### 异步函数和异步生成器

普通异步函数可以：

```python
return await func(*args, **kwargs)
```

异步生成器不能直接 `await`，需要：

```python
async for item in func(*args, **kwargs):
    yield item
```

如果消费者可能提前退出，应使用 `aclosing()` 确保内层生成器被关闭。

## 6. 上下文管理器

### 同步协议

```python
with manager as value:
    ...
```

对应：

```python
value = manager.__enter__()
try:
    ...
finally:
    manager.__exit__(...)
```

### 异步协议

```python
async with manager as value:
    ...
```

对应：

```python
value = await manager.__aenter__()
try:
    ...
finally:
    await manager.__aexit__(...)
```

`__exit__` 和 `__aexit__` 返回真值时可以抑制异常。资源管理通常应只清理，不随意吞异常。

### @asynccontextmanager

```python
@asynccontextmanager
async def scope():
    resource = await open_resource()
    try:
        yield resource
    finally:
        await close_resource(resource)
```

- `yield` 前对应进入
- `yield` 后对应退出
- 通常只允许一个 `yield`
- 如果 `yield` 前初始化失败，`__aexit__` 不会执行

因此资源一旦打开，后续初始化必须立即放在 `try/finally` 中。

### AsyncExitStack

`AsyncExitStack` 适合管理数量在运行时决定的资源：

```python
async with AsyncExitStack() as stack:
    resource_a = await stack.enter_async_context(open_a())
    resource_b = await stack.enter_async_context(open_b())
```

退出顺序为 LIFO：

```text
关闭 resource_b
关闭 resource_a
```

如果 `__aenter__` 内部初始化失败，其自身必须负责回滚已经打开的资源。普通 `except Exception` 捕获不到 `CancelledError`，资源初始化边界需要使用 `BaseException` 进行清理并立即重新抛出。

相关文件：

- [context.py](../src/ai_engine/core/context.py)
- [lifecycle_ext.py](../src/ai_engine/core/lifecycle_ext.py)

## 7. FastAPI lifespan 与依赖注入

### lifespan

项目在 [main.py](../src/ai_engine/main.py) 中使用：

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    async with ProductionHttpClient(...) as http_client:
        app.state.llm_client = NativeLLMClient(...)
        yield
```

生命周期：

```text
应用启动
    ↓
创建连接池和 LLMClient
    ↓
yield，应用开始处理请求
    ↓
应用关闭
    ↓
关闭连接池
```

`app.state` 是应用级状态，不是请求级状态。每个 worker 进程各有自己的 `app.state`。

### Depends

正确写法：

```python
llm_client: LLMClientDep
```

其中：

```python
LLMClientDep = Annotated[
    NativeLLMClient,
    Depends(get_llm_client, use_cache=True),
]
```

FastAPI 负责调用依赖函数，并把返回值注入路由参数。

`Depends(get_llm_client)` 是声明依赖；`get_llm_client()` 是直接调用函数，不能替代依赖声明。

### yield 依赖

```python
async def get_request_trace_id(...):
    token = _trace_id_var.set(trace_id)
    try:
        yield trace_id
    finally:
        _trace_id_var.reset(token)
```

执行顺序：

```text
yield 前：创建请求作用域
路由执行
yield 后：清理请求作用域
```

请求级资源放请求依赖中，应用级资源放 lifespan 和 `app.state` 中。

## 8. ContextVar

`ContextVar` 为每次请求保存独立上下文值，适合：

- trace_id
- 请求 ID
- 用户上下文
- 日志染色

直接 `await` 另一个协程通常在当前上下文中执行；`asyncio.create_task()` 会复制当前上下文快照。

因此子任务修改自己的 `ContextVar` 时，通常不会影响父任务。

项目实现：

- [deps.py](../src/ai_engine/api/deps.py)
- [logger.py](../src/ai_engine/core/logger.py)
- [lifecycle_ext.py](../src/ai_engine/core/lifecycle_ext.py)

## 9. asyncio 任务与取消

### coroutine 与 Task

- coroutine 是待执行的协程对象。
- Task 是被事件循环调度和管理的执行单元。
- `await coro` 在当前任务中等待。
- `asyncio.create_task(coro)` 将协程提交为独立 Task。

### 取消是协作式的

```python
task.cancel()
```

它只是提交取消请求。任务通常在下一个 `await` 挂起点收到 `CancelledError`。

如果任务一直执行纯 CPU 循环，事件循环拿不到执行权，取消就可能无法及时生效。

`CancelledError` 必须继续向外传播：

```python
except asyncio.CancelledError:
    raise
```

清理逻辑应放在 `finally`。

### TaskGroup

`TaskGroup` 提供结构化并发：

- 父作用域不会在子任务仍运行时提前退出
- 一个子任务出现未处理普通异常时，TaskGroup 会取消其他兄弟任务
- 等待所有子任务退出后，将未处理异常汇总为 `ExceptionGroup`

即使只有一个子任务失败，也通常是 `ExceptionGroup`。其他任务可能已经失败，或者在取消和清理过程中再次失败，因此需要收集所有异常。

### timeout

```python
async with asyncio.timeout(3):
    await call_upstream()
```

超时后会触发当前任务取消，并由 `asyncio.timeout()` 转换成 `TimeoutError`。

`timeout()` 不等于网络客户端自己的 `read` 超时：

- `httpx.Timeout` 约束具体网络阶段
- `asyncio.timeout` 约束整个异步代码块的总时间

### shield

```python
await asyncio.shield(inner_task)
```

外层任务被取消时，`inner_task` 不会跟着取消，但外层仍然会收到 `CancelledError`。

`shield` 不是持久化保障。进程崩溃、容器被杀死和事件循环立即关闭时，受保护任务仍可能丢失。

相关文件：

- [concurrency.py](../src/ai_engine/core/concurrency.py)
- [lifecycle_ext.py](../src/ai_engine/core/lifecycle_ext.py)

## 10. 异步迭代与 SSE

### 异步迭代协议

```python
iterator = iterable.__aiter__()
while True:
    try:
        item = await iterator.__anext__()
    except StopAsyncIteration:
        break
```

`async def` 中包含 `yield` 时，函数返回异步生成器，不是 coroutine。

异步生成器：

- 惰性执行
- 第一次 `anext()` 才运行到第一个 `yield`
- 每次 `yield` 暂停并保留状态
- 不能被多个消费者并发推进

### aclose

```python
await generator.aclose()
```

关闭已经启动的异步生成器时，会在暂停点注入 `GeneratorExit`。

- `GeneratorExit` 不是 `CancelledError`
- `GeneratorExit` 不是 `Exception`
- `finally` 中可以 `await`
- 关闭后不能再次 `yield`
- 生成器从未启动时，函数体和 `finally` 不会执行

`async for` 中执行 `break` 不保证立即关闭生成器，应使用：

```python
async with aclosing(stream):
    async for item in stream:
        ...
```

### asend 与 athrow

- `anext(gen)`：请求下一个值
- `gen.asend(value)`：向暂停的 `yield` 表达式发送值
- `gen.athrow(exc)`：在暂停点注入异常
- `gen.aclose()`：关闭生成器

第一次启动异步生成器应使用 `anext()`。如果 `SendType` 不包含 `None`，不应通过 `asend(None)` 启动，否则会产生静态类型问题。

### SSE 格式

标准字段：

```text
event: message
id: 1
data: {"content": "你好"}

```

每帧末尾必须有空行。

其他内容：

- `retry:` 表示重连间隔
- `:` 开头的是注释
- `ping=15` 是 `EventSourceResponse` 的参数，表示定期发送注释帧，不是 SSE 标准字段
- `[DONE]` 是业务协议，不是 SSE 标准

SSE 开始发送后，HTTP 状态码已经固定为成功状态，后续错误只能发送 `event: error`，不能再改回 500。

浏览器原生 `EventSource` 只支持 GET，当前 POST SSE 接口需要使用 `fetch()` 或支持 POST SSE 的库。

相关文件：

- [chat.py](../src/ai_engine/api/v1/chat.py)
- [llm_client.py](../src/ai_engine/services/llm_client.py)

## 11. 异常体系与错误边界

### 继承关系

```text
BaseException
├── SystemExit
├── KeyboardInterrupt
├── GeneratorExit
├── asyncio.CancelledError
└── Exception
    ├── ValueError
    ├── TypeError
    ├── RuntimeError
    └── ...
```

普通业务代码通常捕获 `Exception`，不要捕获 `BaseException`。

资源回滚是例外：初始化阶段需要捕获 `BaseException`，完成清理后立即重新抛出。

### try/except/else/finally

- `else`：`try` 没有异常时执行
- `finally`：通常无论成功、异常或 return 都执行
- `finally` 中的 `return` 会覆盖异常或正常返回值

### 异常链

```python
except httpx.TimeoutException as exc:
    raise UpstreamTimeout("上游超时") from exc
```

`from exc` 建立显式因果链，保留底层原因。

`from None` 用于抑制异常上下文展示，不是删除原始异常。

### 重试分类

通常可重试：

- 连接超时、读超时和临时网络错误
- 408
- 425
- 429
- 500
- 502
- 503
- 504

通常不重试：

- 400
- 401
- 403
- 404
- 409
- 422
- 参数校验错误
- 明确的代码 bug

重试还必须考虑幂等性、总超时、最大次数、`Retry-After` 和是否有部分副作用。

## 12. Pydantic v2

### 模型与校验

```python
class GatewayChatRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=2000)
    model: str = "gpt-4o-mini"
```

模型在运行时执行类型转换、字段约束和嵌套验证。

### Validator

- `field_validator(mode="before")`：原始输入进入类型校验前执行
- `field_validator(mode="after")`：单字段校验通过后执行
- `model_validator(mode="after")`：模型整体校验后执行，必须返回 `self`

### 模型配置

- `extra="forbid"`：禁止未声明字段
- `extra="ignore"`：忽略未声明字段
- `frozen=True`：禁止重新赋值，但只是浅层不可变

浅层不可变意味着列表、字典等引用类型的内容仍可能被修改。

### 序列化

- `model_dump()`：返回 Python 字典
- `model_dump(mode="json")`：返回只包含 JSON 兼容类型的字典
- `model_dump_json()`：返回 JSON 字符串
- `by_alias=True`：使用别名导出

### JSON Schema 与多态

嵌套模型会在 JSON Schema 中生成 `$ref` 和 `$defs`。

联合类型配合 `Field(discriminator="action_type")` 可以实现按字段路由的多态验证。

项目相关文件：

- [agent_protocol.py](../src/ai_engine/schemas/agent_protocol.py)
- [extraction.py](../src/ai_engine/schemas/extraction.py)
- [prompts.py](../src/ai_engine/schemas/prompts.py)

## 13. pydantic-settings

默认优先级：

```text
构造参数 > 系统环境变量 > .env 文件 > 默认值
```

要点：

- `case_sensitive` 控制字段名匹配是否区分大小写，不控制字段值
- `_env_file=None` 只禁用指定 `.env`，系统环境变量仍生效
- `SecretStr` 防止意外显示，但可以通过 `get_secret_value()` 主动读取
- `lru_cache` 会缓存配置，修改环境变量后要 `cache_clear()`
- 每个 worker 进程有自己的配置缓存

相关文件：

- [config.py](../src/ai_engine/core/config.py)

## 14. FastAPI 请求与响应边界

请求处理顺序大致为：

```text
HTTP 请求
    ↓
路由匹配
    ↓
参数解析和 Pydantic 校验
    ↓
依赖注入
    ↓
路由函数
    ↓
response_model 校验和序列化
    ↓
HTTP 响应
```

校验失败时，路由函数通常不会执行，FastAPI 返回 422。

常用状态码：

- 400：请求或业务参数错误
- 401：未认证
- 403：已认证但无权限
- 404：资源不存在
- 409：资源状态冲突
- 422：参数解析或模型校验失败
- 429：限流
- 500：服务内部错误
- 502：上游返回无效响应
- 503：服务暂不可用
- 504：上游超时

`HTTPException` 应使用在 API/Web 边界，不要把 HTTP 概念直接放进数据层和纯业务层。

流式接口开始输出后再抛普通 HTTP 异常已经来不及修改状态码，应使用 SSE 错误事件。

## 15. HTTPX

### 客户端复用

`httpx.AsyncClient` 应在进程和事件循环内复用，统一管理连接池。

不要在每次请求中创建新的客户端。

### 连接池

- `max_connections`：最大总连接数
- `max_keepalive_connections`：最多保留的空闲长连接数
- `keepalive_expiry`：空闲连接保留时间

### 四种超时

- `connect`：建立 TCP/TLS 连接
- `read`：等待服务器返回下一段数据
- `write`：发送请求体
- `pool`：等待连接池中的可用连接

流式请求中的 `read` 超时表示两次数据之间的最长等待，不是整个流的总时长。

### 重试

项目使用 Full-Jitter 思路：

```python
max_sleep = base_delay * (2 ** (attempt - 1))
sleep_time = random.uniform(0.05, max_sleep)
await asyncio.sleep(sleep_time)
```

改进方向：

- 遵守 `Retry-After`
- 增加最大退避上限和总超时
- 明确最大尝试次数含义
- 增加 408、425 等可重试状态
- 只对幂等操作自动重试

### 流式请求

```python
async with client.stream("POST", url, json=payload) as response:
    response.raise_for_status()
    async for line in response.aiter_lines():
        ...
```

必须使用 `async with`，确保响应关闭并释放连接。

相关文件：

- [http_client.py](../src/ai_engine/core/http_client.py)
- [llm_client.py](../src/ai_engine/services/llm_client.py)

## 16. pytest 与异步测试

异步测试：

```python
@pytest.mark.asyncio
async def test_something():
    ...
```

异步 fixture：

```python
@pytest_asyncio.fixture
async def http_client():
    async with ProductionHttpClient(...) as client:
        yield client
```

测试 FastAPI：

```python
async with app.router.lifespan_context(app):
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        ...
```

`ASGITransport` 不会自动执行 lifespan。

测试边界：

- `ASGITransport`：测试自己的 FastAPI 应用
- `MockTransport`：模拟应用调用的外部 HTTP 服务
- `client.post()`：通常读取完整响应
- `client.stream()`：测试增量流式响应

测试清理：

- `app.dependency_overrides.clear()`
- `get_settings.cache_clear()`
- 删除或恢复 `app.state`
- 关闭 AsyncClient、连接池和临时资源

取消测试：

```python
task = asyncio.create_task(worker())
await started.wait()
task.cancel()

with pytest.raises(asyncio.CancelledError):
    await task

assert cleaned.is_set()
```

`task.cancel()` 只是请求取消，必须 `await task` 并验证清理逻辑。

## 17. 当前代码改进点

以下内容属于后续重构方向，不是对当前代码的否定。

### TokenBudgetGuard

[tokenizer.py](../src/ai_engine/core/tokenizer.py) 中的预算校验目前仍未完成。实现后建议使用专用异常，例如：

```python
class TokenBudgetExceeded(Exception):
    ...
```

不要使用宽泛的 `ValueError` 表示所有预算错误。

### SSE 断连处理

[chat.py](../src/ai_engine/api/v1/chat.py) 检测到客户端断开后，当前使用 `break`，之后仍可能继续发送 `done` 帧。建议直接 `return`，让 `aclosing()` 完成内层生成器关闭。

### 异常分类

[chat.py](../src/ai_engine/api/v1/chat.py) 当前先捕获 `ValueError`，再捕获所有 `Exception`。建议区分：

- Token 预算错误
- 上游超时和网络错误
- 上游 HTTP 状态错误
- JSON/SSE 协议错误
- 未预期的内部错误

### 重试范围

[decorators.py](../src/ai_engine/core/decorators.py) 中的 `async_retry` 当前捕获所有 `Exception`。生产环境应只重试可恢复错误，并避免对已经输出了部分内容的流式响应整体重试。

同时，`max_retries=3` 当前实际表示总尝试次数为 3 次，而不是“原始请求 + 3 次重试”。

### AsyncExitStack 取消回滚

[lifecycle_ext.py](../src/ai_engine/core/lifecycle_ext.py) 的 `DynamicMCPClusterManager` 使用 `except Exception` 回滚。任务取消时 `CancelledError` 不会被捕获，已经打开的连接可能泄漏。

资源初始化边界可使用：

```python
except BaseException:
    await self._stack.aclose()
    raise
```

### 测试中的私有属性

测试当前通过以下私有属性注入 MockTransport：

```python
http_client.client._transport = ...
http_client.client._mounts.clear()
```

更稳定的方式是让生产类支持在构造时注入 `transport`，测试不要依赖私有实现。

## 18. 复习清单

### Python 基础与类型

- [ ] 能解释模块、包、`__init__.py`、`.pth` 和 `sys.path`
- [ ] 能解释 `ai-engine` 和 `ai_engine` 的区别
- [ ] 能说明 `Any`、`object`、`TypeVar`、`ParamSpec` 的用途
- [ ] 能说明 `Protocol` 与 ABC 的区别
- [ ] 知道 `cast()` 不执行运行时校验

### 装饰器与上下文管理

- [ ] 能写出普通装饰器和带参数装饰器
- [ ] 能说明多装饰器的应用和执行顺序
- [ ] 知道 `functools.wraps` 的作用
- [ ] 能解释 `__enter__/__exit__` 与 `__aenter__/__aexit__`
- [ ] 知道 `__aenter__` 失败时不会自动调用 `__aexit__`
- [ ] 能用 `AsyncExitStack` 动态管理资源

### asyncio

- [ ] 能区分 coroutine 和 Task
- [ ] 知道取消是协作式的
- [ ] 知道 `CancelledError` 继承自 `BaseException`
- [ ] 能解释 TaskGroup、ExceptionGroup 和 `except*`
- [ ] 能区分 `asyncio.timeout` 和 HTTPX 超时
- [ ] 知道 `shield` 只保护内部任务，不保护外层任务

### 异步迭代与 SSE

- [ ] 能实现 `__aiter__` 和 `__anext__`
- [ ] 知道异步生成器是惰性执行的
- [ ] 知道 `aclose()` 注入 `GeneratorExit`
- [ ] 知道 `break` 不保证自动关闭异步生成器
- [ ] 能解释 SSE 帧格式和 `[DONE]`
- [ ] 知道流开始后不能再修改 HTTP 状态码

### FastAPI

- [ ] 能解释 lifespan 的进入和退出
- [ ] 能解释 `Depends`、`use_cache` 和 yield 依赖
- [ ] 知道 `app.state` 不是跨 worker 共享
- [ ] 能说明请求模型和 `response_model` 的作用
- [ ] 能区分 401、403、422、500、503

### Pydantic

- [ ] 能使用 `Field`、`Annotated`、`Literal`
- [ ] 能区分 before/after validator
- [ ] 知道 `model_validator(mode="after")` 必须返回 `self`
- [ ] 知道 `extra` 和 `frozen` 的边界
- [ ] 能解释 alias、`model_dump`、JSON Schema 和 discriminator

### HTTPX 与测试

- [ ] 知道 AsyncClient 应该复用
- [ ] 能解释四种超时
- [ ] 能区分 429、5xx 和不可重试错误
- [ ] 知道流式响应部分输出后不能透明重试
- [ ] 能使用 MockTransport 和 ASGITransport
- [ ] 知道 ASGITransport 不会自动执行 lifespan
- [ ] 能测试异常、取消、重试和流式输出

## 19. 推荐学习顺序

如果继续深入，建议按以下顺序：

1. FastAPI/ASGI 请求生命周期和中间件
2. 日志、追踪和可观测性
3. 安全：认证、授权、Secret、CORS 和错误脱敏
4. 并发队列、限流和背压
5. 架构边界与依赖倒置
6. 综合代码审查和小型重构

