# FastAPI 依赖注入 Depends

> 本文逐字转录自原始课程对话，只添加角色标题和来源信息，未改写、删减或二次总结。
>
- 返回：[课程原文索引](README.md)
- 原始消息序号：`902`、`907`、`922`、`929`、`934`、`995`、`1002`、`1007`

## 用户（原始消息 902）

继续

## 助手（原始消息 907）

下一课学 **FastAPI 依赖注入（`Depends`）与依赖树**。项目里的 `LLMClientDep`、`TraceIdDep`、`use_cache=True` 和 `yield` 依赖都属于这一套机制；理解它以后，路由函数、鉴权、数据库会话和资源获取会变得一致。

## 助手（原始消息 922）

我注意到工作区里 `src\ai_engine\api\deps.py` 在我们对话期间发生了变化：之前有 `get_http_client` 和 `HttpClientDep`，现在搜索结果中只剩 `TraceIdDep` 和 `LLMClientDep`。

这是你刚刚主动修改的吗？确认后我再继续讲 FastAPI 依赖注入，避免基于过时代码讲解。

## 用户（原始消息 929）

是我的修改

## 助手（原始消息 934）

确认了，我基于你当前版本继续讲。先读一下修改后的依赖文件，后面的例子都按现有代码来。

## 助手（原始消息 995）

**下一课：FastAPI 依赖注入 `Depends`**

依赖注入解决的问题是：路由函数只声明“我需要什么”，不负责“如何创建、从哪里取得、什么时候清理”。

当前项目的三个例子：

```python
TraceIdDep = Annotated[str, Depends(get_request_trace_id, use_cache=True)]
LLMClientDep = Annotated[NativeLLMClient, Depends(get_llm_client, use_cache=True)]
```

路由只需要声明：

```python
async def stream_chat_completions(
    request: Request,
    body: GatewayChatRequest,
    llm_client: LLMClientDep,
    trace_id: TraceIdDep,
) -> EventSourceResponse:
```

FastAPI 会自动取得这两个值，然后调用路由函数。

**1. `Depends` 的基本原理**

```python
def get_name() -> str:
    return "Alice"

@app.get("/")
async def endpoint(name: Annotated[str, Depends(get_name)]) -> dict[str, str]:
    return {"name": name}
```

处理请求时，FastAPI 大致执行：

```python
name = get_name()
result = await endpoint(name=name)
```

因此依赖函数不是普通默认值：

```python
# 错误：路由定义时就会调用一次，而且以后始终是同一个值
name: str = get_name()

# 错误：这里直接调用了函数，传给 Depends 的是结果
name: Annotated[str, Depends(get_name())]

# 正确：传函数对象，让 FastAPI 在请求到来时调用
name: Annotated[str, Depends(get_name)]
```

**2. `Annotated` 类型别名为什么好用**

原始写法：

```python
async def endpoint(
    trace_id: Annotated[str, Depends(get_request_trace_id)],
):
    ...
```

多个路由都需要时就会重复。项目将其提取成别名：

```python
TraceIdDep = Annotated[str, Depends(get_request_trace_id)]

async def endpoint(trace_id: TraceIdDep):
    ...
```

类型含义仍然保留：

```text
运行时值是 str
取得方式是 get_request_trace_id
```

这比把类型写成 `Any` 更好，IDE 和类型检查器知道 `trace_id` 是字符串。

**3. 依赖函数还可以声明自己的请求参数**

当前 `get_request_trace_id` 声明：

```python
async def get_request_trace_id(
    x_trace_id: Annotated[str | None, Header(alias="X-Trace-ID")] = None,
) -> AsyncIterable[str]:
```

依赖函数内部也可以使用 FastAPI 的参数系统：

- `Header`
- `Query`
- `Path`
- `Cookie`
- `Body`
- `Request`
- 其他 `Depends`

所以 HTTP 请求头会先被解析，再调用这个依赖：

```text
读取 X-Trace-ID
  ↓
没有则生成 trace_id
  ↓
设置 ContextVar
  ↓
把 trace_id 注入路由函数
```

`Header(alias="X-Trace-ID")` 表示 Python 参数使用 `x_trace_id`，HTTP 头使用 `X-Trace-ID`。HTTP 头名称本身不区分大小写。

**4. 依赖可以形成依赖树**

```python
async def get_settings_dep() -> Settings:
    return get_settings()


async def get_llm_client(
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> NativeLLMClient:
    ...
```

执行顺序是：

```text
get_settings_dep
  ↓
get_llm_client
  ↓
路由函数
```

FastAPI 在注册路由时分析函数签名，建立依赖关系；请求到来时递归解析这个依赖树。

**5. `use_cache=True` 是什么**

FastAPI 默认在同一个请求内缓存依赖结果。

```python
async def get_database():
    print("创建数据库会话")
    return DatabaseSession()
```

```python
DBDep = Annotated[DatabaseSession, Depends(get_database)]

async def get_audit_service(db: DBDep):
    return AuditService(db)

@app.get("/items")
async def endpoint(
    db: DBDep,
    audit: Annotated[AuditService, Depends(get_audit_service)],
):
    ...
```

在这个请求中，`get_database` 只会调用一次：

```text
路由直接依赖 db
审计服务也间接依赖 db
    ↓
两者收到同一个 DatabaseSession
```

如果设置为：

```python
Depends(get_database, use_cache=False)
```

同一个请求里多次声明它，就可能多次创建对象。

使用规则：

- 数据库会话、当前用户、`trace_id`：通常使用缓存。
- 每次都需要独立实例的对象：使用 `use_cache=False`。
- 不确定时不要随意关闭缓存，否则可能创建多个数据库事务或会话。

当前写 `use_cache=True` 虽然等于默认值，但明确表达了“一个请求内复用同一个实例”的意图。

**6. 带 `yield` 的依赖**

```python
async def get_request_trace_id(...):
    token = _trace_id_var.set(trace_id)
    try:
        yield trace_id
    finally:
        _trace_id_var.reset(token)
```

它不是普通返回值，而是请求级上下文管理器：

```text
yield 前：设置 ContextVar
yield 值：注入路由参数
请求结束：执行 finally，恢复 ContextVar
```

数据库会话也是同样模式：

```python
async def get_db():
    async with SessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
```

连接池由 `lifespan` 管理，会话由请求依赖管理：

```text
lifespan           → 创建连接池
请求依赖 get_db    → 从连接池取得一个会话
请求结束           → 归还会话
lifespan 关闭      → 关闭连接池
```

**7. 依赖清理顺序**

如果 A 依赖 B：

```python
async def get_b():
    print("B enter")
    yield B()
    print("B exit")


async def get_a(b: Annotated[B, Depends(get_b)]):
    print("A enter")
    yield A(b)
    print("A exit")
```

执行顺序是：

```text
B enter
A enter
路由函数
A exit
B exit
```

仍然是后创建、先清理。上层对象先停止使用，底层资源再关闭。

**8. `scope="function"` 与 `scope="request"`**

你当前使用的 FastAPI 版本还支持：

```python
Depends(get_resource, scope="request")
```

两种范围的区别是：

- `scope="function"`：路由函数返回响应对象后，在响应真正发送给客户端之前清理。
- `scope="request"`：整个响应发送完成后清理。

对于当前 SSE 流式接口，这个区别非常重要：

```text
路由函数返回 EventSourceResponse
  ↓
如果 scope="function"
  ↓
trace_id 依赖可能已经 reset
  ↓
但 SSE 还在继续输出
```

这会导致流式输出期间的日志丢失 `trace_id`。

当前带 `yield` 的依赖默认按 `request` 范围处理，所以 `TraceIdDep` 能覆盖整个 SSE 响应的发送过程。不要为了“早点释放”随意改成 `function`。

**9. 依赖覆盖与测试**

FastAPI 支持：

```python
app.dependency_overrides[get_llm_client] = lambda: FakeLLMClient()
```

这样测试路由时不会访问真实大模型服务。测试结束后应清理：

```python
try:
    app.dependency_overrides[get_llm_client] = fake_factory
    ...
finally:
    app.dependency_overrides.clear()
```

这也正好解释了之前失败的流式测试：它通过 `ASGITransport` 调用了真实应用，却没有覆盖 `get_llm_client`，最终真的访问了上游服务并得到 404。

依赖覆盖的键必须是原始依赖函数：

```python
app.dependency_overrides[get_llm_client]
```

不是类型别名：

```python
# 错误
app.dependency_overrides[LLMClientDep]
```

**10. 同步依赖和异步依赖**

```python
def sync_dependency():
    ...
```

普通同步依赖会由 FastAPI 放到线程池执行。

```python
async def async_dependency():
    ...
```

异步依赖直接在事件循环中执行。

所以异步依赖中不要放阻塞操作：

```python
async def bad_dependency():
    time.sleep(5)          # 阻塞整个事件循环
    requests.get(...)      # 同步网络库，阻塞事件循环
```

应该使用异步库或把阻塞部分放进线程池。

**11. 依赖注入不等于全局变量**

FastAPI 依赖可以访问 `Request`，但不应把所有东西都做成全局变量：

```python
# 可以，但不要滥用
async def get_everything(request: Request):
    return request.app.state
```

好的依赖应该只提供明确能力：

```python
get_current_user()
get_database_session()
get_trace_id()
get_llm_client()
require_admin()
```

路由需要什么，就声明什么。

**12. 当前项目完整请求链路**

```text
HTTP 请求
  ↓
FastAPI 解析 GatewayChatRequest
  ↓
解析 Header 中的 X-Trace-ID
  ↓
执行 get_request_trace_id
  ↓
设置 trace_id ContextVar
  ↓
执行 get_llm_client
  ↓
从 app.state 取得 NativeLLMClient
  ↓
调用 stream_chat_completions
  ↓
返回 EventSourceResponse
  ↓
SSE 持续输出
  ↓
响应完成
  ↓
get_request_trace_id 执行 finally
  ↓
恢复 ContextVar
```

**掌握标准**

你应该能够回答：

1. `Depends(get_func)` 和 `Depends(get_func())` 有什么区别？
2. 为什么多个函数依赖同一个依赖时，默认只创建一次？
3. `yield` 依赖的清理在什么时候执行？
4. 为什么多个请求使用同一个 ContextVar 变量名，却不会串数据？
5. 为什么连接池放 `lifespan`，数据库会话放请求依赖？
6. 为什么 SSE 接口不能随便把依赖范围改成 `function`？
7. 测试时怎样替换真实 LLM 客户端而不发网络请求？

这些是 `Depends` 的核心内容。下一课可以继续学习 **ContextVar 与异步请求上下文隔离**，或者 **Pydantic 请求模型与响应模型**。

## 用户（原始消息 1002）

1. Depends(get_func) 是正确用法，fastapi 会在需要的地方调用 get_func 后者是错误用法。2. 创建多次的话，就会造成不一致，并且额外消耗资源 3. yield 在请求完成后或者发生异常后，执行 finally 里面的清理方法 4. 因为python 派生协程会复制父协程的变量，也就是子协程使用的其实是副本 5. 因为连接池不应该创建多个，会拖慢性能，并且可能会造成系统资源耗尽，因此要放全局，为什么会话要放请求，因为会话是独立的，会话可能包含事务，事务必须独立，并且回话完成就没必要在继续维持资源消耗了。需要释放。6. 改成function之后，可能第一帧数据返回 contextvar 就被重置了，导致trace_id 串号等问题 7. 使用 dependency_overrides 并提供真实方法

## 助手（原始消息 1007）

大部分正确。第 1、2、3、5 点已经掌握；第 4、6、7 点需要修正。

**第 4 点：ContextVar 的复制机制**

更准确地说，不是“派生协程时复制变量”，而是：

- Python 的异步任务是运行在 `Context` 中的。
- 创建 `asyncio.Task` 时，会复制当前上下文，作为新任务的上下文快照。
- `ContextVar.set()` 只修改当前上下文。
- 子任务中再修改变量，不会反向影响父任务。
- 两个请求任务拥有不同的上下文，因此不会互相覆盖 `trace_id`。

可以理解为：

```text
请求 A 的上下文：trace_id = A
请求 B 的上下文：trace_id = B

A 中 set/reset 只影响 A 的上下文
B 中 set/reset 只影响 B 的上下文
```

这正是项目用 `ContextVar`，而不是模块级字符串保存 `trace_id` 的原因。

**第 6 点：会丢失追踪信息，但不是串号**

`scope="function"` 的执行顺序是：

```text
get_request_trace_id 执行到 yield
  ↓
路由函数返回 EventSourceResponse
  ↓
清理依赖，执行 _trace_id_var.reset(token)
  ↓
EventSourceResponse 开始向客户端持续发送数据
```

所以 SSE 实际输出期间，依赖已经清理了。此时日志看到的不是另一个请求的 `trace_id`，而是恢复成了默认值，通常表现为：

- 日志没有正确 trace ID。
- 日志显示 `system`。
- 无法把流式输出期间的日志关联到原请求。

因为 ContextVar 本身有请求隔离，正常不会出现 A 请求拿到 B 请求 `trace_id` 的“串号”问题。这里的问题是**追踪上下文提前丢失**。

**第 7 点：覆盖目标应该是测试替身，不是真实方法**

```python
app.dependency_overrides[get_llm_client] = lambda: FakeLLMClient()
```

用途是让测试不访问真实大模型、数据库或外部服务。

覆盖规则：

- 键是原始依赖函数 `get_llm_client`。
- 值可以是另一个同步函数、异步函数或返回替身对象的可调用对象。
- 测试结束后要清理。

```python
try:
    app.dependency_overrides[get_llm_client] = lambda: FakeLLMClient()
    # 发起测试请求
finally:
    app.dependency_overrides.clear()
```

“真实方法”通常达不到隔离测试的目的；应该提供 Fake、Stub 或 Mock。

**第 5 点再补充一个数据库概念**

连接池和会话不是同一个东西：

```text
连接池：保存可复用的物理数据库连接，应用级共享
会话：一次请求中的逻辑工作单元，请求级独立
事务：绑定在会话及其连接上，通常按请求或业务操作划分
```

请求结束时关闭会话，并不等于关闭数据库连接；通常只是让连接归还连接池。

修改后的理解可以概括为：

```text
连接池共享，避免重复建立连接
会话独立，避免事务和状态互相污染
请求结束归还连接，但连接池继续复用
```

这组题你基本已经过关了。

