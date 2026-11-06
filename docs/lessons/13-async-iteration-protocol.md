# 异步迭代协议、异步生成器与 async for

> 本文逐字转录自原始课程对话，只添加角色标题和来源信息，未改写、删减或二次总结。
>
- 返回：[课程原文索引](README.md)
- 原始消息序号：`1857`、`1894`、`1901`、`1906`、`1913`、`1918`、`1925`、`1930`

## 用户（原始消息 1857）

继续下一课

## 助手（原始消息 1894）

**本课知识点：异步迭代协议、异步生成器与 `async for`**

前面的 SSE、`aclose()`、`EventSourceResponse`、`@asynccontextmanager` 都建立在这一套底层协议上。把这层搞懂后，异步流式代码就不再像“框架魔法”。

---

## 1. 同步迭代与异步迭代的对照

同步迭代协议：

```python
class NumberIterator:
    def __iter__(self):
        return self

    def __next__(self):
        if 没有数据了:
            raise StopIteration
        return 数据
```

使用：

```python
for item in NumberIterator():
    print(item)
```

异步迭代协议几乎对称：

```python
class AsyncNumberIterator:
    def __aiter__(self):
        return self

    async def __anext__(self):
        if 没有数据了:
            raise StopAsyncIteration
        return 数据
```

使用：

```python
async for item in AsyncNumberIterator():
    print(item)
```

对应关系：

| 同步 | 异步 |
|---|---|
| `__iter__()` | `__aiter__()` |
| `__next__()` | `__anext__()` |
| `StopIteration` | `StopAsyncIteration` |
| `for` | `async for` |
| `next(it)` | `await anext(it)` |

`__anext__()` 为什么必须异步？因为它内部可能需要：

```python
await asyncio.sleep(...)
```

或者：

```python
await response.aiter_lines()
```

也就是说，获取下一个元素本身就是异步操作。

---

## 2. `async for` 的展开过程

这段代码：

```python
async for token in stream:
    print(token)
```

大致等价于：

```python
iterator = stream.__aiter__()

while True:
    try:
        token = await iterator.__anext__()
    except StopAsyncIteration:
        break

    print(token)
```

这里有几层含义：

1. `__aiter__()` 得到异步迭代器。
2. 每次 `await iterator.__anext__()` 请求下一个元素。
3. 异步生成器内部运行到下一个 `yield`。
4. 数据耗尽时抛出 `StopAsyncIteration`。
5. `async for` 捕获这个终止信号并正常退出。

`StopAsyncIteration` 是迭代结束的控制信号，正常情况下不应该当成业务错误返回给前端。

---

## 3. 手写一个异步迭代器

```python
import asyncio


class TokenIterator:
    def __init__(self) -> None:
        self._tokens = ["你", "好", "！"]
        self._index = 0

    def __aiter__(self) -> "TokenIterator":
        return self

    async def __anext__(self) -> str:
        if self._index >= len(self._tokens):
            raise StopAsyncIteration

        token = self._tokens[self._index]
        self._index += 1
        await asyncio.sleep(0.1)
        return token
```

使用：

```python
async for token in TokenIterator():
    print(token)
```

这个类只实现协议，没有什么特殊继承要求。Python 的迭代协议本质上是鸭子类型：

> 只要你实现了规定的方法，就可以被 `async for` 消费。

---

## 4. 异步生成器是协议的便捷实现

手写 `__aiter__` 和 `__anext__` 比较麻烦，所以 Python 提供了异步生成器：

```python
async def token_stream() -> AsyncGenerator[str, None]:
    for token in ["你", "好", "！"]:
        await asyncio.sleep(0.1)
        yield token
```

只要一个 `async def` 函数里出现 `yield`，它的性质就变了：

```python
async def fetch() -> str:
    return "data"
```

这是异步协程函数，调用得到 coroutine。

```python
async def stream() -> AsyncGenerator[str, None]:
    yield "data"
```

这是异步生成器函数，调用得到 `async_generator` 对象，不是 coroutine。

因此下面的代码是错误的：

```python
result = stream()
await result
```

正确方式是：

```python
result = stream()
token = await anext(result)
```

异步生成器对象已经自动实现了：

- `__aiter__()`
- `__anext__()`
- `asend()`
- `athrow()`
- `aclose()`

所以它既是一个异步可迭代对象，也是一个异步迭代器。

---

## 5. 为什么说异步生成器是惰性执行

看项目代码：

[C:\work\python\ai-agent-leran\ai-engine\src\ai_engine\services\stream_service.py:24](C:\work\python\ai-agent-leran\ai-engine\src\ai_engine\services\stream_service.py:24)

```python
async def stream_llm_tokens(
    client: MockLLMClient,
    prompt: str,
) -> AsyncGenerator[str]:
    ...
    yield token
```

调用：

```python
stream = stream_llm_tokens(client, prompt)
```

此时以下代码都还没有执行：

- 客户端连接检查
- 初始化 token 列表
- `await asyncio.sleep(0.08)`
- 计数
- `yield`

只有第一次执行：

```python
token = await anext(stream)
```

生成器才真正开始运行，直到遇到第一个 `yield`：

```python
yield token
```

然后暂停。

第二次 `anext()` 会从：

```python
yield token
```

的下一行继续，而不是从头执行。

可以用一个简单例子验证：

```python
async def demo():
    print("A")
    yield 1
    print("B")
    yield 2
    print("C")


gen = demo()
print("创建完成")

print(await anext(gen))
print(await anext(gen))
```

输出顺序是：

```text
创建完成
A
1
B
2
```

直到下一次 `anext()` 才会打印 `C`，并触发 `StopAsyncIteration`。

---

## 6. `AsyncIterator` 和 `AsyncGenerator` 的区别

类型层面经常看到：

```python
from collections.abc import AsyncGenerator, AsyncIterator
```

区别是：

```python
AsyncIterator[str]
```

只承诺实现异步迭代协议：

- `__aiter__()`
- `__anext__()`

```python
AsyncGenerator[str, None]
```

除了迭代协议，还承诺生成器能力：

- `asend()`
- `athrow()`
- `aclose()`

两个类型参数的顺序是：

```python
AsyncGenerator[YieldType, SendType]
```

普通流式输出一般是：

```python
AsyncGenerator[str, None]
```

表示：

- `yield` 出来的是 `str`
- 外部通过 `asend()` 发送进去的是 `None`

如果函数只被 `async for` 消费，通常会写成：

```python
AsyncIterator[str]
```

因为调用方只需要迭代能力。

---

## 7. 一个异步生成器对象只能处于一个迭代状态

异步生成器内部有执行位置和局部变量：

```python
async def stream():
    for i in range(3):
        yield i
```

第一次使用：

```python
gen = stream()
print(await anext(gen))  # 0
print(await anext(gen))  # 1
```

如果再拿同一个生成器启动另一个循环：

```python
async for value in gen:
    print(value)
```

它不是重新从 `0` 开始，而是从当前状态继续：

```text
2
```

如果两次调用函数，则是两个独立对象：

```python
gen1 = stream()
gen2 = stream()
```

它们分别从 `0` 开始，互不影响。

但同一个异步生成器不能被两个消费者安全地并发调用：

```python
await asyncio.gather(
    anext(gen),
    anext(gen),
)
```

通常会产生类似：

```text
RuntimeError: anext(): asynchronous generator is already running
```

因为它不是线程安全、也不是并发安全的多播流。SSE 每个请求应该创建自己的异步生成器。

---

## 8. `yield` 如何实现暂停和背压

同步生成器暂停时保留局部变量；异步生成器同样如此：

```python
async def stream():
    count = 0
    while True:
        count += 1
        yield count
```

`yield` 会：

1. 把当前值交给消费者
2. 暂停函数执行
3. 保存调用栈和局部变量
4. 等待下一次 `anext()`

因此当前项目的链路是：

```text
浏览器/客户端
    ↓ 拉取 SSE
EventSourceResponse
    ↓ await __anext__()
generate_gateway_chat_stream()
    ↓ await __anext__()
NativeLLMClient.chat_stream()
    ↓ await response.aiter_lines()
上游模型服务
```

最外层不调用 `__anext__()`，内层就不会继续产生下一个 token，于是形成背压。

需要注意：`yield` 本身不是“取消”或“关闭”，只是暂停。资源仍然可能存在：

- 上游 HTTP 响应仍然打开
- 数据库游标可能仍然打开
- 生成器局部变量仍然存活

这就是为什么消费者退出时必须考虑显式关闭。

---

## 9. `async for` 退出时不一定自动关闭

这是流式代码最重要的工程边界之一。

```python
stream = llm_client.chat_stream(...)

async for token in stream:
    if should_stop:
        break
```

执行 `break` 后，`stream` 可能仍停在：

```python
yield content_token
```

它没有正常结束，也不一定会立刻执行清理逻辑。

同步迭代中也类似：

```python
for line in file:
    break
```

迭代器不会因为 `break` 就立即关闭，通常需要使用上下文管理器：

```python
with open(...) as file:
    ...
```

异步流式场景对应做法是：

```python
from contextlib import aclosing

async with aclosing(llm_client.chat_stream(...)) as stream:
    async for token in stream:
        ...
```

`contextlib.aclosing()` 的语义是：

```python
await stream.aclose()
```

无论代码块是正常结束、`break`、`return` 还是抛异常，都会进行显式关闭。

当前项目已经使用了它：

[C:\work\python\ai-agent-leran\ai-engine\src\ai_engine\api\v1\chat.py:52](C:\work\python\ai-agent-leran\ai-engine\src\ai_engine\api\v1\chat.py:52)

```python
async with aclosing(llm_client.chat_stream(...)) as token_stream:
    async for token in token_stream:
        ...
```

---

## 10. `aclose()` 和 `GeneratorExit`

调用：

```python
await stream.aclose()
```

如果生成器已经启动并暂停在 `yield`，Python 会在暂停点抛入：

```python
GeneratorExit
```

例如：

```python
async def stream():
    try:
        yield "A"
        yield "B"
    finally:
        await cleanup()
```

调用 `aclose()` 后：

```text
暂停在 yield "A"
    ↓
收到 GeneratorExit
    ↓
执行 finally
    ↓
await cleanup()
    ↓
生成器关闭
```

注意几个边界：

- `GeneratorExit` 不是 `asyncio.CancelledError`
- `GeneratorExit` 也不是 `Exception`
- `finally` 中可以执行 `await cleanup()`，但不能再次 `yield`
- 如果 `finally` 中再次 `yield`，可能报 `RuntimeError: async generator ignored GeneratorExit`
- 如果生成器从未启动，函数体没有进入，通常也不会执行其中的 `finally`

这也解释了：

```python
async with self.http_client.client.stream(...) as response:
    async for line in response.aiter_lines():
        yield content_token
```

被 `aclose()` 时，会退出这个 `async with`，从而关闭 HTTP 响应和底层连接。

---

## 11. `asend()`、`athrow()` 是什么

普通 `async for` 只使用 `__anext__()`，等价于每次发送 `None`。

异步生成器还支持：

```python
received = yield value
```

外部可以：

```python
next_value = await gen.asend(some_value)
```

例如：

```python
async def echo():
    while True:
        value = yield value

gen = echo()
await anext(gen)          # 启动并取得第一个值
await gen.asend("hello")  # 将 hello 发送到 yield 表达式
```

`athrow()` 可以向生成器内部抛入异常：

```python
await gen.athrow(ValueError("停止"))
```

3D 流式网关一般不需要这些功能，但它们是异步生成器接口的一部分。

---

## 12. 异常如何传播

如果异步生成器内部抛出普通异常：

```python
async def stream():
    yield "A"
    raise ValueError("模型响应格式错误")
```

消费者：

```python
async for token in stream():
    ...
```

当消费到第二个元素时，`ValueError` 会从：

```python
await iterator.__anext__()
```

向外传播。

项目里正是利用这一点：

[C:\work\python\ai-agent-leran\ai-engine\src\ai_engine\api\v1\chat.py:72](C:\work\python\ai-agent-leran\ai-engine\src\ai_engine\api\v1\chat.py:72)

```python
except Exception as exc:
    ...
    yield {"event": "error", ...}
    yield {"event": "done", "data": "[DONE]"}
```

上游解析失败、网络异常等会最初从内层生成器向上传播，到路由层被转换成一个 SSE `error` 事件。

但要注意：

- 已经发送了部分 token 后，HTTP 状态码通常已经是 200
- 后续只能发送业务 `error` 事件，不能改回 HTTP 500
- `CancelledError` 不应该被 `except Exception` 当作业务异常处理

---

## 13. 项目中的完整消费链路

内层客户端：

[C:\work\python\ai-agent-leran\ai-engine\src\ai_engine\services\llm_client.py:29](C:\work\python\ai-agent-leran\ai-engine\src\ai_engine\services\llm_client.py:29)

```python
async def chat_stream(...) -> AsyncGenerator[str, None]:
    ...
    async for line in response.aiter_lines():
        ...
        yield content_token
```

这一层负责：

- 请求上游模型
- 解析上游 SSE 行
- 把 token 作为异步生成器元素 `yield` 出去

网关层：

[C:\work\python\ai-agent-leran\ai-engine\src\ai_engine\api\v1\chat.py:35](C:\work\python\ai-agent-leran\ai-engine\src\ai_engine\api\v1\chat.py:35)

```python
async def generate_gateway_chat_stream(...) -> AsyncGenerator[dict[str, str], None]:
    async with aclosing(llm_client.chat_stream(...)) as token_stream:
        async for token in token_stream:
            ...
            yield {
                "event": "message",
                "id": str(emitted_tokens),
                "data": json.dumps({"content": token}, ensure_ascii=False),
            }
```

这一层负责：

- 消费内层 token
- 包装成 SSE 事件字典
- 分配事件类型和 ID
- 捕获业务异常并发送错误事件

框架层：

```python
return EventSourceResponse(stream_generator, ping=15)
```

`EventSourceResponse` 会把异步生成器消费成真正的 SSE 字节流，并周期性插入心跳注释。

完整调用关系是：

```text
HTTP 响应框架
  → 消费 generate_gateway_chat_stream
  → 消费 NativeLLMClient.chat_stream
  → 消费 httpx 的 aiter_lines()
  → 读取模型服务网络数据
```

---

## 14. 一个与项目装饰器有关的坑

项目里的：

[C:\work\python\ai-agent-leran\ai-engine\src\ai_engine\core\decorators.py:14](C:\work\python\ai-agent-leran\ai-engine\src\ai_engine\core\decorators.py:14)

```python
def async_timer[...](func: Callable[..., Coroutine[Any, Any, R]]):
    async def wrapper(...):
        return await func(*args, **kwargs)
    return wrapper
```

它是给普通异步协程函数用的。

如果你这样写：

```python
@async_timer
async def stream_tokens():
    yield "A"
```

会出错，因为：

```python
stream_tokens()
```

得到的是异步生成器对象，不是可以 `await` 的 coroutine。

对异步生成器计时，包装器本身也必须是异步生成器：

```python
def async_timer_gen(func):
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        start = time.perf_counter()
        try:
            async for item in func(*args, **kwargs):
                yield item
        finally:
            ...
    return wrapper
```

同理，`async_retry` 也不能简单包住整个已经输出部分内容的流式生成器，否则重试可能造成重复 token。重试通常应该发生在单个上游连接建立阶段，或者在没有向客户端输出任何内容之前。

---

**本课核心结论**

- `__aiter__()` 获取异步迭代器，`__anext__()` 等待下一个元素。
- `StopAsyncIteration` 是正常结束信号。
- `async def` 中只要包含 `yield`，返回的就是异步生成器，不是 coroutine。
- 异步生成器惰性执行，第一次 `anext()` 才运行到第一个 `yield`。
- `yield` 会暂停并保留状态，同时让整条消费链路形成背压。
- 异步迭代器是单消费者状态机，同一个对象不能被并发消费。
- `break` 不保证立即释放异步生成器资源。
- 使用 `aclosing()` 配合 `async with` 确定性关闭。
- `aclose()` 通常向暂停点注入 `GeneratorExit`，不是 `CancelledError`。
- 普通异步函数装饰器不能直接套在异步生成器函数上。

---

**验收问题**

1. `__aiter__()` 和 `__anext__()` 分别负责什么？
2. 异步迭代正常结束时，应抛出哪个异常？
3. 请写出 `async for` 大致等价的 `while` 循环。
4. `async def stream(): yield ...` 调用返回的是什么对象？
5. 为什么要等到第一次 `anext()` 或进入 `async for` 后，异步生成器才开始执行？
6. `AsyncIterator` 和 `AsyncGenerator` 的接口有什么区别？
7. 同一个异步生成器被两个并发任务同时 `anext()` 会发生什么？
8. `async for` 中执行 `break` 后，为什么可能需要 `aclosing()`？
9. `aclose()` 会在暂停点注入哪个异常？`finally` 中能否 `await`、能否再次 `yield`？
10. 当前项目中 `EventSourceResponse`、`generate_gateway_chat_stream()`、`NativeLLMClient.chat_stream()` 三者的消费关系是什么？

按编号回答即可，我会逐题批改。

## 用户（原始消息 1901）

1. aiter 获取迭代器本身，anext 获取下一个元素 2. 抛出 StopAsyncIteration 3. while True:  try:  value = await anext(iter) except StopAsyncIteration: break 4.  返回的是迭代器本身 5. 因为异步生成器是惰性的 6. AsyncIterator 只要求实现 aiter 和 anext 而 AsyncGenerator 还有 asend athrow 这些接口 7. 会发生错误，因为其不是线程安全的 8. break 后，迭代器可能只是停在 yield ，所以资源还未释放，因此可能会需要 aclosing 9. AsyncStopIteration 不能再次 yield 会报错 。10. nativellmclient.chat_steam() 解析大模型返回的流式token，交给 generate_gateway_chat_stream ，generate_gateway_chat_stream 又通过 yield 将其交给  EventSourceResponse 进行消费，最终返回给客户端

## 助手（原始消息 1906）

**批改：8.5/10**

第 1、2、5、6、8、10 题正确；第 3、4 题需要补充；第 7、9 题有概念错误。

**1. 正确**

- `__aiter__()` 返回异步迭代器。
- `__anext__()` 等待并返回下一个元素。

对于异步生成器：

```python
gen = stream()
gen.__aiter__() is gen  # True
```

它既是异步可迭代对象，也是异步迭代器。

**2. 正确**

迭代正常结束时抛出：

```python
StopAsyncIteration
```

`async for` 会捕获它并结束循环，不会把这个异常暴露给业务代码。

**3. 方向正确，但缺少起始步骤**

完整展开应类似：

```python
iterator = iterable.__aiter__()

while True:
    try:
        value = await iterator.__anext__()
    except StopAsyncIteration:
        break

    # async for 的循环体
```

可以简化为：

```python
iterator = iterable.__aiter__()

while True:
    try:
        value = await anext(iterator)
    except StopAsyncIteration:
        break
```

关键点是不能直接从 `iterable` 开始，`async for` 会先调用 `__aiter__()`。

**4. 需要更精确**

调用：

```python
stream = stream_tokens()
```

返回的是一个**新创建的异步生成器对象**，不是原来某个迭代器。

异步生成器对象同时满足两个身份：

```text
AsyncIterable：可以放到 async for 右边
AsyncIterator：实现了 __anext__
```

这类对象通常可以表述为：

> 调用异步生成器函数，创建并返回一个新的异步生成器对象。

**5. 正确**

异步生成器是惰性的。调用函数时：

```python
stream = stream_tokens()
```

函数体还没有执行。

第一次：

```python
await anext(stream)
```

或第一次进入：

```python
async for item in stream:
```

才运行到第一个 `yield`。

**6. 正确**

- `AsyncIterator`：核心协议是 `__aiter__()`、`__anext__()`。
- `AsyncGenerator`：额外提供 `asend()`、`athrow()`、`aclose()`。

补充一个区别：`AsyncGenerator` 是具体能力更丰富的生成器类型，通常不需要自己继承它；它主要用于类型标注。

**7. 结论对，原因不准确**

不是“线程不安全”这么简单。正常异步程序本身运行在单个事件循环线程中。

真正原因是：

> 同一个异步生成器是一个有状态的执行单元，不能被并发、重入地推进。

例如：

```python
await asyncio.gather(
    anext(gen),
    anext(gen),
)
```

可能得到：

```text
RuntimeError: anext(): asynchronous generator is already running
```

它不是设计给多个消费者同时拉取的多播流。

另外还有顺序使用的状态问题：

```python
gen = stream()

await anext(gen)  # 0
await anext(gen)  # 1
```

如果另一个循环继续消费同一个 `gen`，它会从当前位置继续，而不是从头开始。

**8. 正确**

`break` 只是停止继续调用 `__anext__()`，并不保证调用 `aclose()`。

异步生成器可能继续停留在：

```python
yield token
```

并持有：

- 上游 HTTP 响应
- 网络连接
- 文件或数据库游标
- `try/finally` 尚未执行的清理逻辑

所以项目使用：

```python
async with aclosing(token_stream):
    async for token in token_stream:
        ...
```

保证退出时显式关闭。

**9. 错误**

`aclose()` 注入的不是 `StopAsyncIteration`，而是：

```python
GeneratorExit
```

它不是 `Exception` 的子类，也不是 `asyncio.CancelledError`。

`finally` 中：

```python
async def stream():
    try:
        yield "A"
    finally:
        await close_resource()
```

可以执行 `await`，但不能再 `yield`。

如果关闭过程中再次产出元素：

```python
async def bad_stream():
    try:
        yield "A"
    finally:
        yield "B"  # 错误
```

可能得到：

```text
RuntimeError: async generator ignored GeneratorExit
```

还要注意：如果生成器从未启动，`aclose()` 通常不会进入函数体，因此其中的 `finally` 也不会执行。

**10. 正确**

完整链路是：

```text
NativeLLMClient.chat_stream()
    解析上游数据，yield token
            ↓
generate_gateway_chat_stream()
    消费 token，包装成 SSE dict 并 yield
            ↓
EventSourceResponse
    持续消费异步生成器，序列化为 SSE 字节流
            ↓
HTTP 客户端
```

`EventSourceResponse` 是最终消费者。它不调用 `__anext__()` 时，网关生成器暂停；网关生成器暂停时，也不会继续消费 `chat_stream()`，从而形成背压。

---

**下一步建议**

进入知识点：**Python 装饰器与异步装饰器**。

项目里的 `@async_timer`、`@async_retry`、`@functools.wraps` 正好可以串起闭包、函数替换、带参数装饰器、类型保留和异步生成器适配。回复“继续”开始。

## 用户（原始消息 1913）

进入下一步之前，你先帮我再讲讲 GeneratorExit 以及 asend athrow

## 助手（原始消息 1918）

**本课补充：`GeneratorExit`、`asend()` 与 `athrow()`**

这三个概念都围绕同一件事：

> 异步生成器不是只能单向 `yield` 数据，它还可以被外部“推进”和“注入异常”。

普通 `async for` 只用了最基础的能力，没有使用 `asend()` 和 `athrow()`。

---

## 1. `GeneratorExit` 是什么

`GeneratorExit` 是 Python 在关闭生成器时注入到生成器内部的特殊异常。

可以粗略理解为：

```python
await generator.aclose()
```

等价于告诉生成器：

> 不再需要你继续产生数据了，请执行清理并退出。

如果生成器当前暂停在：

```python
async def stream():
    try:
        yield "A"
        yield "B"
    finally:
        print("执行清理")
```

调用：

```python
gen = stream()
print(await anext(gen))  # A
await gen.aclose()
```

`aclose()` 会在暂停点：

```python
yield "A"
```

注入 `GeneratorExit`。

执行过程是：

```text
暂停在 yield "A"
        ↓
aclose() 注入 GeneratorExit
        ↓
退出 try 代码块
        ↓
执行 finally
        ↓
生成器关闭
```

因此会输出：

```text
A
执行清理
```

### 是否需要自己捕获 GeneratorExit

通常不需要直接写：

```python
except GeneratorExit:
    ...
```

更可靠的方式是使用 `finally`：

```python
async def stream():
    try:
        yield "A"
    finally:
        await close_resource()
```

`finally` 可以同时处理：

- 正常执行完毕
- 代码抛出普通异常
- `aclose()` 注入 `GeneratorExit`
- 当前任务取消导致的 `CancelledError`

### `finally` 中可以 `await` 吗

可以：

```python
finally:
    await close_connection()
```

异步生成器的 `aclose()` 本身是异步操作，因此它会等待这里的清理完成。

但清理不应无限等待。例如：

```python
finally:
    await asyncio.sleep(3600)
```

那么 `aclose()` 也会卡住一小时。

### `finally` 中可以再次 `yield` 吗

不可以。

```python
async def bad_stream():
    try:
        yield "A"
    finally:
        yield "B"
```

关闭时可能得到：

```text
RuntimeError: async generator ignored GeneratorExit
```

因为生成器被要求关闭后，不应该再产生新数据。

### `GeneratorExit` 是什么类型的异常

它直接继承自 `BaseException`：

```python
issubclass(GeneratorExit, BaseException)  # True
issubclass(GeneratorExit, Exception)      # False
```

所以：

```python
except Exception:
    ...
```

捕获不到它。

它的继承关系大致是：

```text
BaseException
├── GeneratorExit
├── SystemExit
├── KeyboardInterrupt
└── asyncio.CancelledError
```

### 生成器还没启动时调用 `aclose()`

```python
gen = stream()
await gen.aclose()
```

如果生成器从未执行过 `anext()`，函数体还没有进入，通常不会执行其中的 `finally`。

因为 `try/finally` 代码块本身还没有开始。

### `GeneratorExit` 与 `CancelledError` 的区别

两者触发原因不同：

| 异常 | 来源 | 含义 |
|---|---|---|
| `GeneratorExit` | `generator.aclose()` | 关闭这个生成器 |
| `CancelledError` | `Task.cancel()` | 取消整个任务 |

例如客户端断开连接后，可能发生：

```text
HTTP 响应任务被取消
        ↓
async generator 当前 await 收到 CancelledError
        ↓
路由层退出 async with aclosing
        ↓
aclosing 调用内层 generator.aclose()
        ↓
内层 generator 收到 GeneratorExit
```

这是两个不同层次的信号。

### `aclose()` 会吞掉 `GeneratorExit` 吗

正常情况下会。

你调用：

```python
await gen.aclose()
```

不会看到：

```python
GeneratorExit
```

从 `aclose()` 中冒出来。`GeneratorExit` 是关闭过程的内部控制信号。

但如果生成器在清理时抛出了另一个异常：

```python
finally:
    raise RuntimeError("关闭连接失败")
```

那么 `aclose()` 会把 `RuntimeError` 抛给调用方。

---

## 2. `yield` 不只是单向输出

普通理解中：

```python
yield token
```

像是“把 token 推给消费者”。

但在生成器协议里，`yield` 还可以是一个表达式：

```python
received = yield token
```

这表示：

1. 先把 `token` 交给外部
2. 暂停
3. 等待外部下一次推进
4. 外部发送进来的值赋给 `received`

所以数据流是双向的：

```text
生成器内部
    yield token
        ↓ token 输出给外部

外部
    asend(value)
        ↓ value 输入给生成器

生成器内部
    received = yield token
```

可以画成：

```text
外部消费者                       异步生成器
    |                                  |
    |------ 请求第一个值 ------------->|
    |                                  | yield "A"
    |<----- "A" -----------------------|
    |                                  | 暂停
    |------ asend(100) --------------->|
    |                                  | received = 100
    |                                  | 继续执行
    |<----- "B" -----------------------|
```

---

## 3. `asend()` 基础示例

```python
import asyncio
from collections.abc import AsyncGenerator


async def accumulator() -> AsyncGenerator[int, int | None]:
    total = 0

    while True:
        value = yield total

        if value is None:
            break

        total += value
```

启动生成器：

```python
gen = accumulator()
print(await anext(gen))  # 0
```

此时执行到：

```python
value = yield total
```

先 `yield 0`，然后暂停。

发送一个值：

```python
print(await gen.asend(5))  # 5
```

执行过程：

```text
恢复生成器
value = 5
total += 5
进入下一轮
yield 5
```

再次发送：

```python
print(await gen.asend(7))  # 12
```

最后发送 `None`：

```python
try:
    await gen.asend(None)
except StopAsyncIteration:
    print("生成器正常结束")
```

由于代码执行：

```python
if value is None:
    break
```

生成器结束，并抛出 `StopAsyncIteration`。

### 类型标注

```python
AsyncGenerator[YieldType, SendType]
```

例如：

```python
AsyncGenerator[int, int | None]
```

表示：

- `yield` 输出 `int`
- `asend()` 可以接收 `int` 或 `None`

项目中的流式生成器：

```python
AsyncGenerator[str, None]
```

表示：

- 输出 `str` token
- 外部只会发送 `None`
- 没有使用 `asend()` 向生成器传递业务数据

普通 SSE 流通常就属于这一类。

---

## 4. `anext()` 和 `asend(None)` 的关系

对于异步生成器，可以近似理解为：

```python
await anext(gen)
```

相当于：

```python
await gen.asend(None)
```

`async for` 每次推进生成器时，本质上发送的是 `None`：

```python
async for token in stream:
    print(token)
```

生成器内部：

```python
received = yield token
```

这里的 `received` 会得到 `None`。

因此：

```python
async for
```

适合“只读取数据”的场景，不适合向生成器内部发送额外控制值。

---

## 5. 第一次 `asend` 必须发送 None

异步生成器还没有运行到第一个 `yield` 时，没有地方接收发送值。

错误写法：

```python
gen = accumulator()
await gen.asend(5)
```

可能得到：

```text
TypeError: can't send non-None value to a just-started async generator
```

正确方式：

```python
gen = accumulator()
await gen.asend(None)  # 启动并取得第一个 yield 值
await gen.asend(5)     # 此时 yield 已存在，可以接收 5
```

也可以先：

```python
await anext(gen)
```

---

## 6. `asend()` 常见状态错误

异步生成器处于不同状态时，`asend()` 的行为不同。

**尚未启动**

第一次只能发送 `None`。

**暂停在 yield**

可以发送任意符合 `SendType` 的值。

**已经正常结束**

再调用会得到：

```python
StopAsyncIteration
```

**当前仍在运行**

例如并发调用：

```python
await asyncio.gather(
    gen.asend(1),
    gen.asend(2),
)
```

可能得到：

```text
RuntimeError: anext(): asynchronous generator is already running
```

因为同一个生成器不能被重新进入。

---

## 7. `athrow()` 是什么

`asend()` 是向暂停点发送一个普通值。

`athrow()` 是向暂停点注入一个异常。

假设生成器暂停在：

```python
value = yield token
```

执行：

```python
await gen.athrow(ValueError("注入的业务异常"))
```

可以理解为，暂停点变成了：

```python
value = yield token
# 这里被抛出 ValueError
```

或者更直观地说：

```python
raise ValueError("注入的业务异常") at yield point
```

---

## 8. `athrow()` 基础示例

```python
import asyncio
from collections.abc import AsyncGenerator


async def resilient_stream() -> AsyncGenerator[str, None]:
    try:
        yield "A"
        yield "B"
        yield "C"
    except ValueError as exc:
        print(f"生成器内部捕获异常: {exc}")
        yield "fallback"
    finally:
        print("执行 finally 清理")
```

使用：

```python
gen = resilient_stream()

print(await anext(gen))  # A

print(await gen.athrow(ValueError("模型返回格式错误")))
```

执行过程：

```text
第一次 anext 产生 A 并暂停
        ↓
athrow 在 yield "A" 处注入 ValueError
        ↓
except ValueError 捕获
        ↓
yield "fallback"
        ↓
athrow 返回 "fallback"
```

输出：

```text
A
生成器内部捕获异常: 模型返回格式错误
fallback
```

---

## 9. `athrow()` 的几种结果

### 情况一：生成器捕获异常后继续 yield

```python
except ValueError:
    yield "fallback"
```

那么：

```python
await gen.athrow(ValueError(...))
```

会返回：

```python
"fallback"
```

### 情况二：生成器不捕获异常

```python
async def stream():
    yield "A"
    yield "B"
```

执行：

```python
await gen.athrow(ValueError("错误"))
```

异常会从生成器向外传播：

```python
ValueError("错误")
```

生成器随后结束。

### 情况三：生成器捕获异常后直接结束

```python
except ValueError:
    return
```

这时 `athrow()` 不会返回下一个值，而是抛出：

```python
StopAsyncIteration
```

### 情况四：生成器有 finally

无论异常是否被捕获，`finally` 都可能执行：

```python
finally:
    await close_resource()
```

---

## 10. `athrow()` 能注入 `CancelledError` 吗

语法上可以注入很多异常类型：

```python
await gen.athrow(asyncio.CancelledError())
```

但这通常不是推荐用法。

应该区分目的：

- 想关闭生成器并清理资源：使用 `aclose()`
- 想取消整个异步任务：使用 `task.cancel()`
- 想测试生成器对特定异常的响应：可以谨慎使用 `athrow()`

不要用 `athrow(CancelledError())` 假装取消任务。它只是向生成器内部注入一个异常，不会改变外部 Task 的取消状态。

---

## 11. 三个操作的关系

| 操作 | 向生成器传入什么 | 典型用途 |
|---|---|---|
| `anext(gen)` | `None` | 获取下一个值 |
| `gen.asend(value)` | 普通值 | 双向生成器通信 |
| `gen.athrow(exc)` | 异常 | 注入异常、测试、特殊控制 |
| `gen.aclose()` | `GeneratorExit` | 关闭并清理资源 |

`async for` 只使用最基础的读取协议，等价于不断执行 `anext()`。

---

## 12. 回到当前项目

项目中的内层客户端是：

[C:\work\python\ai-agent-leran\ai-engine\src\ai_engine\services\llm_client.py:29](C:\work\python\ai-agent-leran\ai-engine\src\ai_engine\services\llm_client.py:29)

```python
async def chat_stream(...) -> AsyncGenerator[str, None]:
    async with self.http_client.client.stream(...) as response:
        async for line in response.aiter_lines():
            ...
            yield content_token
```

这里：

- `AsyncGenerator[str, None]` 表示只输出 token
- 外部通过 `async for` 消费
- 外部实际每次发送的是 `None`
- 没有使用 `asend()` 让用户向生成器内部传值
- 没有使用 `athrow()` 进行复杂控制

网关层通过：

```python
async with aclosing(llm_client.chat_stream(...)) as token_stream:
    async for token in token_stream:
        ...
```

在退出时调用内层生成器的 `aclose()`。

如果内层生成器当前暂停在：

```python
yield content_token
```

那么会触发：

```text
GeneratorExit
    ↓
退出 async for
    ↓
退出 async with http_client.client.stream(...)
    ↓
关闭 HTTP 响应
```

这个关闭过程与客户端断连造成的 `CancelledError` 是不同层次的事情。

---

## 13. 最常见的坑

**只写 `except Exception`**

`GeneratorExit` 不会进入这里，因为它不是 `Exception` 子类。

**在 `finally` 中再次 `yield`**

会违反关闭协议，可能触发 `RuntimeError`。

**用 `aclose()` 代替任务取消**

`aclose()` 只关闭生成器，不会取消整个任务。

**用 `task.cancel()` 代替生成器关闭**

任务取消会让当前执行链收到 `CancelledError`，但仍应通过 `aclosing` 或 `finally` 确保生成器资源被释放。

**认为 `asend()` 是获取下一个值**

`asend(value)` 的重点是“向当前暂停的 `yield` 表达式发送 value”，返回值才是生成器下一次 `yield` 的内容。

**忽略了第一次 `asend` 的限制**

尚未启动的异步生成器只能接收 `None`。

---

**本课核心结论**

- `GeneratorExit` 是 `aclose()` 用来关闭生成器的控制信号，不是业务异常。
- 清理应放在 `finally`，不要在关闭后继续 `yield`。
- `GeneratorExit` 与 `CancelledError` 来源不同，不能混用。
- `asend()` 向 `yield` 表达式发送值，使生成器成为双向协程协议。
- `athrow()` 在暂停点注入异常，生成器可以捕获、继续输出或向外传播。
- 普通 `async for` 和 SSE 流只使用 `anext()`，通常不需要 `asend()`、`athrow()`。

理解后回复“继续”，我们进入 **Python 装饰器与异步装饰器**。

## 用户（原始消息 1925）

即使SendType不允许使用None 第一次 asend 也要发送 None 吗？ 这不是不符合类型约束了

## 助手（原始消息 1930）

**是的，静态类型上确实可能不合法。上一课说“近似等价”只适用于运行语义，不适用于类型约束。**

如果声明：

```python
async def accumulator() -> AsyncGenerator[int, int]:
    ...
```

这里的两个类型参数表示：

```text
yield 出来：int
asend 传入：int
```

那么：

```python
gen = accumulator()
await gen.asend(None)
```

从类型检查器角度看，就是在向一个只接收 `int` 的接口传入 `None`，因此 mypy、pyright 可能报错。

运行时允许第一次 `asend(None)`，是因为 Python 对“启动生成器”做了特殊处理：

```python
await gen.asend(None)  # 可以作为启动操作
```

但如果类型是 `AsyncGenerator[int, int]`，更规范、类型安全的启动方式是：

```python
first_value = await anext(gen)
```

---

## 为什么第一次允许发送 None

假设生成器是：

```python
async def accumulator() -> AsyncGenerator[int, int]:
    total = 0

    while True:
        value = yield total
        total += value
```

第一次启动时，生成器还没有运行到：

```python
value = yield total
```

它只是运行到 `yield total`，然后暂停。

所以第一次启动并不存在“把 None 赋给 value”这件事：

```python
value = yield total
```

`value` 要等下一次恢复生成器时才会被赋值。

因此可以这样使用：

```python
gen = accumulator()

first = await anext(gen)   # 启动，返回 0

second = await gen.asend(5)  # 恢复，执行 value = 5
```

这里完全没有发送 `None`，也符合：

```python
AsyncGenerator[int, int]
```

的静态类型约束。

---

## `anext()` 和 `asend(None)` 的区别

运行时，两者的启动效果很接近：

```python
await anext(gen)
await gen.asend(None)
```

都可以启动异步生成器。

但类型语义不同：

- `anext(gen)` 表示“请求下一个值”，不需要提供 `SendType`
- `asend(None)` 表示“向生成器发送 None”，仍然受 `SendType` 检查

所以对于：

```python
AsyncGenerator[int, int]
```

应优先写：

```python
first = await anext(gen)
```

而不是：

```python
first = await gen.asend(None)
```

---

## 和同步生成器完全一样

同步生成器也有同样的设计：

```python
def accumulator() -> Generator[int, int, None]:
    total = 0
    while True:
        value = yield total
        total += value
```

启动：

```python
gen = accumulator()
first = next(gen)  # 正确启动方式
```

发送值：

```python
second = gen.send(5)
```

虽然运行时：

```python
gen.send(None)
```

也可以用于启动，但从类型上看，`SendType` 是 `int`，传 `None` 同样不合适。

所以这不是异步生成器独有的问题，而是 Python 生成器协议本来的设计。

---

## 什么时候 `SendType` 应该包含 `None`

如果生成器确实会把 `None` 当作有效值接收，例如：

```python
async def accumulator() -> AsyncGenerator[int, int | None]:
    total = 0

    while True:
        value = yield total

        if value is None:
            break

        total += value
```

那么这里写：

```python
await gen.asend(None)
```

就是类型正确的，因为 `SendType` 明确包含 `None`。

它既能作为初始化手段，也能作为业务上的停止信号。

不过更清晰的设计通常是用专门命令类型：

```python
from typing import Literal

type AccumulatorCommand = int | Literal["stop"]


async def accumulator() -> AsyncGenerator[int, AccumulatorCommand]:
    total = 0

    while True:
        command = yield total

        if command == "stop":
            break

        total += command
```

---

## 最准确的表述

不要记成：

> 第一次 `asend()` 必须发送 `None`。

应记成：

> 第一次启动异步生成器时，不能第一次就发送非 `None` 的业务值；应该使用 `anext()`，或者把 `asend(None)` 视为特殊启动操作。

类型检查和代码设计上，优先使用：

```python
await anext(gen)
```

只有在生成器确实设计为接收 `None` 时，才把 `SendType` 写成：

```python
AsyncGenerator[YieldType, None]
```

或：

```python
AsyncGenerator[YieldType, SomeType | None]
```

你这个问题抓得很准。我之前那句“等价”应该限定为运行时行为，不能跨越到静态类型语义。

