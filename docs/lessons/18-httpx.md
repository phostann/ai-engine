# HTTPX、连接池、超时、重试与流式请求

> 本文逐字转录自原始课程对话，只添加角色标题和来源信息，未改写、删减或二次总结。
>
- 返回：[课程原文索引](README.md)
- 原始消息序号：`2246`、`2281`、`2288`、`2300`

## 用户（原始消息 2246）

j继续

## 助手（原始消息 2281）

**本课知识点：HTTPX、连接池、超时、重试与流式请求**

这一课直接对应项目中的：

- `ProductionHttpClient`
- `NativeLLMClient`
- `httpx.AsyncClient`
- `httpx.MockTransport`
- 流式 `client.stream()`

核心目标不是记住 HTTPX API，而是理解：

```text
什么时候复用连接
什么时候会发生超时
哪些错误能重试
流式请求为什么不能随便重试
```

---

## 1. `httpx.AsyncClient` 应该复用

错误方式：

```python
async def call_llm():
    async with httpx.AsyncClient() as client:
        return await client.post(...)
```

每个请求都创建客户端，意味着：

- 每次都初始化连接池
- 每次可能重新建立 TCP/TLS 连接
- 连接无法跨请求复用
- 成本和延迟增加

正确方式是由应用生命周期管理一个全局客户端：

```python
async with ProductionHttpClient(...) as http_client:
    llm_client = NativeLLMClient(
        settings=settings,
        http_client=http_client,
    )
```

项目在 FastAPI lifespan 中完成这件事：

[C:\work\python\ai-agent-leran\ai-engine\src\ai_engine\main.py:29](C:\work\python\ai-agent-leran\ai-engine\src\ai_engine\main.py:29)

```python
async with ProductionHttpClient(base_url=settings.llm_base_url) as http_client:
    llm_client = NativeLLMClient(
        settings=settings,
        http_client=http_client,
        token_guard=token_guard,
    )
    app.state.llm_client = llm_client
    yield
```

`yield` 前创建客户端，`yield` 后关闭它。

---

## 2. `AsyncClient` 的连接池

项目中：

[C:\work\python\ai-agent-leran\ai-engine\src\ai_engine\core\http_client.py:22](C:\work\python\ai-agent-leran\ai-engine\src\ai_engine\core\http_client.py:22)

```python
self._limits = httpx.Limits(
    max_connections=max_connections,
    max_keepalive_connections=max_keepalive,
    keepalive_expiry=30.0,
)
```

主要参数含义：

**`max_connections`**

整个客户端同时允许的最大连接数。

如果设置为：

```python
max_connections=100
```

那么超过 100 个并发请求时，其余请求会等待连接释放。

**`max_keepalive_connections`**

连接池中最多保留多少个空闲长连接。

```python
max_keepalive_connections=20
```

并不是“总连接数最多 20”，而是空闲连接最多保留 20 个。

**`keepalive_expiry`**

空闲连接最多保留多久：

```python
keepalive_expiry=30.0
```

如果服务端已经提前关闭连接，客户端继续使用旧连接可能得到连接错误。因此连接池中的连接也需要健康处理。

---

## 3. HTTPX 的四种超时

项目：

[C:\work\python\ai-agent-leran\ai-engine\src\ai_engine\core\http_client.py:29](C:\work\python\ai-agent-leran\ai-engine\src\ai_engine\core\http_client.py:29)

```python
self._timeout = httpx.Timeout(
    connect=connect_timeout,
    read=read_timeout,
    write=10.0,
    pool=5.0,
)
```

### `connect`

建立 TCP 连接、TLS 握手的时间限制。

它不包括等待服务器返回业务数据的时间。

### `read`

等待服务器返回下一段响应数据的时间限制。

对普通请求，它接近“等待响应内容”的时间。

对流式请求，它表示：

> 两个数据块之间最多等待多久。

不是整个流的总时长。

例如：

```python
read=60
```

流持续了 10 分钟，但每 10 秒都能收到一个 token，通常不会触发 `read` 超时。

如果上游连续 60 秒没有任何数据，才可能触发 `ReadTimeout`。

### `write`

发送请求体的时间限制。

请求体很大，例如上传文件时，这个限制更重要。

### `pool`

从连接池等待可用连接的最长时间。

当 `max_connections` 已经被占满时，请求可能需要等待空闲连接。等待超过 `pool` 时间会触发 `PoolTimeout`。

### 没有总请求超时

`httpx.Timeout` 的 `read` 不是整个请求的总超时。

如果需要：

```python
async with asyncio.timeout(120):
    response = await client.request(...)
```

这表示整个操作最多 120 秒。

这两者含义不同：

```text
htpx.Timeout(read=60)       每次等待响应的时间限制
asyncio.timeout(120)        整个异步操作的总时间限制
```

---

## 4. 响应对象和 `raise_for_status()`

普通请求：

```python
response = await client.get("/health")
print(response.status_code)
print(response.text)
print(response.json())
```

如果希望 4xx/5xx 抛异常：

```python
response.raise_for_status()
```

`raise_for_status()` 不会自动决定“是否重试”，它只是：

```python
if response.status_code not in 2xx:
    raise httpx.HTTPStatusError(...)
```

是否重试由业务代码决定。

项目中：

[C:\work\python\ai-agent-leran\ai-engine\src\ai_engine\core\http_client.py:70](C:\work\python\ai-agent-leran\ai-engine\src\ai_engine\core\http_client.py:70)

```python
resp = await self.client.request(method, url, **kwargs)

if resp.status_code not in retryable_codes:
    resp.raise_for_status()
    return resp
```

含义是：

- 状态码不可重试：如果不是 2xx，直接抛 `HTTPStatusError`
- 状态码可重试：暂时不返回，构造错误并进入重试逻辑

---

## 5. HTTPX 主要异常类型

常见异常：

```python
httpx.TimeoutException
    ├── ConnectTimeout
    ├── ReadTimeout
    ├── WriteTimeout
    └── PoolTimeout

httpx.NetworkError
    ├── ConnectError
    ├── ReadError
    └── WriteError

httpx.ProtocolError
    ├── RemoteProtocolError
    └── LocalProtocolError

httpx.HTTPStatusError
```

它们含义不同：

- `ConnectTimeout`：连不上服务器
- `ReadTimeout`：连接成功后读不到数据
- `WriteTimeout`：请求发送太慢
- `PoolTimeout`：等待连接池中的连接太久
- `ConnectError`：DNS、TCP、TLS 等连接失败
- `ReadError` / `WriteError`：连接中断
- `HTTPStatusError`：服务端返回了非成功 HTTP 状态码

不要只写：

```python
except Exception:
    ...
```

这样无法区分超时、认证失败、协议错误和业务错误。

---

## 6. 重试要基于“可恢复性”

项目重试状态码：

```python
retryable_codes = {429, 500, 502, 503, 504}
```

这些通常表示：

- `429`：临时限流
- `500`：服务端内部错误，可能恢复
- `502`：上游网关错误
- `503`：服务暂时不可用
- `504`：上游超时

通常不重试：

```text
400 Bad Request
401 Unauthorized
403 Forbidden
404 Not Found
422 Unprocessable Entity
```

因为这些通常不会因为等待一会儿就变好。

还应考虑：

```python
408 Request Timeout
425 Too Early
```

这两个也可能适合重试。

---

## 7. Full-Jitter 退避

项目：

```python
max_sleep = base_delay * (2 ** (attempt - 1))
sleep_time = random.uniform(0.05, max_sleep)
await asyncio.sleep(sleep_time)
```

这个思路是在指数退避基础上加入随机抖动，避免大量请求同时重试形成“惊群”。

典型 Full-Jitter 更接近：

```python
retry_index = attempt - 1
cap = base_delay * (2**retry_index)
sleep_time = random.uniform(0, cap)
```

当前实现还有几个边界：

- 最低固定为 `0.05`
- 没有总上限
- 没有读取 `Retry-After`
- `max_retries=3` 实际是总尝试次数 3 次，不是“原始请求 + 3 次重试”
- 没有区分 `Retry-After` 是秒数还是 HTTP 日期

更严谨的重试参数通常包括：

```text
最大尝试次数
初始延迟
指数增长倍率
最大延迟
随机抖动
总超时
Retry-After
```

---

## 8. 重试必须考虑幂等性

GET 通常是安全、可重复的。

但是：

```http
POST /chat/completions
```

可能产生副作用：

- 消耗 Token
- 产生计费
- 创建会话
- 执行工具调用
- 修改数据库

如果在请求已经到达上游、上游已经处理、但客户端读响应超时的情况下重试，可能造成：

```text
重复扣费
重复生成
重复工具调用
```

所以重试不能只靠状态码判断，还要看业务操作是否幂等，以及是否有幂等键。

对于大模型流式请求，重试边界尤其重要：

```text
还没有向客户端发送任何 token
    → 可能允许重新建立上游连接

已经发送了部分 token
    → 通常不能透明重试整个请求
    → 只能发送 error 事件或让客户端重新发起请求
```

---

## 9. 普通请求和流式请求的区别

普通请求：

```python
response = await client.post("/chat", json=payload)
data = response.json()
```

HTTPX 通常会读取完整响应体后返回。

流式请求：

[C:\work\python\ai-agent-leran\ai-engine\src\ai_engine\services\llm_client.py:61](C:\work\python\ai-agent-leran\ai-engine\src\ai_engine\services\llm_client.py:61)

```python
async with self.http_client.client.stream(
    "POST",
    "/chat/completions",
    json=payload,
    headers=headers,
) as response:
    response.raise_for_status()

    async for line in response.aiter_lines():
        ...
```

关键差异：

- `client.stream()` 是异步上下文管理器
- 必须使用 `async with`
- 响应体逐步读取
- 读取期间连接仍然占用
- 退出后才会释放响应资源
- 不能忘记关闭

不要写成：

```python
response = await client.stream(...)
```

也不要读完不关闭。

---

## 10. 流式请求中的 read timeout

假设：

```python
read_timeout=60
```

上游正常输出：

```text
第 1 秒：你好
第 5 秒：我是
第 10 秒：AI
```

这些间隔都小于 60 秒，流可以持续很久。

如果上游突然停止发送数据：

```text
收到最后一个 token
        ↓
60 秒没有新数据
        ↓
ReadTimeout
```

因此流式接口通常还需要：

- 上游心跳
- 服务端 SSE ping
- 总时长限制
- 客户端断连检测

项目使用：

```python
EventSourceResponse(stream_generator, ping=15)
```

定期发送 SSE 注释帧，保持连接活跃。

---

## 11. `MockTransport` 测试

项目测试：

[C:\work\python\ai-agent-leran\ai-engine\tests\test_day6_core.py:35](C:\work\python\ai-agent-leran\ai-engine\tests\test_day6_core.py:35)

```python
def mock_sse_handler(request: httpx.Request) -> httpx.Response:
    ...
    return httpx.Response(
        200,
        content=sse_body,
        headers={"Content-Type": "text/event-stream"},
    )

http_client.client._transport = httpx.MockTransport(mock_sse_handler)
```

`MockTransport` 的作用是：

> 不发真实网络请求，直接由测试函数返回响应。

它可以测试：

- 状态码
- JSON 响应
- SSE 行
- 超时异常
- 网络异常
- 重试次数
- 请求头和请求体

但当前代码使用了：

```python
http_client.client._transport = ...
http_client.client._mounts.clear()
```

这是访问私有属性，测试能工作，但不够稳定。

更干净的方式是让测试可以注入 transport：

```python
transport = httpx.MockTransport(handler)
client = httpx.AsyncClient(
    base_url="https://mock.api.com",
    transport=transport,
)
```

测试不应依赖生产代码内部私有属性。

---

## 12. `ASGITransport` 和 `MockTransport` 的区别

`MockTransport`：

```python
httpx.MockTransport(handler)
```

模拟 HTTP 客户端到外部服务的通信。

`ASGITransport`：

```python
ASGITransport(app=app)
```

直接调用 FastAPI/ASGI 应用，不经过真实网络。

项目测试中：

```python
async with httpx.AsyncClient(
    transport=ASGITransport(app=app),
    base_url="http://test",
) as client:
    response = await client.post(...)
```

适合测试自己的 FastAPI 路由。

但 `ASGITransport` 不会自动执行 FastAPI lifespan：

```python
async with app.router.lifespan_context(app):
    ...
```

因此在测试中需要显式启动 lifespan，才能初始化全局连接池和 `app.state.llm_client`。

---

## 13. 当前流式测试的一个注意点

测试里使用了：

```python
httpx.Response(200, content=sse_body)
```

这会把整个 SSE 内容一次性作为内存响应返回。

它适合验证：

- SSE 解析
- token 拼接
- `[DONE]`
- 响应状态

但它不完全等同于真实的逐块网络流。

要测试真正的增量传输和背压，需要使用自定义 `AsyncByteStream` 或模拟分块读取。

---

## 14. 流式解析的边界

当前解析逻辑：

```python
async for line in response.aiter_lines():
    if not line or not line.startswith("data: "):
        continue

    data_str = line[len("data: ") :].strip()

    if data_str == "[DONE]":
        break

    chunk = json.loads(data_str)
```

能处理常见 OpenAI SSE，但还不够通用。

一个完整 SSE 解析器需要处理：

- `data:` 后面没有空格
- 多行 `data`
- 注释行 `: ping`
- `event:` 字段
- `id:` 字段
- 空行分隔事件
- JSON 解析失败
- 上游 `error` 事件
- `[DONE]` 终止

当前实现适合学习和小型网关，生产环境建议使用成熟的 SSE 解析器，或明确遵循上游协议并补充错误处理。

---

## 15. 代理缓冲问题

SSE 请求经过 Nginx、CDN、网关时，代理可能把数据缓冲起来，导致：

```text
上游已经发送 token
        ↓
代理先缓存
        ↓
浏览器很久后才收到
```

需要关闭代理缓冲，例如 Nginx 中常见配置：

```nginx
proxy_buffering off;
proxy_cache off;
X-Accel-Buffering: no;
```

具体配置取决于部署环境。这不是 HTTPX 客户端本身的问题，但会严重影响 SSE 体验。

---

## 16. 连接关闭和流式资源

流式代码：

```python
async with self.http_client.client.stream(...) as response:
    async for line in response.aiter_lines():
        yield token
```

退出 `async with` 后：

- 响应被关闭
- 连接归还连接池
- 如果连接不能复用，可能被关闭
- 当前占用的并发连接释放

如果在生成器外部使用：

```python
async with aclosing(llm_client.chat_stream(...)) as stream:
    async for token in stream:
        ...
```

则 `aclosing` 会关闭异步生成器，最终触发内部 `async with httpx.stream()` 的退出。

---

## 17. 项目结构上的一个改进方向

当前 `NativeLLMClient.chat_stream` 直接使用：

```python
self.http_client.client
```

这意味着它依赖底层 HTTPX 客户端的具体实现。

更可测试的设计是使用 Protocol：

```python
class StreamTransport(Protocol):
    def stream(
        self,
        method: str,
        url: str,
        **kwargs,
    ) -> AsyncIterator[httpx.Response]:
        ...
```

或者让 `NativeLLMClient` 依赖一个抽象接口：

```python
class LLMTransport(Protocol):
    def chat_stream(...) -> AsyncGenerator[str, None]:
        ...
```

这样业务层不需要知道 HTTPX 的具体细节，测试时也可以替换为假实现。

不过当前小型项目直接使用 HTTPX 是可以接受的，不必为了“架构漂亮”引入过多抽象。

---

**本课核心结论**

- `AsyncClient` 应复用，不要每个请求创建一次。
- 连接池的 `max_connections` 和 `max_keepalive_connections` 含义不同。
- `connect/read/write/pool` 是四种不同超时。
- `read` 超时是两次数据之间的等待，不等于整个流的总时长。
- `raise_for_status()` 只负责抛异常，不负责决定是否重试。
- 只重试临时网络错误、429 和部分 5xx。
- 重试必须考虑幂等性和 `Retry-After`。
- 流式请求只应通过 `async with client.stream()` 使用。
- `MockTransport` 测试外部 HTTP，`ASGITransport` 测试 FastAPI 应用。
- 流式接口要处理连接关闭、SSE 格式、代理缓冲和部分输出后的失败。

---

**验收问题**

1. 为什么不应该在每个请求处理函数里创建新的 `httpx.AsyncClient`？
2. `max_connections` 和 `max_keepalive_connections` 分别表示什么？
3. `connect`、`read`、`write`、`pool` 四种超时的区别是什么？
4. 流式请求中，`read` 超时是指整个流的最长持续时间吗？
5. `raise_for_status()` 会自动重试吗？它只做什么？
6. 哪些 HTTP 状态码通常可以重试？哪些通常不应该重试？
7. 当前项目 Full-Jitter 实现有哪些可以改进的地方？
8. 为什么流式响应已经输出部分 token 后不能透明重试整个请求？
9. `MockTransport` 和 `ASGITransport` 分别适合测试什么？
10. 为什么 `client.stream()` 必须配合 `async with` 使用？

按编号回答即可，我会逐题批改。

## 用户（原始消息 2288）

1. 每次创建都要建立连接，浪费资源，因此全局维护一份进行共享就行了 2. max_connections 表示最大连接数  max_keepalive_connections 表示最大长连接数 3. connect 表示 http 连接超时， read 表示通过   http 读取数据，write 表示向调用方返回数据的超时，pool 表示从连接池等待可用连接的最大超时时间  4. read 超时指的是两帧之间的时间 5。不会自动重试，他是会在状态码非 200 的时候抛出异常  6. 500 502 503 通常可以重试 429 401 403 通常不可以重试   7. 没有考虑 retry-after 以及总体超时 8. 可能会重复向客户端返回 。因此需要明确告知客户端，发生错误，让客户端重新发送整个请求 9. MockTransport 适合模拟 http 响应，不走真是请求， ASGITransport 适合直接测试 fastapi ，不用真实发送请求去触发 10. client.stream() 类似异步生成器，并且要考虑释放，因此必须配合 async with

## 助手（原始消息 2300）

**批改：8/10**

第 1、4、6、7、9 题基本正确；第 2、3、5、8、10 题需要修正或补充。

**1. 正确，但“全局”要限定范围**

`httpx.AsyncClient` 应该在应用生命周期内复用，避免每个请求重新建连接池。

项目在 lifespan 中创建一次：

```python
async with ProductionHttpClient(...) as http_client:
    app.state.llm_client = ...
    yield
```

但有三个边界：

- 每个 FastAPI worker 进程各有一份客户端
- 不要跨进程共享
- 不要跨事件循环共享同一个 `AsyncClient`

所以更准确地说：

> 每个进程、每个事件循环内复用一份客户端。

**2. 基本正确，但 `max_keepalive_connections` 不是“最大长连接数”**

```python
httpx.Limits(
    max_connections=100,
    max_keepalive_connections=20,
)
```

- `max_connections`：整个连接池最多同时存在多少连接
- `max_keepalive_connections`：连接空闲后，最多保留多少个可复用连接

如果当前有 100 个活跃连接，之后都变成空闲：

```text
最多保留 20 个空闲连接
其余空闲连接关闭
```

更准确叫法是：

> 最大空闲长连接数，或者连接池中最多保留的 keep-alive 连接数。

另外还有：

```python
keepalive_expiry=30.0
```

表示空闲连接最多保留 30 秒。

**3. `write` 的理解错了**

正确的是：

- `connect`：建立 TCP/TLS 连接的超时
- `read`：等待服务器返回数据的超时
- `write`：把请求体发送给服务器的超时
- `pool`：等待连接池中可用连接的超时

`write` 不是“向调用方返回数据”的超时。

例如上传大文件：

```python
await client.post("/upload", content=large_body)
```

发送请求体太慢，可能触发 `WriteTimeout`。

`read` 才是等待服务器响应数据的阶段。

**4. 正确，但“帧”要理解成数据块**

流式请求中：

```python
read_timeout=60
```

表示两次读取到数据之间最多等待 60 秒。

不一定是严格的“SSE 帧”，也可以理解为：

```text
上游网络数据块
token 数据块
SSE 事件块
```

只要超过 60 秒没有任何新数据，就可能触发 `ReadTimeout`。

注意：它不是整个流的 10 分钟总时长限制。

**5. 基本正确，但表述要改**

```python
response.raise_for_status()
```

不是“状态码非 200 才抛异常”，而是：

> 状态码不是 2xx 时抛出 `httpx.HTTPStatusError`。

常见情况：

```text
200、201、204 → 不抛异常
301、302        → 未被自动跟随重定向时也可能抛异常
400、401、404  → 抛异常
500、502、503  → 抛异常
```

它不会自动重试，只负责判断响应状态并抛异常。

**6. 正确，但可以补全**

通常可以重试：

```text
408
425
429
500
502
503
504
```

通常不重试：

```text
400
401
403
404
409
422
```

`500` 要谨慎：它可能是临时故障，也可能是代码永久错误。重试 500 必须配合次数上限、退避和监控。

**7. 正确**

当前 Full-Jitter 实现的改进点包括：

- 没有读取 `Retry-After`
- 没有总超时
- 没有最大退避上限
- 固定最小延迟 `0.05`
- `max_retries` 实际表示总尝试次数
- 没有区分 408、425
- 没有明确限制幂等请求
- 没有记录每次尝试的结构化信息

**8. 方向正确，但“让客户端重发”要谨慎**

流式响应已经输出部分 token 后：

```text
客户端已经看到：你好，我是
```

此时服务端不能透明地重新开始整个流，因为客户端会看到：

```text
你好，我是
你好，我是
```

更重要的是，上游可能已经：

- 消耗了 Token
- 产生了费用
- 修改了外部状态
- 执行了工具调用

正确策略通常是：

- 如果还没发送任何业务数据，可以尝试重新建立上游连接
- 如果已经发送了部分数据，发送 SSE `error` 事件
- 让客户端明确知道当前流已失败
- 是否允许重发由客户端和业务协议决定

更严谨的接口会加入：

- `request_id`
- `stream_id`
- 幂等键
- 可续传事件 ID
- 重试建议和 `retryable` 标记

**9. 正确**

- `MockTransport`：模拟外部 HTTP 响应，不走真实网络
- `ASGITransport`：直接调用 FastAPI/ASGI 应用，不走真实网络
- 两者都不能替代真实网络的全部行为

另外，`ASGITransport` 不会自动执行 lifespan，测试中通常要手动：

```python
async with app.router.lifespan_context(app):
    ...
```

**10. 基本正确**

更精确地说：

`client.stream()` 返回的是一个异步上下文管理器，管理底层响应和连接。

```python
async with client.stream("POST", url, json=payload) as response:
    async for line in response.aiter_lines():
        ...
```

必须使用 `async with` 的原因：

- 确保响应被关闭
- 确保连接归还连接池
- 异常或提前 `break` 时仍能释放资源
- 流式连接不会在请求结束后自动变成普通对象

`response.aiter_lines()` 才是异步迭代器；`client.stream()` 本身更准确地说是异步上下文管理器。

---

**本课最容易记错的点**

```text
connect：连接服务器
write：把请求体发给服务器
read：等待服务器返回数据
pool：等待连接池中的连接
```

以及：

```text
raise_for_status() 只抛异常，不负责重试
```

下一步建议进入：**pytest 与异步测试**，把 `MockTransport`、`ASGITransport`、lifespan、依赖覆盖和流式测试串起来。回复“继续”开始。

