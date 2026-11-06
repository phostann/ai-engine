# lifespan 与资源生命周期

> 本文逐字转录自原始课程对话，只添加角色标题和来源信息，未改写、删减或二次总结。
>
- 返回：[课程原文索引](README.md)
- 原始消息序号：`771`、`776`、`833`、`840`、`858`、`865`、`870`、`885`、`892`、`895`

## 用户（原始消息 771）

继续下一个知识点

## 助手（原始消息 776）

下一课建议学 **FastAPI 的 `lifespan` 与异步上下文管理**。它正好解释了 `main.py` 中连接池为什么在启动时创建、服务关闭时释放，也是理解这个项目资源生命周期的关键。我先结合当前代码把这个知识点讲透。

## 助手（原始消息 833）

**下一课：`lifespan` 与资源生命周期**

这一课要解决的问题是：数据库连接池、HTTP 客户端、Redis 客户端、模型客户端这些“创建成本高、必须关闭”的对象，应该在哪里创建和释放。

**1. `lifespan` 是什么**

`lifespan` 表示整个 FastAPI 应用的生命周期，不是单个请求的生命周期：

```text
服务启动
  ↓
执行 lifespan 中 yield 之前的代码      启动阶段
  ↓
等待并处理大量请求
  ↓
执行 lifespan 中 yield 之后的代码      关闭阶段
  ↓
服务退出
```

当前代码在 `main.py` 中：

```python
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # 启动逻辑
    yield
    # 关闭逻辑
```

`yield` 是启动和关闭之间的分界线：

- `yield` 前：连接池初始化、客户端创建。
- `yield` 后：连接池关闭、客户端释放。
- 请求处理发生在 `yield` 暂停的期间。

**2. 为什么需要 `@asynccontextmanager`**

普通函数执行到 `yield` 会暂停，FastAPI 利用这个暂停点把应用切换到“正在提供服务”的状态。

`AsyncIterator[None]` 表示这是一个异步生成器，并且 `yield` 不返回具体值。真正的共享对象会放进 `app.state`：

```python
app.state.llm_client = llm_client
```

可以把它理解成：

```python
try:
    resource = await create_resource()
    app.state.resource = resource
    yield
finally:
    await close_resource(resource)
```

**3. `async with` 在这里做了什么**

关键代码是：

```python
async with ProductionHttpClient(base_url=settings.llm_base_url) as http_client:
    ...
    yield
```

它等价于：

```python
http_client = ProductionHttpClient(...)
await http_client.__aenter__()
try:
    ...
    yield
finally:
    await http_client.__aexit__(...)
```

当前 `ProductionHttpClient` 中：

- `__aenter__()` 创建 `httpx.AsyncClient` 和连接池。
- `__aexit__()` 调用 `aclose()` 关闭连接池。

完整流程是：

```text
lifespan 启动
  ↓
调用 ProductionHttpClient.__aenter__
  ↓
创建 httpx.AsyncClient 和连接池
  ↓
创建 NativeLLMClient
  ↓
挂载到 app.state.llm_client
  ↓
yield，开始接收 HTTP 请求
  ↓
客户端中途断开或服务停止
  ↓
执行 ProductionHttpClient.__aexit__
  ↓
关闭连接池
```

这比在每个请求里创建 `AsyncClient` 好得多。每个请求创建连接池会增加 TCP/TLS 握手成本，也无法充分复用连接。

**4. `app.state` 与依赖注入的关系**

`app.state` 是一个应用级共享状态容器，不是 Pydantic 模型，也没有严格的类型检查。

在 `main.py` 中：

```python
app.state.llm_client = llm_client
```

在 `deps.py` 中：

```python
async def get_llm_client(request: Request) -> NativeLLMClient:
    client = getattr(request.app.state, "llm_client", None)
    if client is None:
        raise HTTPException(...)
    return client
```

路由函数并不直接访问全局变量，而是通过依赖注入取得客户端：

```python
llm_client: LLMClientDep
```

因此三类对象的生命周期要区分清楚：

- `get_settings()`：进程级配置缓存，由 `@lru_cache` 管理。
- `ProductionHttpClient`：应用级资源，由 `lifespan` 管理。
- `trace_id`：请求级状态，由带 `yield` 的 FastAPI 依赖管理。

`trace_id` 的依赖也使用了同样的思路：

```python
token = _trace_id_var.set(trace_id)
try:
    yield trace_id
finally:
    _trace_id_var.reset(token)
```

区别是它针对每一个请求执行一次，而 `lifespan` 针对整个应用执行一次。

**5. 一个常见误区：多 worker 下的“全局”**

如果以后这样启动：

```powershell
uvicorn ai_engine.main:app --workers 4
```

实际上会有 4 个独立的 Python 进程，每个进程都会执行一次 `lifespan`，每个进程都有自己的 `AsyncClient` 和连接池。

所以 `app.state` 中的对象是“当前 worker 进程内共享”，不是“整个服务所有进程共享”。如果配置 `max_connections=100`，4 个 worker 理论上可能产生约 400 条连接。

**6. 异常与清理**

当前 `ProductionHttpClient` 被 `async with` 包裹，因此即使应用发生异常，连接池也会通过 `__aexit__` 关闭。

但如果希望关闭阶段的日志也一定执行，代码可以写成：

```python
async with ProductionHttpClient(...) as http_client:
    ...
    try:
        yield
    finally:
        logger.info("正在释放网关全局连接池资源...")
```

**7. 当前项目的一处关联问题**

`main.py` 只挂载了：

```python
app.state.llm_client = llm_client
```

但 `deps.py` 的 `get_http_client()` 查找的是：

```python
request.app.state.http_client
```

目前聊天路由只使用 `LLMClientDep`，所以还没有触发这个问题；以后如果某个路由使用 `HttpClientDep`，就会返回“全局 HTTP 客户端连接池未初始化”的 500 错误。正确的挂载方式应该同时加入：

```python
app.state.http_client = http_client
app.state.llm_client = llm_client
```

这一课的核心可以概括为：

```text
lifespan 管应用级资源
async with 管资源的获取与释放
app.state 管应用内共享对象
Depends 管按请求获取这些对象
多 worker 下每个进程各有一份资源
```

## 用户（原始消息 840）

你还是没讲清楚 为啥需要  @asynccontextmanager

## 助手（原始消息 858）

关键点是：**FastAPI 需要的不是“一个能 `yield` 的异步函数”，而是一个“异步上下文管理器工厂”**。`@asynccontextmanager` 的职责就是把前者转换成后者。

**1. 先分清三种对象**

```python
async def lifespan(app):
    ...
    yield
```

这里的 `lifespan` 是：

```text
异步生成器函数
```

调用它会得到：

```text
异步生成器对象 async_generator
```

而 FastAPI 传给 Starlette 的 `lifespan` 参数要求的是：

```text
调用后返回异步上下文管理器的函数
```

类似：

```text
async_context_manager.__aenter__
async_context_manager.__aexit__
```

这是两种不同的协议。异步生成器不等于异步上下文管理器。

**2. `yield` 只负责暂停，不负责管理生命周期**

```python
async def lifespan(app):
    print("启动")
    yield
    print("关闭")
```

`yield` 确实能让函数暂停，但调用这个函数并不会执行任何代码，只会得到一个异步生成器。

而 FastAPI 的内部最终需要执行类似：

```python
async with lifespan_context(app):
    # 应用运行
    ...
```

注意这里使用的是 `async with`。`async with` 要求对象必须提供：

```python
__aenter__()
__aexit__()
```

普通异步生成器没有这两个方法，所以不能直接作为 `async with` 的对象使用。

**3. 装饰器做了什么**

```python
@asynccontextmanager
async def lifespan(app):
    ...
    yield
```

这个装饰器把“异步生成器函数”包装成了“返回异步上下文管理器的函数”。

概念上相当于：

```python
def lifespan(app):
    agen = raw_lifespan(app)

    return AsyncGeneratorContextManager(agen)
```

这个上下文管理器内部大致做了：

```python
class AsyncGeneratorContextManager:
    async def __aenter__(self):
        # 执行到 yield 为止
        return await anext(self.agen)

    async def __aexit__(self, *exc_info):
        # 从 yield 后继续执行
        await anext(self.agen)
```

所以：

```text
@asynccontextmanager
        ↓
把 async generator function
        ↓
包装成 async context manager factory
        ↓
FastAPI 才能执行 async with
```

**4. 把它套入当前项目**

代码：

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    async with ProductionHttpClient(...) as http_client:
        app.state.llm_client = ...
        yield
```

实际执行顺序是：

```text
FastAPI 启动
  ↓
调用 lifespan(app)，得到异步上下文管理器
  ↓
执行 async with lifespan_context(app)
  ↓
__aenter__ 执行到 yield
  ↓
连接池已创建，应用开始接收请求
  ↓
服务运行期间一直停在 yield
  ↓
服务关闭
  ↓
__aexit__ 从 yield 后继续
  ↓
ProductionHttpClient.__aexit__ 执行
  ↓
httpx.AsyncClient.aclose()
```

不能用普通 `await` 的原因也在这里：

```python
await lifespan(app)
```

这样做只是在等待一个异步生成器函数执行完，无法表达“启动完成后暂停，等应用关闭再继续”这一段生命周期。

**5. 去掉装饰器为什么可能还能运行**

某些版本的 Starlette 检测到 `lifespan` 是原生异步生成器函数后，会出于兼容性自动帮你包一层：

```python
self.lifespan_context = asynccontextmanager(lifespan)
```

但它同时会发出弃用警告。也就是说：

- 你现在删掉装饰器，某些版本可能“碰巧能跑”。
- 这不是 FastAPI 推荐的接口形式。
- 换版本后可能报错。
- 类型检查和你自己的代码也无法再把它当作标准异步上下文管理器使用。

Starlette 当前源码中最终执行的位置就是：

```python
async with self.lifespan_context(app) as maybe_state:
```

这个 `async with` 就是必须使用 `@asynccontextmanager` 的根本原因。

**一句话总结**

`yield` 负责划分启动和关闭阶段，`@asynccontextmanager` 负责把“带 `yield` 的异步生成器”转换成 FastAPI 能使用 `async with` 管理的标准异步上下文管理器。两者解决的是不同问题，缺一不可。

## 用户（原始消息 865）

我看完了，这个知识点就这么些内容么

## 助手（原始消息 870）

上一课讲的是“读懂当前代码所必需的最小闭环”，不是这个知识点的全部。还缺几块真正影响生产代码的内容：异常语义、取消与超时、资源关闭顺序、测试方式，以及 lifespan 与请求级依赖的边界。

## 助手（原始消息 885）

不是。上一轮只解释了你卡住的“为什么需要装饰器”，属于最小必要知识。完整的 `lifespan` 知识点还包括异常、取消、资源关闭顺序、测试和多进程语义。

**完整知识地图**

1. 异步上下文管理器协议。
2. `@asynccontextmanager` 的生成器语义。
3. 启动失败和关闭失败如何处理。
4. 多个资源的获取与释放顺序。
5. `lifespan`、请求依赖和流式生成器三者的生命周期区别。
6. 取消、超时和强制停机。
7. 测试时如何真正触发生命周期。
8. 多 worker、reload 下的资源副本问题。

下面补充最关键、上一轮没展开的部分。

**1. `__aenter__` 和 `__aexit__` 才是协议本体**

一个对象能用于 `async with`，不是因为它叫 context manager，而是因为它实现了：

```python
class Resource:
    async def __aenter__(self):
        print("获取资源")
        return self

    async def __aexit__(self, exc_type, exc, tb):
        print("释放资源")
        return False
```

它的执行方式是：

```python
resource = Resource()
value = await resource.__aenter__()

try:
    async with_body(value)
except BaseException as exc:
    suppressed = await resource.__aexit__(type(exc), exc, exc.__traceback__)
    if not suppressed:
        raise
else:
    await resource.__aexit__(None, None, None)
```

重点有三条：

- `__aenter__` 的返回值赋给 `as` 后面的变量。
- `__aexit__` 正常情况下也会执行。
- 如果 `__aexit__` 返回 `True`，异常会被吞掉；返回 `None` 或 `False`，异常继续向外传播。

当前项目的 `ProductionHttpClient` 正是手动实现了这两个方法：

```python
async def __aenter__(self):
    self._client = httpx.AsyncClient(...)
    return self

async def __aexit__(self, ...):
    await self._client.aclose()
```

因此 `async with ProductionHttpClient(...) as http_client` 本质上就是调用这两个方法。

**2. `@asynccontextmanager` 不能随意返回 `True`**

普通 `__aexit__` 可以直接返回 `True` 抑制异常。使用装饰器时，控制方式不同：

```python
@asynccontextmanager
async def manager():
    try:
        yield
    except ValueError:
        print("吞掉 ValueError")
```

如果 `async with` 的主体抛出 `ValueError`，它会被重新抛到 `yield` 所在位置。由于这里捕获后没有继续抛出，异常就被抑制了。

业务资源清理通常不应该吞异常：

```python
@asynccontextmanager
async def manager():
    try:
        yield
    finally:
        await close()
```

这里只保证清理，不改变原异常。

还要注意：**如果清理代码自己抛异常，可能覆盖原始异常**。例如原始请求已经报错，但 `close()` 又失败，最终看到的可能是关闭错误。所以关闭逻辑要尽量可靠，并记录上下文。

**3. 启动阶段失败会怎样**

```python
@asynccontextmanager
async def lifespan(app):
    client = await create_client()  # 如果这里失败
    yield
```

由于还没执行到 `yield`，`__aenter__` 会失败，Starlette 会发送：

```text
lifespan.startup.failed
```

应用不会被认为是启动成功的，也不会开始正常提供服务。

这有一个重要实践结论：

> `yield` 前面只应该放“服务可以开始接收请求”所必需的初始化。

不要在这里执行几分钟的数据迁移、全量缓存预热或没有超时的远程请求，否则 Uvicorn 会一直等待启动完成。

正常关闭时，Starlette 从 `yield` 后继续执行。如果关闭代码抛错，会进入关闭失败流程。因此关闭逻辑也要设置超时和异常处理。

**4. 多个资源的关闭顺序**

嵌套的 `async with` 会按照后进先出释放：

```python
async with database_pool() as db:
    async with redis_client() as redis:
        async with http_client() as http:
            yield
```

关闭顺序是：

```text
先关闭 http
再关闭 redis
最后关闭 database
```

这是正确的，因为上层资源可能依赖下层资源。比如业务客户端依赖 HTTP 连接池，就应该先停止业务客户端，再关闭连接池。

当前代码是：

```python
async with ProductionHttpClient(...) as http_client:
    llm_client = NativeLLMClient(...)
    yield
```

`NativeLLMClient` 自己没有需要异步关闭的资源，所以只需要关闭底层 `http_client`。以后如果 `NativeLLMClient` 也增加了后台任务、队列或会话，就应该把它的关闭逻辑放在 HTTP 连接池关闭之前。

**5. 资源所有权必须唯一**

推荐规则：

> 谁创建资源，谁负责关闭。

当前由 `lifespan` 创建 `ProductionHttpClient`，那么也必须由 `lifespan` 关闭。路由、依赖或普通业务函数只借用它，不负责关闭。

错误做法：

```python
async def get_http_client(request: Request):
    client = request.app.state.http_client
    await client.client.aclose()  # 错误：把全局连接池关了
    return client
```

这会导致第一个请求结束后，其他请求全部无法使用连接池。

**6. `lifespan`、请求依赖、异步生成器的区别**

项目中同时存在三种生命周期：

```python
# 整个应用一次
@asynccontextmanager
async def lifespan(app):
    ...
    yield
```

```python
# 每个请求一次
async def get_request_trace_id(...):
    token = _trace_id_var.set(trace_id)
    try:
        yield trace_id
    finally:
        _trace_id_var.reset(token)
```

```python
# 每个流式响应一次
async def chat_stream(...):
    async with self.http_client.client.stream(...) as response:
        yield content
```

对应关系是：

- 连接池、Redis 连接池、数据库引擎：应用级，放 `lifespan`。
- 数据库事务、当前用户、`trace_id`：请求级，放 FastAPI 依赖。
- SSE 响应、上游流式响应、文件句柄：流级，放异步生成器中的 `async with`。

如果把数据库连接池放到请求依赖里，就会每个请求创建一套连接池。如果把 `trace_id` 放进全局变量，就会出现多个并发请求互相串数据。

**7. 取消与强制停机**

正常关闭时，清理代码有机会执行。但以下情况没有绝对保证：

- 进程收到 `SIGKILL`。
- 操作系统直接终止进程。
- 关闭过程本身卡死。
- 清理任务再次被取消。

`finally` 能处理大多数异常，但不是“进程无论怎么死都能执行”的保证。

因此生产环境的关闭逻辑应该：

- 有明确超时，不能无限等待。
- 尽量幂等，重复关闭也不会出错。
- 不在清理阶段发起不可控的长网络请求。
- 对后台任务执行取消并等待其退出。
- 记录资源关闭失败，但不要让日志本身再次失败。

**8. 测试时为什么要手动进入 lifespan**

`httpx.ASGITransport(app=app)` 只会调用 ASGI 应用处理请求，不一定会自动执行 lifespan。

所以测试如果直接这样写：

```python
transport = ASGITransport(app=app)
```

`app.state.llm_client` 可能还没有被创建。

项目中的测试显式执行：

```python
async with app.router.lifespan_context(app):
    async with httpx.AsyncClient(...) as client:
        ...
```

这相当于手动执行启动和关闭阶段，是异步测试里常见做法。

如果使用 `TestClient` 的上下文形式：

```python
with TestClient(app) as client:
    ...
```

通常也会自动管理 lifespan。关键不是用哪个工具，而是测试必须明确“我要不要执行应用生命周期”。

**9. 多 worker 与 reload**

每个 Uvicorn worker 都是独立进程：

```text
Worker 1 -> 自己的 lifespan -> 自己的连接池
Worker 2 -> 自己的 lifespan -> 自己的连接池
Worker 3 -> 自己的 lifespan -> 自己的连接池
```

所以 `app.state` 是**进程内共享**，不是跨进程共享。连接池上限、后台任务、内存缓存都要按 worker 数量重新估算。

`--reload` 也不是热替换一个全局对象。修改文件后，worker 会重启，旧 lifespan 关闭，新 lifespan 重新创建所有资源。因此开发时看到连接池重建是正常现象。

**10. 当前项目还可以改进的一点**

当前代码只挂载了：

```python
app.state.llm_client = llm_client
```

但 `get_http_client()` 查找的是：

```python
request.app.state.http_client
```

如果以后有路由使用 `HttpClientDep`，就会得到 500。更完整的生命周期代码应该同时挂载：

```python
app.state.http_client = http_client
app.state.llm_client = llm_client
```

关闭时可以清理引用，避免测试或同进程重启时访问到过期对象：

```python
try:
    yield
finally:
    app.state.llm_client = None
    app.state.http_client = None
```

**这个知识点的掌握标准**

你真正掌握它，不是会背 `@asynccontextmanager`，而是能回答：

1. 为什么连接池不能在路由函数里创建？
2. `yield` 前后分别发生什么？
3. 启动失败发生在 `yield` 前还是后？
4. 多个上下文管理器的关闭顺序是什么？
5. `app.state` 在多 worker 下是不是唯一的？
6. `ASGITransport` 为什么不自动执行 lifespan？
7. 请求级依赖和应用级资源分别应该放在哪里？

这些内容合起来，才算完整掌握 `lifespan`。

## 用户（原始消息 892）

1. 由路由函数创建的话，就会每个请求都要创建一遍连接池，严重影响性能，并且可能导致异常 2. yield 前执行资源创建，yield 后执行资源释放 3. 启动失败发生在 yield 前 4. 多个上下文管理器关闭的顺序是由上向下，因为生成可能依赖下层 5. app.state 在每个 worker 中都是独立的 6. ASGITransport 只会调用应用请求，而不会主动调用 lifespan 7. 请求级依赖放在每次请求里面，应用级依赖放在 state 上进行共享

## 助手（原始消息 895）

整体理解已经正确，尤其第 2、3、5、6 点没问题。有三处需要修正得更精确。

**第 1 点补充**

每个请求创建连接池不只是“影响性能”，具体会导致：

- 每次请求重新进行 TCP/TLS 握手。
- 连接无法复用，延迟显著增加。
- 文件描述符、端口和内存快速消耗。
- 并发升高时可能连接耗尽，甚至触发系统级错误。
- 异常退出时更容易遗留未关闭的套接字。

所以它是资源架构问题，不只是性能优化问题。

**第 4 点顺序反了**

嵌套上下文管理器遵循 **后创建、先释放**，也就是 LIFO：

```python
async with A:          # 1. 创建 A
    async with B:      # 2. 创建 B
        yield
                       # 3. 先释放 B
                       # 4. 再释放 A
```

不是“由上向下”，而是：

```text
A 进入
  B 进入
  B 退出
A 退出
```

如果 `B` 依赖 `A`，就必须先关闭 `B`：

```python
async with database_pool() as pool:
    async with pool.transaction() as transaction:
        yield

# 先结束 transaction
# 再关闭 database_pool
```

**第 7 点需要区分“存放”与“管理”**

更准确的表述是：

- 应用级资源的**创建和关闭**放在 `lifespan`。
- 创建好的对象在 `lifespan` 中写入 `app.state`。
- 每次请求通过 `Depends` 从 `app.state` 读取引用。
- 请求结束后只归还引用，不关闭应用级资源。
- 请求级资源由带 `yield` 的 FastAPI 依赖创建和清理。

例如：

```python
# lifespan：只创建和关闭一次
async with ProductionHttpClient(...) as http_client:
    app.state.http_client = http_client
    yield

# 请求依赖：每个请求只读取已有对象的引用
async def get_http_client(request: Request):
    return request.app.state.http_client
```

因此重点不是“应用级依赖放在 state 上”，而是：

```text
lifespan 管理生命周期
app.state 保存对象引用
Depends 负责在请求中取得引用
```

你对这个知识点的掌握已经够用了。真正容易出错的点通常不是 `yield` 前后怎么写，而是资源所有权、关闭顺序和多 worker 下误以为 `app.state` 是全局唯一的。

