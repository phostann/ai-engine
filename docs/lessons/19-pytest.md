# pytest 与异步测试

> 本文逐字转录自原始课程对话，只添加角色标题和来源信息，未改写、删减或二次总结。
>
- 返回：[课程原文索引](README.md)
- 原始消息序号：`2307`、`2312`、`2319`、`2324`

## 用户（原始消息 2307）

继续

## 助手（原始消息 2312）

**本课知识点：pytest 与异步测试**

前面的 HTTPX、lifespan、依赖注入和异常都学到了，但真正把这些能力组合起来的是测试。

这一课解决几个实际问题：

- 如何测试异步函数和异步生成器
- 如何测试 FastAPI lifespan
- 如何避免测试真的访问网络
- 如何替换外部大模型服务
- 如何让测试之间的状态互不污染

---

## 1. pytest 的基本发现规则

pytest 默认发现：

- 文件名：`test_*.py` 或 `*_test.py`
- 函数名：`test_*`
- 类名：`Test*`
- 类中的测试方法：`test_*`

例如：

```python
def test_add() -> None:
    assert 1 + 1 == 2
```

pytest 使用普通 `assert`，失败时会给比原始断言更详细的输出。

运行：

```bash
uv run pytest
```

只运行某个文件：

```bash
uv run pytest tests/test_day6_core.py -v
```

只运行某个测试：

```bash
uv run pytest tests/test_day6_core.py::test_system_prompt_template_render -vv
```

---

## 2. 异步测试需要事件循环

普通 pytest 测试是同步函数：

```python
def test_something():
    ...
```

异步测试：

```python
@pytest.mark.asyncio
async def test_something() -> None:
    result = await some_async_function()
    assert result == ...
```

`@pytest.mark.asyncio` 告诉 `pytest-asyncio`：

> 这个测试需要创建事件循环，并运行这个 coroutine。

项目当前使用这种显式标记方式：

```python
@pytest.mark.asyncio
async def test_native_llm_client_streaming_with_mock() -> None:
    ...
```

也可以配置自动模式，例如在 `pyproject.toml` 中配置：

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
```

这样可能不需要每个测试都写 `@pytest.mark.asyncio`。

但显式标记更清楚，不容易把普通异步函数和异步 fixture 混在一起。

---

## 3. fixture 是测试环境准备器

fixture 用于准备测试所需的资源：

```python
import pytest


@pytest.fixture
def sample_user() -> dict[str, str]:
    return {
        "name": "Alice",
        "role": "admin",
    }


def test_user_name(sample_user: dict[str, str]) -> None:
    assert sample_user["name"] == "Alice"
```

pytest 会根据参数名自动注入 fixture：

```python
def test_user_name(sample_user):
```

不需要手动调用：

```python
sample_user()
```

---

## 4. 带清理逻辑的 fixture

如果 fixture 需要释放资源，可以使用 `yield`：

```python
@pytest.fixture
def temporary_resource():
    resource = open_resource()

    try:
        yield resource
    finally:
        close_resource(resource)
```

执行顺序：

```text
创建 resource
    ↓
测试执行
    ↓
finally 清理
```

即使测试失败、抛出异常，清理仍会执行。

这对数据库连接、临时文件、mock 和客户端都适用。

---

## 5. 异步 fixture

异步资源需要异步 fixture：

```python
import pytest_asyncio


@pytest_asyncio.fixture
async def http_client():
    async with ProductionHttpClient(
        base_url="https://mock.api.com/v1",
    ) as client:
        yield client
```

使用：

```python
@pytest.mark.asyncio
async def test_request(http_client: ProductionHttpClient) -> None:
    response = await http_client.request_with_jitter_retry(
        "GET",
        "/health",
    )
    assert response.status_code == 200
```

`pytest-asyncio` 负责在事件循环中执行异步 fixture。

在严格模式下，异步 fixture 建议使用：

```python
pytest_asyncio.fixture
```

而不是普通的：

```python
pytest.fixture
```

---

## 6. fixture 的作用域

常用作用域：

```python
@pytest.fixture
def function_scope():
    ...
```

每个测试函数创建一次。

```python
@pytest.fixture(scope="module")
def module_scope():
    ...
```

整个测试模块共享一次。

```python
@pytest.fixture(scope="session")
def session_scope():
    ...
```

整个测试会话共享一次。

对于 `httpx.AsyncClient`、数据库连接和事件循环资源，通常优先使用函数级或模块级 fixture。

不要随意使用 session 级异步 fixture，因为可能跨越多个事件循环，造成资源绑定到旧事件循环的问题。

---

## 7. 测试 FastAPI：ASGITransport

项目测试：

```python
from httpx import ASGITransport

async with httpx.AsyncClient(
    transport=ASGITransport(app=app),
    base_url="http://test",
) as client:
    response = await client.post(...)
```

`ASGITransport` 的作用是：

> 让 HTTPX 直接调用 FastAPI 的 ASGI 应用，不经过真实网络。

请求流程变成：

```text
httpx.AsyncClient
    ↓
ASGITransport
    ↓
FastAPI app
    ↓
路由函数
```

而不是：

```text
httpx.AsyncClient
    ↓
真实 DNS
    ↓
真实 TCP
    ↓
真实 HTTP 服务器
```

这适合测试：

- 路由
- 请求模型
- 响应模型
- 状态码
- 依赖注入
- 异常处理器
- SSE 响应

---

## 8. `ASGITransport` 不会自动执行 lifespan

这是一个很容易踩的坑。

创建：

```python
ASGITransport(app=app)
```

不会自动执行：

```python
app.router.lifespan_context(app)
```

因此项目里的：

```python
app.state.llm_client
```

可能还没有初始化。

测试中通常要显式执行：

```python
async with app.router.lifespan_context(app):
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/health")
```

这样顺序才是：

```text
启动 lifespan
    ↓
初始化 app.state
    ↓
执行 ASGI 请求
    ↓
关闭 lifespan
    ↓
释放连接池
```

如果不启动 lifespan，应用可能返回：

```text
NativeLLMClient 尚未在 lifespan 中初始化
```

---

## 9. `MockTransport` 测试外部 HTTP

`ASGITransport` 测试自己的 FastAPI 应用。

`MockTransport` 测试应用所调用的外部服务：

```python
import httpx


def mock_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        json={"data": "success"},
        headers={"Content-Type": "application/json"},
    )


transport = httpx.MockTransport(mock_handler)

client = httpx.AsyncClient(
    base_url="https://mock.api.com",
    transport=transport,
)
```

请求：

```python
response = await client.get("/v1/chat")
```

不会访问真实网络，而是调用 `mock_handler()`。

项目当前测试通过修改内部 transport 实现：

```python
http_client.client._transport = httpx.MockTransport(mock_sse_handler)
```

这可以工作，但属于访问私有属性，建议以后把 `transport` 作为构造参数注入，测试会更稳定。

---

## 10. 模拟不同 HTTP 响应

成功响应：

```python
def handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"ok": True})
```

限流响应：

```python
def handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        429,
        json={"error": "rate limited"},
    )
```

服务端错误：

```python
def handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(503, json={"error": "unavailable"})
```

模拟读取超时：

```python
def handler(request: httpx.Request) -> httpx.Response:
    raise httpx.ReadTimeout("读取超时", request=request)
```

这样可以在不访问网络的情况下测试：

- 正常请求
- 429 重试
- 5xx 错误处理
- 超时分支
- 重试次数
- 最终异常

---

## 11. 测试重试次数

```python
attempt_count = 0


def handler(request: httpx.Request) -> httpx.Response:
    nonlocal attempt_count
    attempt_count += 1

    if attempt_count <= 2:
        return httpx.Response(429, json={"error": "limited"})

    return httpx.Response(200, json={"ok": True})
```

测试：

```python
response = await client.request_with_jitter_retry(
    "GET",
    "/v1/chat",
    max_retries=3,
    base_delay=0.01,
)

assert response.status_code == 200
assert attempt_count == 3
```

这里不仅验证最终成功，还验证了：

- 重试确实发生
- 重试次数符合预期
- 429 被识别为可重试
- 最终成功结果被返回

---

## 12. 测试 SSE 流式响应

可以通过 `MockTransport` 返回 SSE 文本：

```python
def mock_sse(request: httpx.Request) -> httpx.Response:
    body = "".join(
        [
            'data: {"content": "你"}\n\n',
            'data: {"content": "好"}\n\n',
            "data: [DONE]\n\n",
        ]
    )

    return httpx.Response(
        200,
        content=body,
        headers={"Content-Type": "text/event-stream"},
    )
```

消费：

```python
async with httpx.AsyncClient(
    base_url="https://mock.api.com",
    transport=httpx.MockTransport(mock_sse),
) as client:
    async with client.stream("POST", "/chat") as response:
        response.raise_for_status()

        async for line in response.aiter_lines():
            ...
```

需要断言：

```python
assert "你" in received_data
assert "好" in received_data
assert "[DONE]" in received_data
```

如果测试真正的分块传输，可以使用自定义 `AsyncByteStream`：

```python
class ChunkedSSEStream(httpx.AsyncByteStream):
    async def __aiter__(self):
        yield b'data: {"content": "A"}\n\n'
        yield b'data: {"content": "B"}\n\n'
        yield b"data: [DONE]\n\n"


def handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        stream=ChunkedSSEStream(),
        headers={"Content-Type": "text/event-stream"},
    )
```

这样更接近真实的流式网络读取。

---

## 13. 测试 FastAPI SSE 路由

项目中的 `/api/v1/chat/completions/stream` 是 SSE。

普通：

```python
response = await client.post(...)
```

会等待完整响应结束，适合验证整体内容。

如果要观察流式边界：

```python
async with client.stream(
    "POST",
    "/api/v1/chat/completions/stream",
    json={"prompt": "测试"},
) as response:
    assert response.status_code == 200

    async for line in response.aiter_lines():
        ...
```

这样可以边接收边断言。

注意：

- `client.post()` 可能等待整个流结束
- `client.stream()` 才适合检查逐帧行为
- 需要正确处理 `text/event-stream`
- 需要启动 lifespan

---

## 14. 测试依赖覆盖

FastAPI 允许覆盖依赖：

```python
async def fake_llm_client():
    return FakeLLMClient()


app.dependency_overrides[get_llm_client] = fake_llm_client
```

然后测试：

```python
async def test_chat(...):
    ...
```

测试结束后必须清理：

```python
app.dependency_overrides.clear()
```

推荐使用 fixture 自动清理：

```python
@pytest.fixture
def override_llm_client():
    app.dependency_overrides[get_llm_client] = fake_llm_client
    try:
        yield
    finally:
        app.dependency_overrides.clear()
```

否则测试之间会互相污染。

---

## 15. 测试配置和缓存

项目使用：

```python
@lru_cache
def get_settings() -> Settings:
    ...
```

测试如果修改环境变量：

```python
monkeypatch.setenv("LLM_MODEL", "test-model")
```

必须清除缓存：

```python
get_settings.cache_clear()
```

完整模式：

```python
@pytest.fixture
def test_settings(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    monkeypatch.setenv("LLM_MODEL", "test-model")

    get_settings.cache_clear()
    try:
        yield get_settings()
    finally:
        get_settings.cache_clear()
```

否则：

```python
get_settings()
```

第一次返回旧配置后，后续测试可能一直使用旧值。

---

## 16. 测试应用状态

FastAPI 的 `app.state` 是进程/应用级状态，测试之间可能残留。

例如：

```python
app.state.llm_client = fake_client
```

测试完成后应清理：

```python
del app.state.llm_client
```

或者使用独立 app fixture：

```python
@pytest.fixture
def test_app():
    return create_app()
```

比多个测试共享同一个全局 `app` 更安全。

当前项目使用模块级：

```python
app = FastAPI(...)
```

因此要特别注意：

- `app.state`
- `dependency_overrides`
- `get_settings` 缓存
- 连接池
- lifespan

都要在测试边界内恢复。

---

## 17. 测试异常和取消

测试异常：

```python
with pytest.raises(TokenBudgetExceeded, match="上下文 Token 超限"):
    guard.validate_budget_or_raise(...)
```

测试取消：

```python
task = asyncio.create_task(consume_stream())
await asyncio.sleep(0.05)
task.cancel()

with pytest.raises(asyncio.CancelledError):
    await task
```

测试 TaskGroup 异常：

```python
with pytest.raises(ExceptionGroup):
    await run_bounded_task_group(...)
```

也可以检查异常组内容：

```python
with pytest.raises(ExceptionGroup) as exc_info:
    await run_bounded_task_group(...)

assert any(
    isinstance(exc, ValueError)
    for exc in exc_info.value.exceptions
)
```

---

## 18. 参数化测试

同一个逻辑多种输入：

```python
@pytest.mark.parametrize(
    ("status_code", "should_retry"),
    [
        (200, False),
        (401, False),
        (429, True),
        (500, True),
        (503, True),
    ],
)
def test_retry_policy(status_code: int, should_retry: bool) -> None:
    ...
```

参数化可以减少重复测试代码。

---

## 19. 避免测试中的时间不稳定

不要写：

```python
await asyncio.sleep(1)
assert task.done()
```

这种测试可能受机器性能影响。

优先使用：

- `asyncio.Event`
- `asyncio.Queue`
- `Mock`
- 可控的 fake clock
- 足够小的超时配合 `pytest.raises`

流式测试尤其要注意：

- 不要依赖固定睡眠时间
- 不要依赖真实网络延迟
- 不要依赖外部 API

---

## 20. 推荐的测试层次

**单元测试**

测试纯函数：

```python
count_text_tokens()
parse_sse_line()
validate_budget()
```

**组件测试**

测试一个服务类：

```python
NativeLLMClient
ProductionHttpClient
TokenBudgetGuard
```

使用 `MockTransport` 替代网络。

**API 测试**

用 `ASGITransport` 测试 FastAPI 路由。

**集成测试**

真实启动应用和真实依赖，通常数量较少。

测试金字塔：

```text
大量单元测试
    中等 API/组件测试
        少量真实集成测试
```

---

## 21. 常用 pytest 命令

```bash
uv run pytest
```

详细输出：

```bash
uv run pytest -vv
```

遇到第一个失败就停：

```bash
uv run pytest -x
```

只跑上次失败：

```bash
uv run pytest --lf
```

运行匹配名称：

```bash
uv run pytest -k "streaming or retry"
```

显示 print：

```bash
uv run pytest -s
```

---

**本课核心结论**

- 异步测试需要事件循环，项目当前使用 `@pytest.mark.asyncio`
- fixture 用 `yield` 管理资源生命周期
- 异步 fixture 使用 `pytest_asyncio.fixture`
- `ASGITransport` 测试 FastAPI，但不会自动执行 lifespan
- `MockTransport` 测试外部 HTTP，不访问真实网络
- `client.stream()` 测试真正的流式读取
- 测试必须清理 `dependency_overrides`、`app.state` 和 `lru_cache`
- 测试异常、取消、重试和流式边界时，要使用可控的 mock
- 不要让测试依赖真实网络和固定睡眠时间

---

**验收问题**

1. 普通 pytest 函数和异步 pytest 函数在声明上有什么区别？
2. fixture 中的 `yield` 前后分别对应什么生命周期？
3. 异步 fixture 通常应该使用什么 fixture 装饰器？
4. `ASGITransport` 的作用是什么？它会自动执行 lifespan 吗？
5. `MockTransport` 和 `ASGITransport` 的测试边界有什么区别？
6. 如何用 `MockTransport` 模拟一次 `ReadTimeout`？
7. 为什么测试完依赖覆盖后要执行 `app.dependency_overrides.clear()`？
8. 修改环境变量后为什么可能需要 `get_settings.cache_clear()`？
9. 测试流式 SSE 时，`client.post()` 和 `client.stream()` 有什么区别？
10. 如何测试一个被取消的异步任务，并验证它确实完成了清理？

按编号回答即可，我会逐题批改。

## 用户（原始消息 2319）

1. 普通函数直接定义就行，异步需要加 pytest.mock.asyncio 装饰器， 2. yield 之前，对应测试节点， yield 之后对应执行之后，此时需要完成清理 3. 使用 pytest_asyncio.fixure 装饰器 4. ASGITransport 用来测试 fastapi 应用，不走真实网络请求，不会自动执行 lifespan ，因此要手动执行。5. MockTransport 是测试外部请求，ASGITransport 测试fastapi应用本身  6. 抛出超时对应的 http 状态码 7. 为了避免其他测试在执行的时候，环境被污染 8. 为了避免拿到错误的配置 9. client.post 可能会等到所有流返回之后统一返回，stream 才可以真正测试流式 10. 调用 .calcel() 方法

## 助手（原始消息 2324）

**批改：8/10**

第 2、3、4、5、7、8、9 题基本正确；第 1 题是拼写问题；第 6 题概念错误；第 10 题不完整。

**1. 基本正确，但装饰器名称写错了**

不是：

```python
pytest.mock.asyncio
```

正确是：

```python
@pytest.mark.asyncio
async def test_something() -> None:
    ...
```

准确说法是“标记（marker）”，它告诉 `pytest-asyncio` 这个测试需要事件循环。

**2. 正确**

```python
@pytest.fixture
def resource():
    resource = setup()

    try:
        yield resource
        # 测试函数在这里执行
    finally:
        cleanup(resource)
```

执行顺序：

```text
yield 前：准备测试资源
测试函数执行
yield 后：清理测试资源
```

即使测试失败，`finally` 也应执行清理。

**3. 基本正确，但拼写应为 `fixture`**

```python
@pytest_asyncio.fixture
async def http_client():
    ...
```

不是 `fixure`。

异步 fixture 内部通常也使用 `async with` 或 `yield`：

```python
@pytest_asyncio.fixture
async def http_client():
    async with ProductionHttpClient(...) as client:
        yield client
```

**4. 正确**

`ASGITransport` 让 HTTPX 直接调用 ASGI/FastAPI 应用，不经过真实网络。

但它不会自动执行：

```python
app.router.lifespan_context(app)
```

所以测试中通常需要：

```python
async with app.router.lifespan_context(app):
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        ...
```

**5. 正确**

- `MockTransport`：模拟应用访问的外部 HTTP 服务
- `ASGITransport`：直接调用自己的 FastAPI 应用

可以理解为：

```text
MockTransport：模拟上游服务
ASGITransport：模拟浏览器/客户端访问本项目
```

**6. 错误**

`httpx.ReadTimeout` 不是 HTTP 状态码。

它是客户端网络层异常，表示：

> 已经建立连接，但等待读取响应数据超时。

模拟时应让 handler 抛异常：

```python
def handler(request: httpx.Request) -> httpx.Response:
    raise httpx.ReadTimeout("读取超时", request=request)
```

而不是返回一个“超时代码”。

需要区分：

```text
504 Gateway Timeout
    是 HTTP 响应状态码，通常由网关返回

httpx.ReadTimeout
    是本地 HTTP 客户端在读取阶段抛出的网络异常
```

**7. 基本正确，但要说准确**

`app.dependency_overrides` 是全局应用状态，不是系统环境变量。

如果测试结束后不清理：

```python
app.dependency_overrides.clear()
```

后续测试可能仍然拿到当前测试的 fake 依赖，造成测试之间的状态污染。

**8. 正确**

`get_settings` 使用了：

```python
@lru_cache
def get_settings() -> Settings:
    ...
```

修改环境变量后，如果不清理缓存，仍可能返回第一次读取的旧 `Settings`。

所以需要：

```python
get_settings.cache_clear()
```

通常 fixture 中这样写：

```python
@pytest.fixture
def test_settings(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "test-model")
    get_settings.cache_clear()

    try:
        yield get_settings()
    finally:
        get_settings.cache_clear()
```

**9. 正确**

`client.post()`通常会等待完整响应体读取完毕，然后返回最终响应。

`client.stream()`返回异步上下文管理器，可以边接收边处理：

```python
async with client.stream("POST", "/stream", json=payload) as response:
    async for line in response.aiter_lines():
        ...
```

SSE 测试更适合使用 `client.stream()`，因为可以验证：

- 第一帧什么时候到达
- 中途错误帧
- 流是否按预期结束
- 资源是否正确释放

**10. 不够完整**

`task.cancel()` 只是发出取消请求，不能保证任务已经停止。

需要等待任务结束，并验证清理逻辑：

```python
import asyncio
import pytest


@pytest.mark.asyncio
async def test_cancellation_cleanup() -> None:
    started = asyncio.Event()
    cleaned = asyncio.Event()

    async def worker() -> None:
        try:
            started.set()
            await asyncio.sleep(10)
        finally:
            cleaned.set()

    task = asyncio.create_task(worker())
    await started.wait()

    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert cleaned.is_set()
```

流程是：

```text
创建任务
    ↓
等待任务进入执行状态
    ↓
task.cancel()
    ↓
await task
    ↓
确认收到 CancelledError
    ↓
确认 finally 清理已经执行
```

还可以检查：

```python
assert task.cancelled()
```

但 `task.cancelled()` 只表示任务最终处于取消状态，不能证明你的业务清理已经完成，所以通常还需要一个 `cleaned` 标志或事件。

---

**本课最需要修正的点**

```text
ReadTimeout 是网络异常，不是 HTTP 状态码
dependency_overrides 是应用状态，不是环境变量
task.cancel() 是请求，await task 才能确认取消完成
```

下一步建议进入：**FastAPI/ASGI 运行机制与请求生命周期**，把路由、中间件、依赖、异常处理器和流式响应放在一条完整调用链中。回复“继续”开始。

