# 上下文管理器、ExitStack 与 AsyncExitStack

> 本文逐字转录自原始课程对话，只添加角色标题和来源信息，未改写、删减或二次总结。
>
- 返回：[课程原文索引](README.md)
- 原始消息序号：`2206`、`2227`、`2234`、`2239`

## 用户（原始消息 2206）

继续下一课

## 助手（原始消息 2227）

**本课知识点：上下文管理器、`ExitStack` 与 `AsyncExitStack`**

前面已经用过：

- `async with ProductionHttpClient(...)`
- `@asynccontextmanager`
- FastAPI `lifespan`
- `aclosing()`
- `AsyncExitStack`

这一课把它们背后的协议完整串起来。

核心问题是：

> 一个资源被成功打开后，如何保证无论正常结束、抛出异常、提前 return，还是任务取消，都能按照正确顺序释放？

---

## 1. `with` 本质上调用了什么

同步代码：

```python
with resource as value:
    do_something(value)
```

大致等价于：

```python
manager = resource
value = manager.__enter__()

try:
    do_something(value)
except BaseException as exc:
    suppressed = manager.__exit__(
        type(exc),
        exc,
        exc.__traceback__,
    )
    if not suppressed:
        raise
else:
    manager.__exit__(None, None, None)
```

关键方法：

```python
__enter__()
__exit__(exc_type, exc_value, traceback)
```

`as value` 接收的是 `__enter__()` 的返回值，不是资源对象本身。

例如：

```python
class Resource:
    def __enter__(self) -> str:
        print("打开资源")
        return "resource-value"

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        print("关闭资源")


with Resource() as value:
    print(value)
```

输出：

```text
打开资源
resource-value
关闭资源
```

---

## 2. `__exit__` 的参数

```python
def __exit__(
    self,
    exc_type: type[BaseException] | None,
    exc_value: BaseException | None,
    traceback: TracebackType | None,
) -> bool | None:
    ...
```

正常退出时：

```python
exc_type is None
exc_value is None
traceback is None
```

代码块抛出异常时：

```python
exc_type = ValueError
exc_value = ValueError("错误")
traceback = 异常堆栈
```

`__exit__` 可以通过返回值控制是否抑制异常：

```python
class SuppressValueError:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        return exc_type is ValueError
```

使用：

```python
with SuppressValueError():
    raise ValueError("被吞掉")

print("继续执行")
```

`__exit__()` 返回 `True`，异常被抑制。

返回：

- `True`：抑制异常
- `False` 或 `None`：异常继续传播

---

## 3. 异常是在 `__exit__` 中处理的

看项目：

[C:\work\python\ai-agent-leran\ai-engine\src\ai_engine\core\context.py:20](C:\work\python\ai-agent-leran\ai-engine\src\ai_engine\core\context.py:20)

```python
@asynccontextmanager
async def llm_session_scope(model_name: str) -> AsyncIterator[MockLLMClient]:
    ...
    client = MockLLMClient(model_name=model_name, is_connected=True)

    try:
        yield client
    except Exception as exc:
        print(f"会话执行期间捕获到异常: {exc}")
        raise
    finally:
        client.is_connected = False
        await asyncio.sleep(0.05)
```

这里的 `yield` 会被 `asynccontextmanager` 转换成：

```text
yield 前 → __aenter__
yield 后 → __aexit__
```

执行 `async with llm_session_scope(...) as client:` 时：

```text
进入 async with
    ↓
执行 yield 前的初始化
    ↓
把 client 交给 as 变量
    ↓
执行使用资源的代码
    ↓
退出 async with
    ↓
回到 yield 之后
    ↓
执行 finally 清理
```

如果 `async with` 代码块中抛出异常：

```python
async with llm_session_scope("gpt") as client:
    raise ValueError("业务错误")
```

异常会被抛回到生成器的 `yield client` 位置，因此这里的：

```python
except Exception as exc:
```

可以捕获它。

随后 `raise` 继续抛出，所以异常不会被吞掉。最后 `finally` 继续执行清理。

---

## 4. `@asynccontextmanager` 的基本规则

```python
from contextlib import asynccontextmanager


@asynccontextmanager
async def resource_scope():
    resource = await open_resource()
    try:
        yield resource
    finally:
        await close_resource(resource)
```

规则是：

- 函数必须是异步生成器
- 通常只能 `yield` 一次
- `yield` 前对应 `__aenter__`
- `yield` 后对应 `__aexit__`
- 所有清理逻辑应放在 `finally`
- 如果 `yield` 前初始化失败，`async with` 块不会进入
- 如果 `__aenter__` 失败，`__aexit__` 不会自动执行

最后一点很重要。假设：

```python
@asynccontextmanager
async def scope():
    await connect()
    raise RuntimeError("初始化失败")
    yield resource
```

此时：

```python
async with scope():
    ...
```

`connect()` 已经执行了，但 `yield` 没有到达，`async with` 块没有进入，`__aexit__` 也不会执行。

因此初始化失败时，已经获得的资源必须在内部回滚：

```python
@asynccontextmanager
async def scope():
    resource = await connect()
    try:
        await initialize(resource)
        yield resource
    finally:
        await resource.close()
```

只要 `connect()` 成功，从那一刻起就应该让 `try/finally` 覆盖后续所有初始化。

---

## 5. `async with` 与同步 `with` 的区别

同步上下文管理器：

```python
with manager:
    ...
```

需要：

```python
__enter__
__exit__
```

异步上下文管理器：

```python
async with manager:
    ...
```

需要：

```python
__aenter__
__aexit__
```

`async with` 不能直接用于普通同步上下文管理器，除非对象同时实现了异步协议。

项目中的 HTTP 客户端：

[C:\work\python\ai-agent-leran\ai-engine\src\ai_engine\core\http_client.py:36](C:\work\python\ai-agent-leran\ai-engine\src\ai_engine\core\http_client.py:36)

```python
async def __aenter__(self) -> "ProductionHttpClient":
    self._client = httpx.AsyncClient(...)
    return self


async def __aexit__(self, ...) -> None:
    if self._client is not None:
        await self._client.aclose()
        self._client = None
```

因此可以：

```python
async with ProductionHttpClient(...) as client:
    await client.request_with_jitter_retry(...)
```

退出时 `__aexit__` 自动关闭连接池。

---

## 6. 多个 `async with` 的释放顺序

```python
async with resource_a:
    async with resource_b:
        ...
```

释放顺序是：

```text
关闭 resource_b
关闭 resource_a
```

也就是后进先出，LIFO。

原因是：

- `resource_a` 先进入
- `resource_b` 后进入
- 内层作用域先结束
- 外层作用域后结束

如果 `resource_b` 依赖 `resource_a`，这个顺序是合理的：

```text
A 建立连接
B 使用 A 创建事务
B 使用完，先关闭
A 后关闭
```

如果顺序反过来，就可能先关闭 A，导致 B 的清理失败。

---

## 7. 动态数量资源的问题

静态数量可以直接嵌套：

```python
async with resource_a:
    async with resource_b:
        async with resource_c:
            ...
```

但有时资源数量是运行时决定的：

```python
server_names = ["github-mcp", "postgres-mcp", "browser-mcp"]
```

你不知道未来会不会有 3 个、10 个甚至 100 个资源。

如果动态编写 `async with`，就需要递归或复杂嵌套。

`AsyncExitStack` 解决这个问题。

---

## 8. `ExitStack` 的基本思想

同步版：

```python
from contextlib import ExitStack

with ExitStack() as stack:
    file_1 = stack.enter_context(open("a.txt"))
    file_2 = stack.enter_context(open("b.txt"))
    file_3 = stack.enter_context(open("c.txt"))
```

退出 `with ExitStack()` 时：

```text
关闭 file_3
关闭 file_2
关闭 file_1
```

`ExitStack` 维护一个退出回调栈。

每次 `enter_context()` 进入一个上下文管理器，就把对应的 `__exit__` 注册到栈中。

无论中途哪个资源创建失败，已经注册的资源都会被清理。

---

## 9. `AsyncExitStack`

项目使用：

[C:\work\python\ai-agent-leran\ai-engine\src\ai_engine\core\lifecycle_ext.py:74](C:\work\python\ai-agent-leran\ai-engine\src\ai_engine\core\lifecycle_ext.py:74)

```python
class DynamicMCPClusterManager:
    def __init__(self, server_names: list[str], fail_server: str | None = None) -> None:
        self.server_names = server_names
        self.fail_server = fail_server
        self._stack: AsyncExitStack | None = None
        self.active_connections: dict[str, MockMCPServerConnection] = {}
```

进入时动态注册资源：

```python
async def __aenter__(self) -> dict[str, MockMCPServerConnection]:
    self._stack = AsyncExitStack()
    await self._stack.__aenter__()

    try:
        for name in self.server_names:
            conn = await self._stack.enter_async_context(
                connect_single_mcp(name, fail_on_init=(name == self.fail_server))
            )
            self.active_connections[name] = conn

        return self.active_connections
    except Exception:
        await self._stack.__aexit__(*(None, None, None))
        raise
```

`enter_async_context()` 会：

1. 调用异步上下文管理器的 `__aenter__`
2. 获得返回值
3. 把对应的 `__aexit__` 注册到 `AsyncExitStack`
4. 后续退出时自动按 LIFO 调用

假设连接顺序是：

```text
github-mcp
postgres-mcp
broken-mcp
```

如果 `broken-mcp` 初始化失败，栈中已经注册：

```text
github-mcp 的 __aexit__
postgres-mcp 的 __aexit__
```

回滚时会先关闭 `postgres-mcp`，再关闭 `github-mcp`。

这比手写：

```python
try:
    conn_a = await open_a()
    conn_b = await open_b()
    conn_c = await open_c()
except Exception:
    # 手动判断哪一个已经打开
    await close_b()
    await close_a()
```

安全得多。

---

## 10. 当前 `DynamicMCPClusterManager` 的一个重要边界问题

当前代码：

```python
except Exception:
    await self._stack.__aexit__(*(None, None, None))
    raise
```

如果 `connect_single_mcp()` 内部因为普通异常失败，前面已经打开的连接会被关闭。

但如果是任务取消：

```python
except Exception:
```

捕获不到：

```python
asyncio.CancelledError
```

因为 `CancelledError` 继承自 `BaseException`，不是 `Exception`。

而 `__aenter__` 失败时，Python 不会自动调用这个管理器的 `__aexit__`：

```python
async with DynamicMCPClusterManager(...) as connections:
    ...
```

如果 `__aenter__` 内部打开第一个连接后，在打开第二个连接时被取消，那么：

```text
第一个连接已经打开
第二个连接初始化时收到 CancelledError
except Exception 不捕获
__aenter__ 退出
async with 代码块没有进入
__aexit__ 不会自动执行
```

前面已经打开的连接可能泄漏。

对于资源回滚，可以专门捕获 `BaseException` 然后重新抛出：

```python
try:
    for name in self.server_names:
        ...
except BaseException:
    await self._stack.aclose()
    raise
```

这里的 `BaseException` 不是吞掉取消信号，而是：

1. 捕获所有异常和取消信号
2. 确保回滚已经打开的资源
3. 立即 `raise` 恢复原异常

这是资源清理场景中可以接受的 `BaseException` 用法。

如果不在资源回滚边界，普通业务代码仍然应使用 `except Exception`。

---

## 11. `AsyncExitStack` 的常用能力

除了 `enter_async_context()`，还有：

```python
stack.push_async_exit(async_exit)
stack.push_async_callback(async_cleanup, arg1, arg2)
stack.callback(sync_cleanup, arg1)
stack.enter_context(sync_context_manager)
```

几个常用方法：

| 方法 | 用途 |
|---|---|
| `enter_async_context(cm)` | 注册异步上下文管理器 |
| `enter_context(cm)` | 注册同步上下文管理器 |
| `push_async_exit(fn)` | 注册异步退出函数 |
| `push_async_callback(fn, *args)` | 注册异步清理回调 |
| `callback(fn, *args)` | 注册同步清理回调 |
| `aclose()` | 立即展开并清理整个栈 |
| `pop_all()` | 把当前栈的所有退出回调转移给新的栈 |

后注册的回调先执行：

```python
stack.callback(close_a)
stack.callback(close_b)
stack.callback(close_c)
```

退出时：

```text
close_c
close_b
close_a
```

---

## 12. `AsyncExitStack` 可以混合同步和异步资源

```python
async with AsyncExitStack() as stack:
    file = stack.enter_context(open("data.txt"))
    http_client = await stack.enter_async_context(open_http_client())
    db = await stack.enter_async_context(open_database())
```

退出顺序：

```text
关闭 database
关闭 http_client
关闭 file
```

对于包含同步资源的异步服务，`AsyncExitStack` 很实用。

---

## 13. `asynccontextmanager` 和 `AsyncExitStack` 的关系

两者解决不同层次的问题。

`asynccontextmanager`：

```python
@asynccontextmanager
async def resource_scope():
    resource = await open()
    try:
        yield resource
    finally:
        await close(resource)
```

适合：

> 一个固定资源生命周期

`AsyncExitStack`：

```python
stack = AsyncExitStack()
await stack.__aenter__()
for item in dynamic_items:
    await stack.enter_async_context(open_item(item))
```

适合：

> 运行时动态决定的一组资源

两者可以组合：

```python
@asynccontextmanager
async def cluster_scope(names: list[str]):
    async with AsyncExitStack() as stack:
        connections = []
        for name in names:
            conn = await stack.enter_async_context(connect(name))
            connections.append(conn)

        try:
            yield connections
        finally:
            print("所有连接即将按 LIFO 关闭")
```

---

## 14. `aclosing()` 的定位

`aclosing()` 是专门关闭异步对象的工具：

```python
from contextlib import aclosing

async with aclosing(generator) as stream:
    async for item in stream:
        ...
```

它会在退出时调用：

```python
await generator.aclose()
```

适用对象：

- 异步生成器
- 有 `aclose()` 方法的异步对象

`AsyncExitStack` 管理的对象更通用：

- 异步上下文管理器
- 同步上下文管理器
- 任意退出回调

简单说：

```text
aclosing：关闭一个异步生成器
AsyncExitStack：动态管理多个资源
```

---

## 15. 异常抑制要谨慎

上下文管理器可以吞掉异常：

```python
class SuppressAll:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        return True
```

使用：

```python
with SuppressAll():
    raise RuntimeError("错误消失")
```

这通常是危险行为。

如果包装器吞掉：

- `CancelledError`，任务可能无法退出
- 数据库异常，事务可能被错误提交
- 上游错误，调用方可能误以为成功
- 清理异常，原始异常可能被覆盖

推荐的上下文管理器模式是：

```python
@asynccontextmanager
async def scope():
    try:
        yield resource
    finally:
        await cleanup()
```

只清理，不擅自吞异常。

如果确实要抑制异常，应精确指定类型：

```python
except FileNotFoundError:
    ...
```

不要写：

```python
except BaseException:
    ...
```

更不要静默 `pass`。

---

## 16. 一个完整的资源生命周期

```python
@asynccontextmanager
async def app_scope():
    stack = AsyncExitStack()

    try:
        await stack.__aenter__()

        http_client = await stack.enter_async_context(open_http_client())
        db = await stack.enter_async_context(open_database())
        cache = await stack.enter_async_context(open_cache())

        try:
            yield http_client, db, cache
        finally:
            print("业务作用域结束")
    finally:
        await stack.aclose()
```

生命周期：

```text
打开 HTTP
打开数据库
打开缓存
    ↓
业务代码
    ↓
关闭缓存
关闭数据库
关闭 HTTP
```

如果中间某一步失败：

```text
打开 HTTP
打开数据库
打开缓存失败
    ↓
关闭数据库
关闭 HTTP
    ↓
重新抛出原始错误
```

这就是结构化资源管理。

---

**本课核心结论**

- `with` 调用 `__enter__/__exit__`
- `async with` 调用 `__aenter__/__aexit__`
- `__enter__` 的返回值绑定给 `as` 变量
- `__exit__` 返回 `True` 可以抑制异常，要谨慎使用
- `__aenter__` 失败时，`__aexit__` 不会自动执行
- 多资源释放通常遵循 LIFO
- `AsyncExitStack` 用来动态管理数量不确定的异步资源
- `asynccontextmanager` 适合固定资源生命周期
- `aclosing` 适合关闭异步生成器
- 资源初始化失败和任务取消都必须主动回滚

---

**验收问题**

1. `with manager as value:` 中，`value` 来自哪里？
2. `__exit__` 接收到哪三个参数？返回 `True` 意味着什么？
3. 如果 `__aenter__` 内部失败，`async with` 会调用 `__aexit__` 吗？
4. 两个嵌套 `async with` 的退出顺序是什么？为什么？
5. `AsyncExitStack.enter_async_context()` 做了什么？
6. `asynccontextmanager` 中的 `yield` 前后分别对应哪个协议方法？
7. `AsyncExitStack` 和 `aclosing` 的适用场景有什么区别？
8. 当前 `DynamicMCPClusterManager` 遇到 `CancelledError` 时可能有什么资源泄漏风险？
9. 为什么资源回滚场景可以捕获 `BaseException`，但普通业务代码不应该这样做？
10. 如何让一个已经成功打开的资源在 `asynccontextmanager` 初始化失败时仍被关闭？

按编号回答即可，我会逐题批改。

## 用户（原始消息 2234）

1. value来自于 aenter 的返回 2. exec_type exec_value, traceback 返回 True 代表抑制异常 3 . 如果 aenter 内部失败，则不会调用 aexit ，如果初始化失败，则直接不会进入 async with 4. 先退出内层，再退出外层 ，这类似于函数内部调用函数，就这么简单 5. 将资源推入队列进行管理 6. yield 前对应 aenter 后 对应 aexit 7. asyncexitstack 适应不确定资源数量， aclosing 适合直接关闭某一个资源 8. 不能正常释放资源 9. 因为 CancelledError 继承自 BaseException ，一般就是取消后会触发这个异常，就需要捕获 10 . 使用 finally  释放资源

## 助手（原始消息 2239）

**批改：8.5/10**

第 2、3、4、6、8、10 题基本正确；第 1、5、7 题需要修正表述；第 9 题要多解释一步。

**1. 需要区分同步和异步**

同步：

```python
with manager as value:
    ...
```

`value` 来自：

```python
manager.__enter__()
```

异步：

```python
async with manager as value:
    ...
```

`value` 来自：

```python
await manager.__aenter__()
```

如果题目是 `with`，应说 `__enter__`；如果是 `async with`，才说 `__aenter__`。

**2. 正确**

```python
__exit__(exc_type, exc_value, traceback)
```

对应异步：

```python
__aexit__(exc_type, exc_value, traceback)
```

返回 `True` 表示抑制异常：

```python
def __exit__(self, exc_type, exc_value, traceback) -> bool:
    return exc_type is ValueError
```

如果返回 `None` 或 `False`，异常继续向外传播。

**3. 正确**

```python
async with manager:
    ...
```

如果 `manager.__aenter__()` 自己抛出异常，`async with` 的代码块不会进入，Python 也不会自动调用 `manager.__aexit__()`。

因此资源初始化函数必须自己负责回滚：

```python
resource = await open_resource()
try:
    await initialize(resource)
    yield resource
finally:
    await close(resource)
```

注意：`open_resource()` 成功之后，`try` 必须立即覆盖后续所有可能失败的初始化步骤。

**4. 正确**

```text
async with A:
    async with B:
        ...
```

退出顺序是：

```text
先退出 B
再退出 A
```

这是后进先出，LIFO。

用嵌套函数理解也可以：

```python
A 进入
    B 进入
        work()
    B 退出
A 退出
```

**5. 基本正确，但“队列”这个词不准确**

`AsyncExitStack` 维护的是**退出回调栈**，不是普通队列。

```text
资源 A 进入 → 注册 A 的退出函数
资源 B 进入 → 注册 B 的退出函数
资源 C 进入 → 注册 C 的退出函数
```

退出时：

```text
执行 C 的退出函数
执行 B 的退出函数
执行 A 的退出函数
```

所以它是 LIFO，不是 FIFO 队列。

`enter_async_context()` 具体做两件事：

1. 调用上下文管理器的 `__aenter__()`
2. 把对应的 `__aexit__()` 注册到栈中

返回值则是 `__aenter__()` 返回的资源对象。

**6. 正确**

`@asynccontextmanager` 将一个异步生成器转换成异步上下文管理器：

```python
@asynccontextmanager
async def scope():
    resource = await open()
    try:
        yield resource
    finally:
        await close(resource)
```

对应关系是：

```text
yield 之前 → __aenter__ 的主体
yield 之后 → __aexit__ 的主体
```

外部代码块中的异常会被抛回到 `yield` 位置，因此可以用 `try/finally` 或 `except` 处理。

**7. 基本正确**

`AsyncExitStack` 适合：

- 运行时数量不确定的资源
- 多种同步、异步资源混合
- 需要统一注册退出回调
- 某个资源初始化失败后自动回滚前面已经打开的资源

`aclosing` 适合：

- 异步生成器
- 具有 `aclose()` 方法的异步对象
- 显式关闭单个异步生成器

它本质上是：

```python
async with aclosing(stream):
    ...
```

在退出时执行：

```python
await stream.aclose()
```

所以 `aclosing` 不是通用资源管理器，它专门处理带 `aclose()` 的异步对象。

**8. 正确**

当前：

[C:\work\python\ai-agent-leran\ai-engine\src\ai_engine\core\lifecycle_ext.py:98](C:\work\python\ai-agent-leran\ai-engine\src\ai_engine\core\lifecycle_ext.py:98)

```python
except Exception:
    await self._stack.__aexit__(*(None, None, None))
    raise
```

对于普通异常，前面已经打开的连接会被回滚关闭。

但 `CancelledError` 不是 `Exception` 子类，因此不会进入这个分支。

如果 `__aenter__()` 执行过程中发生取消：

```text
已经打开 connection-a
准备打开 connection-b
此时任务被取消
except Exception 不执行
__aenter__ 失败
async with 代码块没有进入
__aexit__ 不会自动执行
```

于是 `connection-a` 可能泄漏。

**9. 需要补充：不是普通业务代码要捕获 `CancelledError`**

准确说法是：

> 资源初始化或清理边界需要捕获 `BaseException`，目的是确保已经获得的资源被回滚，然后立即重新抛出，不是把异常吞掉。

例如：

```python
try:
    for name in self.server_names:
        ...
except BaseException:
    await self._stack.aclose()
    raise
```

这里的逻辑是：

```text
捕获所有退出信号
    ↓
关闭已注册资源
    ↓
重新抛出原始异常
```

普通业务代码仍然不应该写：

```python
except BaseException:
    pass
```

因为这会吞掉：

- `CancelledError`
- `KeyboardInterrupt`
- `SystemExit`
- `GeneratorExit`

而 `CancelledError` 是控制任务取消的信号，不是普通业务错误。普通代码应该让它继续传播。

**10. 正确，但要放在正确位置**

正确结构是：

```python
@asynccontextmanager
async def scope():
    resource = await open_resource()

    try:
        await initialize(resource)
        yield resource
    finally:
        await close(resource)
```

重点是：

- `open_resource()` 成功后立即进入 `try`
- `yield` 前失败，`finally` 仍会关闭资源
- `yield` 后正常退出，`finally` 会关闭资源
- 外部代码块抛异常，`finally` 仍会关闭资源
- 外部代码块取消，`finally` 也会执行清理

不要把 `finally` 写得太晚：

```python
resource = await open_resource()
await initialize(resource)  # 这里失败会跳过后面的 finally
try:
    yield resource
finally:
    await close(resource)
```

这样就是错误的。

---

**本课最重要的一句话**

```text
__aenter__ 成功后才注册资源；
__aenter__ 失败时，框架不会替你调用 __aexit__，
所以初始化阶段本身必须用 try/finally 保证回滚。
```

下一步建议进入：**HTTPX、连接池、超时与重试机制**。这会直接连接你项目里的 `ProductionHttpClient`、`NativeLLMClient` 和流式请求。回复“继续”开始。

