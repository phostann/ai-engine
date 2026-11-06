# FastAPI / ASGI 请求生命周期与响应边界

> 本文逐字转录自原始课程对话，只添加角色标题和来源信息，未改写、删减或二次总结。
>
> 原始线程：`01a18013-ec26-74f1-a930-8f39f1524987`  
> 原始消息序号：`2569`、`2605`、`2612`、`2617`

## 用户（课程开始）

继续下一个知识点

## 助手（知识点讲解与考题）

补充一下提交状态：两个提交已经创建在本地 `master`，但远端推送尚未完成。SSH 返回 `Permission denied (publickey)`，HTTPS 凭据对话框又被取消，因此当前是 `master` 比 `origin/master` 领先 2 个提交。代码本身已提交，后续配置好 GitHub 凭据即可推送。

---

**本课知识点：FastAPI/ASGI 运行机制与请求生命周期**

前面已经分别学过：

- lifespan
- `Depends`
- 中间件
- 异常处理器
- SSE
- `ASGITransport`

这一课把它们放进同一条请求链路。

完整链路可以概括为：

```text
Uvicorn
    ↓
ASGI application
    ↓
ServerErrorMiddleware
    ↓
用户中间件
    ↓
ExceptionMiddleware
    ↓
Router
    ↓
路由匹配
    ↓
参数解析与 Pydantic 校验
    ↓
依赖注入
    ↓
路由函数
    ↓
Response
    ↓
反向经过中间件
    ↓
客户端
```

---

## 1. ASGI 是什么

ASGI 是异步 Web 服务器和 Python 应用之间的协议。

最核心的应用形式是：

```python
async def app(scope, receive, send) -> None:
    ...
```

三个参数：

- `scope`：连接元数据
- `receive`：接收客户端消息
- `send`：向客户端发送消息

常见 scope 类型：

```text
http
websocket
lifespan
```

HTTP 请求的 scope 中包含：

```python
{
    "type": "http",
    "method": "POST",
    "path": "/api/v1/chat/completions/stream",
    "headers": [...],
    "query_string": b"",
    "app": ...,
}
```

响应消息主要是：

```python
await send({
    "type": "http.response.start",
    "status": 200,
    "headers": [...],
})
```

然后发送响应体：

```python
await send({
    "type": "http.response.body",
    "body": b'{"status":"ok"}',
    "more_body": False,
})
```

---

## 2. lifespan 和 middleware 不是一回事

### lifespan

lifespan 管理整个应用的启动和关闭：

```text
应用启动 → lifespan 进入
处理很多请求
应用关闭 → lifespan 退出
```

项目：

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    async with ProductionHttpClient(...) as http_client:
        app.state.llm_client = ...
        yield
```

`lifespan` 中的一个 `yield` 可以覆盖成千上万个请求。

### middleware

middleware 管理每个请求或响应：

```text
每个 HTTP 请求进入中间件
    ↓
进入路由
    ↓
响应返回中间件
```

中间件适合：

- 请求 ID
- 日志
- 耗时统计
- CORS
- 压缩
- 访问控制
- 响应头
- 限流

lifespan 适合：

- 数据库连接池
- HTTP 客户端
- 配置初始化
- 全局缓存
- 后台任务启动与停止

---

## 3. FastAPI 基于 Starlette

FastAPI 的底层 Web 框架是 Starlette。

大致关系：

```text
Uvicorn
    ↓
Starlette 应用
    ↓
FastAPI
    ↓
APIRouter
    ↓
路由函数
```

FastAPI 主要增加了：

- Pydantic 请求和响应校验
- 依赖注入
- OpenAPI 文档
- 参数绑定
- 更丰富的异常处理
- `response_model`

---

## 4. 请求处理顺序

一次请求大致经过：

```text
1. Uvicorn 接收 HTTP 请求
2. 构造 ASGI scope
3. 进入最外层中间件
4. 进入下一层中间件
5. 进入 FastAPI/Starlette 路由
6. 匹配路由路径和 HTTP 方法
7. 解析 query、path、header、body
8. Pydantic 校验请求模型
9. 解析依赖树
10. 执行路由函数
11. 生成响应
12. 响应按相反顺序经过中间件
13. Uvicorn 发送响应
```

如果请求模型校验失败：

```text
第 8 步失败
    ↓
路由函数不执行
    ↓
FastAPI 返回 422
```

如果路由函数中的普通参数出错：

```text
第 9 或第 10 步失败
    ↓
进入异常处理
    ↓
返回 500 或自定义错误
```

---

## 5. 路由匹配

FastAPI 会按注册顺序匹配路由。

例如：

```python
@app.get("/users/me")
async def current_user():
    ...

@app.get("/users/{user_id}")
async def get_user(user_id: str):
    ...
```

`/users/me` 要放在 `/users/{user_id}` 前面，否则 `me` 可能被当成 `user_id`。

这不是 Pydantic 的问题，而是路由匹配顺序问题。

---

## 6. 依赖注入发生在路由函数之前

项目：

```python
async def stream_chat_completions(
    request: Request,
    body: GatewayChatRequest,
    llm_client: LLMClientDep,
    trace_id: TraceIdDep,
):
    ...
```

FastAPI 会先准备：

- `request`
- `body`
- `llm_client`
- `trace_id`

然后才调用路由函数。

依赖本质上是一棵依赖树：

```text
stream_chat_completions
├── Request
├── GatewayChatRequest
├── LLMClientDep
│   └── get_llm_client
│       └── request.app.state
└── TraceIdDep
    └── get_request_trace_id
        ├── Header
        └── ContextVar
```

同一个请求中，如果依赖参数相同并且 `use_cache=True`，同一依赖通常只计算一次。

注意：`use_cache` 是请求内的缓存，不是跨请求缓存。

---

## 7. yield 依赖的清理时机

```python
async def get_request_trace_id(...):
    token = _trace_id_var.set(trace_id)
    try:
        yield trace_id
    finally:
        _trace_id_var.reset(token)
```

yield 前执行依赖初始化，yield 后执行清理。

需要特别注意：

> 依赖的清理时机可能随 FastAPI 版本变化。

当前 `uv.lock` 中 FastAPI 是 `0.162.0`。在这个版本下，yield 依赖的退出代码通常在响应发送完成后执行；具体行为应与实际版本和流式响应测试保持一致。

因此不要假设：

```text
路由函数返回时，trace_id 立刻被重置
```

对 SSE，请求上下文可能覆盖整个流式响应生命周期。

---

## 8. 中间件的基本写法

函数式 HTTP 中间件：

```python
from fastapi import Request


@app.middleware("http")
async def add_request_id(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Request-Id"] = "..."
    return response
```

执行过程：

```text
请求进入 add_request_id
    ↓
call_next(request)
    ↓
路由和依赖
    ↓
响应返回
    ↓
中间件修改响应头
    ↓
返回响应
```

注意：

- `call_next()` 是异步的
- 必须等待 `call_next()`
- 中间件也可以直接返回响应，短路路由

---

## 9. 中间件顺序

Starlette 的 `add_middleware()` 会构造一个包装栈。

例如：

```python
app.add_middleware(A)
app.add_middleware(B)
```

通常请求顺序是：

```text
B
    ↓
A
    ↓
路由
    ↓
A 的后置逻辑
    ↓
B 的后置逻辑
```

也就是说，后添加的中间件通常更靠外，先处理请求，后处理响应。

但中间件顺序容易受框架实现影响，生产代码应写测试验证，不要只靠记忆。

---

## 10. CORS 中间件

项目：

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

CORS 主要处理：

- 简单跨域请求
- 预检请求 `OPTIONS`
- `Access-Control-Allow-Origin`
- `Access-Control-Allow-Methods`
- `Access-Control-Allow-Headers`

预检请求可能在进入路由前就被 CORS 中间件处理。

需要知道一个安全边界：

```python
allow_origins=["*"]
allow_credentials=True
```

组合需要谨慎。允许携带凭据时，不应随便允许所有来源。生产环境通常使用明确的白名单。

---

## 11. 中间件如何读取请求

可以读取：

```python
request.method
request.url
request.headers
request.client
request.state
```

读取请求体要小心：

```python
body = await request.body()
```

请求体通常只能被底层接收一次。虽然 Starlette 的 `Request` 可能缓存部分内容，但中间件读取 body 后，下游可能拿不到预期内容。

更安全的做法：

- 通用日志只记录方法、路径、状态码和长度
- 需要业务字段时在路由或依赖中读取
- 如果中间件必须改写 body，需要包装 `receive`，不要直接消费

---

## 12. `request.state` 与 `app.state`

```python
app.state.llm_client
```

应用级状态：

- lifespan 初始化
- 多个请求共享
- 每个 worker 独立
- 适合连接池、配置、单例服务

```python
request.state.user
```

请求级状态：

- 每个请求独立
- 中间件、依赖、路由之间共享
- 请求结束后不应长期保存

例如认证中间件：

```python
request.state.user = user
```

路由读取：

```python
user = request.state.user
```

不要把请求级用户信息放到 `app.state`。

---

## 13. 中间件中的 ContextVar

可以在中间件中设置请求上下文：

```python
@app.middleware("http")
async def trace_middleware(request: Request, call_next):
    token = _trace_id_var.set(request.headers.get("X-Trace-ID", "system"))
    try:
        return await call_next(request)
    finally:
        _trace_id_var.reset(token)
```

与 FastAPI 依赖版本相比，中间件方式更直接覆盖整个请求生命周期。

但要注意：

- 必须使用 `try/finally` 重置 token
- 不能在 finally 中吞掉异常
- 流式响应可能让中间件生命周期持续很久
- 子任务会复制当前 ContextVar 快照

---

## 14. 中间件与流式响应

正确的流式链路：

```text
中间件
    ↓
EventSourceResponse
    ↓
不断发送 http.response.body
    more_body=True
    ↓
最后发送 more_body=False
```

中间件不要在 SSE 场景中：

- 把整个响应体读入内存
- 等待流完全结束后才转发
- 对响应内容做全量压缩
- 修改已经发送的响应头

否则可能导致：

- SSE 不流式
- 首帧延迟
- 内存增长
- 客户端收不到心跳
- 断连检测失效

对于流式响应，优先使用纯 ASGI 中间件或明确的流式转发方式，避免做全量缓冲。

---

## 15. 异常处理在链路中的位置

FastAPI 和 Starlette 有不同层次的异常处理：

```text
路由/依赖
    ↓
ExceptionMiddleware
    ↓
用户中间件
    ↓
ServerErrorMiddleware
```

大致语义：

- 路由中的 `HTTPException` 通常由 FastAPI/Starlette 转换成 HTTP 响应
- `RequestValidationError` 通常转换成 422
- 未处理的普通异常可能转换成 500
- 最外层 ServerErrorMiddleware 负责最终兜底

如果中间件自己抛出异常，不要假设路由层的 `HTTPException` 处理器一定会接手。中间件应：

- 明确返回错误 Response，或
- 记录后继续抛出，让外层处理

---

## 16. SSE 已经发送响应头后

一旦发送：

```http
HTTP/1.1 200 OK
Content-Type: text/event-stream
```

就不能再把状态码改成 500。

后续只能发送：

```text
event: error
data: {"code":"UPSTREAM_ERROR","message":"..."}
```

中间件和异常处理器都无法改变已经发送的 HTTP 状态码。

---

## 17. 客户端断开

流式响应期间客户端断开时，ASGI 服务器可能：

- 取消当前响应任务
- 调用响应生成器的关闭逻辑
- 让 `await send()` 失败
- 触发 `CancelledError`

因此流式路由要正确处理：

- `request.is_disconnected()`
- `CancelledError`
- `aclosing()`
- `finally` 清理
- 上游 HTTP 连接关闭

---

## 18. ASGI 中间件和 BaseHTTPMiddleware

Starlette 提供：

```python
BaseHTTPMiddleware
```

它使用：

```python
response = await call_next(request)
```

优点是写法简单。

但对于流式、底层 ASGI 消息和某些上下文场景，纯 ASGI 中间件更可控：

```python
class MyMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        await self.app(scope, receive, send)
```

纯 ASGI 中间件可以直接观察：

- `http.response.start`
- `http.response.body`
- `more_body`
- `lifespan`
- `websocket`

如果项目对 SSE 和背压要求高，应优先考虑纯 ASGI 实现。

---

## 19. 测试中的 ASGI

`ASGITransport` 会直接调用 ASGI 应用：

```python
transport = ASGITransport(app=app)
```

这会让：

- 路由执行
- 中间件执行
- 依赖解析执行
- 响应发送执行

但不会自动执行 lifespan：

```python
async with app.router.lifespan_context(app):
    ...
```

测试 SSE 时使用：

```python
async with client.stream("POST", url, json=body) as response:
    ...
```

这样才能验证中间件是否破坏了流式行为。

---

## 20. 当前项目生命周期总结

启动：

```text
Uvicorn 启动
    ↓
创建 FastAPI app
    ↓
触发 lifespan startup
    ↓
读取配置
    ↓
创建 TokenBudgetGuard
    ↓
创建 ProductionHttpClient
    ↓
创建 NativeLLMClient
    ↓
挂载 app.state
    ↓
开始接收请求
```

请求：

```text
请求进入 CORS 中间件
    ↓
FastAPI 路由匹配
    ↓
GatewayChatRequest 校验
    ↓
get_llm_client 依赖
    ↓
get_request_trace_id 依赖
    ↓
路由函数返回 EventSourceResponse
    ↓
生成器逐帧发送
    ↓
客户端断开或流结束
    ↓
关闭上游生成器和 HTTP 响应
```

关闭：

```text
Uvicorn 停止接收请求
    ↓
lifespan shutdown
    ↓
退出 ProductionHttpClient
    ↓
关闭 HTTPX 连接池
    ↓
进程退出
```

---

**本课核心结论**

- lifespan 管应用生命周期，middleware 管单个请求生命周期。
- FastAPI 基于 Starlette，ASGI 的核心是 `scope`、`receive`、`send`。
- 请求先经过中间件，再做路由匹配、参数校验、依赖注入和路由函数。
- 响应会按相反顺序经过中间件。
- 后添加的中间件通常更靠外。
- 中间件不要随意读取或消费请求体。
- SSE 中间件不能全量缓冲响应。
- `app.state` 是应用级，`request.state` 是请求级。
- 路由中的 `HTTPException` 与中间件抛异常的处理边界不同。
- 流式响应开始后不能再修改 HTTP 状态码。
- `ASGITransport` 会执行中间件和路由，但不会自动执行 lifespan。

---

**验收问题**

1. ASGI 应用的三个核心参数是什么？
2. lifespan 和 middleware 的生命周期有什么区别？
3. FastAPI 请求处理的先后顺序是什么？
4. 为什么参数校验失败时路由函数通常不会执行？
5. `use_cache=True` 的依赖缓存作用范围是什么？
6. 后添加的中间件通常位于内层还是外层？
7. 为什么中间件不应该随便执行 `await request.body()`？
8. `app.state` 和 `request.state` 分别适合保存什么？
9. 为什么 SSE 中间件不能把整个响应缓冲后再返回？
10. `ASGITransport` 会执行 lifespan 吗？测试时应该怎么处理？

按编号回答即可，我会逐题批改。

## 用户（作答）

1. 三大核心是 scope recive send 2. lifespan 是整个应用的生命周期，middleware 中间件则和每次请求有关，3. 路径匹配 ， 参数校验，依赖注入，路由函数执行，返回响应  4. 参数校验 就直接返回 422 了 不会到路由函数执行这一步 5. 作用范围是某次请求 6. 后添加的位于外层 7. body 只能读取一次，所以不要随便读取  8. app.state 适合进程级的数据共享 ，request.state 适合单次请求间的共享 9. 缓冲后就失去了流式的意义，并且可能会导致超时。10 。不会执行，测试时使用 app.router.life_span(app)  会手动执行

## 助手（批改）

**批改：8/10**

第 2、4、5、6、7、9 题正确；第 1 题是拼写问题；第 3、8、10 题需要补充或修正。

**1. 正确，拼写应为 `receive`**

```python
async def app(scope, receive, send) -> None:
    ...
```

- `scope`：连接元数据
- `receive`：接收客户端消息
- `send`：发送响应消息

**2. 正确**

- lifespan：整个应用启动到关闭
- middleware：每个 HTTP 请求或响应经过一次

可以理解为：

```text
lifespan 包围整个服务
middleware 包围每次请求
```

**3. 不完整**

除了路径匹配、参数校验、依赖注入和路由函数，还应包含中间件和响应阶段：

```text
ASGI 请求
    ↓
外层 middleware
    ↓
内层 middleware
    ↓
路由匹配
    ↓
解析参数、依赖和请求体
    ↓
Pydantic 校验
    ↓
路由函数
    ↓
生成 Response
    ↓
反向经过 middleware
    ↓
发送给客户端
```

FastAPI 内部的参数解析、依赖解析和嵌套依赖通常是一起处理的，所以不要过度依赖某两个步骤的严格先后；但可以确定：

- 中间件在路由外层
- 请求模型校验失败后，路由函数不会执行
- 响应生成后会反向经过中间件

**4. 正确**

默认情况下，请求体或参数校验失败会产生 `RequestValidationError`，FastAPI 返回 422：

```json
{
  "detail": [
    {
      "loc": ["body", "prompt"],
      "msg": "String should have at least 1 character",
      "type": "string_too_short"
    }
  ]
}
```

路由函数不会执行。

如果注册了自定义异常处理器，也可以改变最终响应格式和状态码。

**5. 正确**

`use_cache=True` 的缓存范围是：

```text
同一个请求内部
```

不是跨请求缓存，也不是进程级缓存。

同一个请求中多个地方依赖相同函数、相同参数时，可以复用第一次的结果。

**6. 正确**

在 Starlette 的 `add_middleware()` 机制下，后添加的中间件通常更靠外：

```python
app.add_middleware(A)
app.add_middleware(B)
```

请求通常先经过：

```text
B → A → 路由
```

响应返回时：

```text
路由 → A → B
```

生产代码仍建议通过测试确认实际顺序。

**7. 正确，但可以补充原因**

请求体通常由底层的 `receive` 消息流提供，不能假设可以无限次读取。

Starlette 的 `Request` 可能缓存已经读取的 body，但中间件直接消费请求体仍可能影响下游，尤其是流式请求和自定义 ASGI 中间件。

所以中间件应尽量只读取：

- method
- path
- headers
- client
- content-length
- 状态码

不要在通用中间件里随便解析整个请求体。

**8. 基本正确，但“进程级”要更精确**

`app.state`：

- 属于一个 FastAPI app 实例
- 通常在 lifespan 中初始化
- 每个 worker 进程各有一份
- 不能跨进程共享
- 适合连接池、配置、全局客户端等

准确说法不是所有情况下都“进程级共享”，而是：

> 同一个 app 实例共享，每个 worker 进程独立。

`request.state`：

- 属于单个请求
- 可以在 middleware、依赖和路由函数之间共享
- 请求结束后不应继续使用
- 适合保存当前用户、请求 ID、权限信息等

**9. 正确**

缓冲 SSE 会破坏流式语义，因为客户端无法及时收到：

- 首帧
- 心跳
- 中间 token
- 中途错误事件

还可能导致：

- 长时间无数据，代理或客户端超时
- 内存持续增长
- 背压失效
- 客户端断开后服务端仍继续生成

流式中间件应该逐块转发 `http.response.body`，并保留 `more_body=True` 的分块语义。

**10. 概念正确，方法名写错了**

不是：

```python
app.router.life_span(app)
```

项目中使用的是：

```python
async with app.router.lifespan_context(app):
    ...
```

`ASGITransport` 不会自动执行 lifespan，因此测试中要手动进入 lifespan 上下文：

```python
async with app.router.lifespan_context(app):
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        ...
```

---

**本课最需要记住的链路**

```text
middleware
    ↓
router
    ↓
参数与依赖解析
    ↓
Pydantic 校验
    ↓
路由函数
    ↓
Response
    ↓
middleware 反向返回
    ↓
客户端
```

以及：

```text
app.state：app 实例级，每个 worker 独立
request.state：单次请求级
use_cache：单次请求内
ASGITransport：不自动执行 lifespan
```

下一步建议进入：**日志、追踪与可观测性**，重点讲 `logging` 层级、handler/formatter/filter、trace_id、异常日志脱敏，以及如何记录上游耗时和重试次数。回复“继续”开始。

