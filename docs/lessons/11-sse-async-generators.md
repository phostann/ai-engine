# SSE、异步生成器与流式取消

> 本文逐字转录自原始课程对话，只添加角色标题和来源信息，未改写、删减或二次总结。
>
- 返回：[课程原文索引](README.md)
- 原始消息序号：`1671`、`1676`、`1722`、`1740`、`1785`

## 用户（原始消息 1671）

继续

## 助手（原始消息 1676）

下一课：**SSE、异步生成器与流式取消**。这一课会解释 `EventSourceResponse` 如何消费异步生成器、SSE 帧格式、客户端断连、生成器关闭、`aclose()` 以及计费清理为什么要 `shield`。

## 助手（原始消息 1722）

**下一课：SSE、异步生成器与流式取消**

当前项目有两条流式链路：

```text
上游 OpenAI 兼容接口
  ↓ HTTP SSE
httpx 流式读取
  ↓ aiter_lines
NativeLLMClient.chat_stream()
  ↓ 异步生成器逐个 Token
网关 SSE
  ↓ EventSourceResponse
浏览器或前端
```

“流式输出”不是一次返回大 JSON，而是连接保持打开，持续发送多个 SSE 事件。

**1. SSE 的基本格式**

HTTP 响应头：

```http
Content-Type: text/event-stream
Cache-Control: no-cache
Connection: keep-alive
```

一个事件由若干字段组成，并以空行结束：

```text
id: 1
event: message
data: {"content":"Python "}

```

下一帧：

```text
id: 2
event: message
data: {"content":"异步"}

```

字段含义：

```text
event: 事件类型
data:  事件数据
id:    事件编号
retry: 客户端重连等待时间，单位毫秒
:      注释行，可用于心跳
```

一行 `:` 开头的内容会被客户端忽略，因此适合做保活：

```text
: ping

```

当前：

```python
EventSourceResponse(stream_generator, ping=15)
```

`ping=15` 表示大约每 15 秒发送一次心跳，避免代理或负载均衡器认为连接空闲并关闭它。

**2. `[DONE]` 不是 SSE 标准**

SSE 标准没有：

```text
data: [DONE]
```

这是 OpenAI 兼容接口和当前网关定义的业务结束标记：

```python
yield {"event": "done", "data": "[DONE]"}
```

客户端必须理解：

```text
message -> 一段内容
error   -> 错误信息
done    -> 本次流结束
```

当前帧：

```python
yield {
    "event": "message",
    "id": str(emitted_tokens),
    "data": json.dumps({"content": token}, ensure_ascii=False),
}
```

`EventSourceResponse` 会把这些字典编码成：

```text
id: 1
event: message
data: {"content": "Python "}

```

不要自己拼接字符串交给 `EventSourceResponse`，除非确实需要控制原始字节。使用字典更安全，库会处理换行和编码。

**3. 异步生成器不会在调用时执行**

```python
async def chat_stream():
    print("开始")
    yield "A"
    yield "B"
    print("结束")
```

下面这行不会执行函数体：

```python
stream = chat_stream()
```

它只是创建异步生成器对象。

真正执行发生在：

```python
async for token in stream:
    print(token)
```

执行过程：

```text
创建异步生成器
  ↓
anext() 执行到第一个 yield
  ↓
消费 "A"
  ↓
再次 anext() 执行到第二个 yield
  ↓
消费 "B"
  ↓
再次 anext() 执行剩余代码
  ↓
StopAsyncIteration
```

`yield` 不只是“返回一个值”，它还会暂停整个函数，包括局部变量：

```python
async def stream():
    count = 0
    while count < 3:
        count += 1
        yield count
```

每次恢复后，`count` 仍然保留。

**4. 两层异步生成器如何衔接**

底层：

```python
async def chat_stream(...) -> AsyncGenerator[str, None]:
    async with self.http_client.client.stream(...) as response:
        async for line in response.aiter_lines():
            ...
            yield content_token
```

上层：

```python
async def generate_gateway_chat_stream(...):
    async for token in llm_client.chat_stream(...):
        yield {
            "event": "message",
            "data": json.dumps({"content": token}),
        }
```

可以理解为：

```text
EventSourceResponse 请求一个网关事件
  ↓
网关生成器请求一个 Token
  ↓
LLM 生成器请求一行上游 SSE
  ↓
httpx 从网络读取一行
  ↓
逐层向上返回
```

整个链路由消费方驱动，这个过程叫**拉取式流式处理**。

**5. 背压**

`yield` 会暂停生成器，直到下游请求下一个值。

```python
yield event
```

不会继续执行，直到 `EventSourceResponse` 或 `async for` 请求下一个事件。

如果客户端读取很慢：

```text
客户端读取慢
  ↓
EventSourceResponse 发送阻塞
  ↓
网关生成器暂停
  ↓
上游读取暂停
  ↓
TCP 接收窗口逐渐填满
```

这就是一种背压。它比“后台无限读取，再堆积到内存队列”更安全，因为不会无限积累 Token。

但如果中间加入无界 `asyncio.Queue`，这个背压可能被破坏，内存可能持续增长。生产流式系统要使用有界队列。

**6. `EventSourceResponse` 在做什么**

```python
return EventSourceResponse(stream_generator, ping=15)
```

它会：

- 设置 `text/event-stream` 响应头。
- 持续迭代异步生成器。
- 将字典编码为 SSE 帧。
- 周期性发送心跳。
- 检测连接状态。
- 在断开或关闭时停止消费流。
- 管理流式任务和资源清理。

它不会自动理解 `[DONE]`。结束语义由你的应用定义。

**7. 客户端断开后发生什么**

客户端关闭连接后，服务端会得到断开信号。`sse-starlette` 通常会取消对应的发送任务，异步生成器中可能出现：

```python
asyncio.CancelledError
```

当前代码主动检查：

```python
if await request.is_disconnected():
    break
```

这属于轮询检测，只能在生成器继续执行时检查。例如只有上游产生新 Token、代码继续循环时，才有机会调用它。

如果上游很久没有新 Token，`is_disconnected()` 不一定立即被发现；`EventSourceResponse` 自身也会处理连接关闭和取消。

`CancelledError` 在现代 Python 中继承自 `BaseException`，不会被：

```python
except Exception:
```

捕获。这通常是正确的：取消信号不能被普通异常处理吞掉。

正确模式：

```python
try:
    async for token in stream:
        yield token
except asyncio.CancelledError:
    logger.info("客户端断开，流式任务被取消")
    raise
finally:
    logger.info("清理流式资源")
```

必须重新 `raise`，否则会破坏任务取消语义。

**8. 为什么只写 `break` 还不够**

当前：

```python
async for token in llm_client.chat_stream(...) as stream:
    if await request.is_disconnected():
        break
```

`break` 会退出循环，但不应该依赖垃圾回收器去关闭内层异步生成器。内层生成器持有：

```python
async with self.http_client.client.stream(...) as response:
```

如果关闭不及时，上游 HTTP 连接可能暂时保持打开。

更明确的方式是：

```python
from contextlib import aclosing

async with aclosing(llm_client.chat_stream(messages)) as token_stream:
    async for token in token_stream:
        if await request.is_disconnected():
            return
        yield ...
```

`aclosing` 会在退出代码块时调用：

```python
await token_stream.aclose()
```

这会向生成器内部抛出关闭信号，使其执行：

```python
finally:
    ...
```

并退出：

```python
async with self.http_client.client.stream(...):
```

从而及时关闭上游响应。

也可以手动写：

```python
token_stream = llm_client.chat_stream(messages)
try:
    async for token in token_stream:
        ...
finally:
    await token_stream.aclose()
```

`aclosing` 只是把这种模式封装起来。

**9. 客户端断开后不要继续发送 `done`**

当前代码在 `break` 后还会执行：

```python
yield {"event": "done", "data": "[DONE]"}
```

如果客户端已经断开，这个事件没有意义，发送时还可能产生额外异常。

更合理的是：

```python
if await request.is_disconnected():
    logger.warning(...)
    return
```

`return` 会进入 `finally`，但不会继续尝试向已经断开的客户端写数据。

**10. 为什么计费需要 `asyncio.shield`**

当任务被取消时，普通 `finally` 中仍然可以执行同步清理，但如果清理包含：

```python
await save_token_billing_to_db(...)
```

这个 `await` 本身也可能被取消。

`asyncio.shield()` 的作用是：

```python
billing_task = asyncio.create_task(save_token_billing_to_db(...))
await asyncio.shield(billing_task)
```

保护的是内部的 `billing_task`，让它不因为外部任务取消而被取消。

但只写：

```python
await asyncio.shield(billing_task)
```

仍有问题：外部任务自身仍会立即收到 `CancelledError`。

因此当前实现：

```python
try:
    await asyncio.shield(billing_task)
except asyncio.CancelledError:
    await billing_task
    raise
```

逻辑是：

```text
外部任务被取消
  ↓
billing_task 受 shield 保护，继续执行
  ↓
外层收到 CancelledError
  ↓
等待 billing_task 完成
  ↓
重新抛出 CancelledError
```

`shield` 不会让外层任务变成不可取消，它只是阻止取消传播到内部任务。

不要对所有清理都使用 `shield`。可能无限阻塞的清理会导致进程无法正常退出，应配合超时和幂等策略。

**11. SSE 的 `id` 与断线重连**

当前每帧：

```python
"id": str(emitted_tokens)
```

浏览器收到 `id: 1`、`id: 2` 后会保存最后一个事件 ID。重新连接时可能发送：

```http
Last-Event-ID: 2
```

但当前服务端没有读取这个请求头，也没有恢复生成状态。因此当前 `id` 主要只是帧编号，不具备真正的断点续传能力。

真正的可恢复 SSE 需要：

- 全局唯一或会话内单调递增的事件 ID。
- 服务端保存已经发送的事件。
- 读取 `Last-Event-ID`。
- 从该 ID 之后重放事件。
- 处理事件保留时间和容量上限。

普通大模型聊天通常很难精确恢复，因为模型生成不是可随机重放的静态消息流。常见做法是保存已经生成的文本，然后从下一个文本片段继续。

**12. 原生浏览器 `EventSource` 的限制**

浏览器原生 API：

```javascript
const es = new EventSource("/events");
```

只支持 GET，而且不能设置任意请求头。

当前接口是：

```python
@router.post("/completions/stream")
```

因此不能直接使用原生 `EventSource` 调用这个 POST 接口。前端需要使用：

- `fetch + ReadableStream` 手动解析 SSE。
- 支持 POST 的 SSE polyfill。
- 把请求改成 GET，但要注意 URL 长度和安全问题。

这是协议层与浏览器 API 层的重要区别。

**13. 生产环境注意事项**

反向代理不能缓冲流：

```text
Nginx: proxy_buffering off
负载均衡空闲超时 > ping 间隔
压缩不要缓冲 SSE
```

否则客户端会遇到：

```text
服务端已经发送
但代理把多个事件缓冲起来
前端很久才一次收到
```

心跳间隔要小于代理和负载均衡器的空闲超时。

**14. 当前项目的改进点**

- `break` 后应直接 `return`，避免向断开客户端发送 `done`。
- 内层 `chat_stream` 最好用 `aclosing` 显式关闭。
- `except ValueError` 应替换为专用 Token 预算异常。
- 应增加 `except asyncio.CancelledError` 日志并重新抛出。
- SSE `id` 当前不支持断线续传，应明确只是帧序号。
- 浏览器原生 `EventSource` 不支持当前 POST 接口。
- `NativeLLMClient` 只解析单行 `data:`，足以覆盖 OpenAI Chat Completions，但不是通用 SSE 解析器。
- `ping=15` 合理，但要确保所有代理的空闲超时都会大于 15 秒。

**掌握标准**

1. SSE 一帧由哪些字段组成？
2. 为什么 `[DONE]` 不是 SSE 标准？
3. 异步生成器在什么时候开始执行？
4. 两层异步生成器如何形成背压？
5. 客户端断开后，`break` 为什么不足以保证资源及时释放？
6. `aclose()` 会触发异步生成器中的哪些逻辑？
7. 为什么 `except Exception` 不应该吞掉 `CancelledError`？
8. `asyncio.shield` 保护的是什么，为什么外部任务仍会被取消？
9. 当前 SSE 事件 ID 为什么还不能实现断点续传？
10. 为什么浏览器原生 `EventSource` 不能直接调用当前 POST 接口？

## 用户（原始消息 1740）

1. 由 id event 以及 data 组成，可能还有 retry 重试间隔以及 ping  不带key的 : 可以代表 ping  2. [DONE] 只能算前后端的一种约定 3. 在消费  anext 的时候开始执行 4. 第一层停止读取 ，第二层就也会停止读取 ，这样就形成了背压 5. 不知道 6. 不知道 7. CancelledError 是更具体的错误，表示协程被取消，可以做一些清理等工作，所以不应，而 Exception 范围太广了，不能更好的控制程序 8. 保护取消不会传播到被保护的携程，外部没被保护，当然会受取消影响。9.没有实现会话唯一且单调递增，并且大模型生成存在随机性，不是静态，所以当前的实现根本不能断点续传。10 。 浏览器就是那么实现的，默认只支持get

## 助手（原始消息 1785）

**批改结论**

你对 SSE 的整体链路已经理解了，第 1 到第 4 题、第 8 到第 10 题基本正确。主要缺口集中在三个地方：

- `break` 和 `aclose()` 的区别
- `GeneratorExit` 与 `CancelledError` 不是一回事
- `asyncio.shield` 实际保护了谁

---

**1. SSE 帧字段：基本正确**

SSE 标准字段是：

- `event`：事件类型
- `data`：数据内容，可以有多行
- `id`：事件 ID
- `retry`：客户端重连等待时间
- `:` 开头的是注释，例如：

```text
: ping - 2026-11-02 10:00:00
```

浏览器会忽略注释，所以 `sse-starlette` 可以用它保持连接活跃。

但 `ping` 不是 SSE 标准字段。你项目里的 `ping=15` 是 `EventSourceResponse` 的参数，表示每 15 秒发一次注释帧，不是发送 `ping: 15` 这种字段。

框架最终输出大致是：

```text
event: message
id: 1
data: {"content": "你好"}

```

末尾必须有一个空行，浏览器才会认为这一帧结束。

**2. `[DONE]`：正确**

`[DONE]` 是 OpenAI 流式接口定义的数据协议，不是 SSE 标准。

当前项目实际上同时用了两种“结束”：

```python
yield {"event": "done", "data": "[DONE]"}
```

- `event: done` 是项目自定义的事件类型
- `data: [DONE]` 是模仿 OpenAI 的数据结束标记

前端可以监听 `done` 事件，也可以判断数据是否等于 `[DONE]`。

**3. 异步生成器执行时机：正确**

调用：

```python
stream = llm_client.chat_stream(messages)
```

只是创建异步生成器对象，函数体不会执行。

第一次执行：

```python
token = await stream.__anext__()
```

或者第一次进入：

```python
async for token in stream:
    ...
```

函数才开始运行，直到遇到第一个 `yield`，然后暂停。

后续每次请求下一个元素，它会从暂停位置继续执行。

**4. 背压：方向正确，可以再精确一点**

完整链路是：

```text
客户端
  ↓ 拉取一帧
网关异步生成器
  ↓ 请求下一个 token
LLMClient 异步生成器
  ↓ 读取一行
上游 HTTP 响应
```

最外层消费者不继续拉取时：

1. 网关生成器暂停在 `yield`
2. 它不会继续执行 `async for`
3. 因此不会调用内层生成器的下一次 `__anext__()`
4. 内层生成器也暂停在内层 `yield`
5. 上游数据逐渐填满网络缓冲区
6. 最终通过 TCP/HTTP 流控对上游形成背压

所以并不是“客户端一暂停，大模型立刻停止”，而是“网关停止继续消费，网络缓冲区填满后逐渐反压上游”。

---

**5. 为什么单靠 `break` 不足以保证释放资源**

这是你目前最主要的缺口。

`async for` 在 `break` 时只会停止继续调用异步生成器的 `__anext__()`。它不会自动调用：

```python
await generator.aclose()
```

因此生成器可能继续停留在暂停状态：

```python
async def stream():
    async with open_resource() as resource:
        try:
            yield "A"
            yield "B"
        finally:
            await cleanup()
```

消费者执行 `break` 后，生成器状态还是：

```text
已产生 "A"，暂停在 yield "A"
```

它既没有正常结束，也没有立即执行 `finally`。

Python 可能稍后通过垃圾回收或事件循环关闭阶段触发异步生成器清理，但时机不确定，极端情况下可能迟迟不释放连接，甚至产生：

```text
Task was destroyed but it is pending
async generator ignored GeneratorExit
```

这类问题。

不过你的当前代码其实已经补上了这一点：

```python
async with aclosing(llm_client.chat_stream(...)) as token_stream:
    async for token in token_stream:
        ...
```

`aclosing` 会在退出代码块时执行：

```python
await token_stream.aclose()
```

所以准确说法是：

> 单靠 `break` 不够，但当前代码通过 `aclosing` 补上了确定性关闭。

另一个问题是，你在客户端断开后只是 `break`，之后还会继续发送：

```python
yield {"event": "done", "data": "[DONE]"}
```

客户端已经断开，再写结束帧没有意义。这里更合理的做法是直接 `return`：

```python
if await request.is_disconnected():
    return
```

`return` 会退出生成器，同时触发 `aclosing` 关闭内层流。

**6. `aclose()` 触发了什么**

对已经启动并暂停在 `yield` 的异步生成器调用：

```python
await generator.aclose()
```

Python 会在暂停位置抛入一个：

```python
GeneratorExit
```

它不是 `CancelledError`。

效果类似：

```python
async def stream():
    try:
        yield "A"
    finally:
        print("清理")
```

调用 `aclose()` 后，生成器会在 `yield "A"` 处收到 `GeneratorExit`，然后执行 `finally`，最终关闭生成器。

在你的项目里，内层生成器是：

```python
async with self.http_client.client.stream(...) as response:
    async for line in response.aiter_lines():
        yield content_token
```

`aclose()` 会触发 `async with` 的 `__aexit__()`，从而关闭 HTTP 响应、释放底层连接。

如果生成器从来没有启动过，那么函数体没有进入，`try/finally` 也不会执行。

还要注意，`GeneratorExit` 不是 `asyncio.CancelledError`，所以：

```python
except asyncio.CancelledError:
    ...
```

捕获不到 `aclose()` 产生的 `GeneratorExit`。真正可靠的释放位置是：

```python
finally:
    ...
```

或者异步上下文管理器的退出逻辑。

**7. 为什么不能吞掉 `CancelledError`：结论对，理由要纠正**

你有一句关键表述不准确：

> `CancelledError` 是更具体的错误，而 `Exception` 范围太广。

在现代 Python 中，继承关系是：

```text
BaseException
├── SystemExit
├── KeyboardInterrupt
├── GeneratorExit
└── asyncio.CancelledError

Exception
├── ValueError
├── RuntimeError
└── ...
```

也就是说，从 Python 3.8 开始：

```python
issubclass(asyncio.CancelledError, Exception)  # False
```

所以普通的：

```python
except Exception:
    ...
```

根本捕获不到 `CancelledError`。

不能吞掉它的真正原因是：`CancelledError` 是任务取消的控制信号，不是普通业务异常。它表示“上层要求这个协程停止”。如果捕获后不重新抛出：

```python
except asyncio.CancelledError:
    print("我处理掉了")
```

就会破坏任务取消语义，让调用方以为任务正常结束，可能导致：

- 服务关闭时协程不退出
- 超时控制失效
- 父任务无法正确等待子任务结束
- 取消信号无法继续传播

正确写法通常是：

```python
except asyncio.CancelledError:
    # 只做必要记录或清理
    raise
```

或者更常见的是连捕获都不需要，直接放在 `finally` 中清理：

```python
finally:
    await cleanup()
```

**8. `asyncio.shield`：基本正确**

`asyncio.shield(billing_task)` 保护的是被包裹的内部任务，不是外层等待它的任务。

```python
await asyncio.shield(billing_task)
```

发生外层取消时：

1. 外层 `await` 收到 `CancelledError`
2. `billing_task` 不会因此被取消，继续执行
3. 外层任务仍然处于被取消流程中

当前项目在异常分支里等待计费任务完成，这个思路是对的：

```python
billing_task = asyncio.create_task(save_token_billing_to_db(...))

try:
    await asyncio.shield(billing_task)
except asyncio.CancelledError:
    await billing_task
    raise
```

有两点边界需要知道：

- 这里必须先 `create_task()`，确保内部任务已经成为一个独立 Task
- `shield` 不能抵抗进程退出、机器宕机或事件循环被立即关闭

生产系统里更可靠的计费应当进入持久化队列，而不是只依赖 `shield`。

**9. SSE 断点续传：结论正确，但随机性不是根本原因**

当前代码的 ID 是：

```python
"id": str(emitted_tokens)
```

它只是一个每次请求都从零开始的 token 序号。

要支持断点续传，至少需要：

1. 一个稳定的 `stream_id`
2. 每个事件有单调递增的序号
3. 服务端保存已经生成的事件
4. 客户端重连时发送 `Last-Event-ID`
5. 服务端根据该 ID 补发后续事件

例如：

```text
id: stream-abc:1
id: stream-abc:2
id: stream-abc:3
```

即使大模型输出是确定性的，只要没有保存事件历史，也仍然无法续传。大模型随机性只是让“重新生成一遍”也无法得到相同内容。

**10. 原生 `EventSource` 不支持 POST：正确**

浏览器原生：

```javascript
new EventSource("/api/v1/chat/completions/stream")
```

只能发 GET 请求，不能携带 JSON 请求体，也不能方便地自定义 `Authorization` 请求头。

当前接口是：

```post
POST /api/v1/chat/completions/stream
Content-Type: application/json
```

因此不能直接用原生 `EventSource`。

常见方案是：

- 使用 `fetch()` 读取 `ReadableStream`，自己解析 SSE
- 使用支持 POST SSE 的第三方库
- 后端另开一个 GET SSE 接口，通过查询参数传递会话 ID

---

**本项目当前最值得修正的一点**

`C:\work\python\ai-agent-leran\ai-engine\src\ai_engine\api\v1\chat.py:56` 附近，客户端断开后建议直接从生成器返回：

```python
if await request.is_disconnected():
    logger.warning(...)
    return
```

不要只 `break` 后继续发送 `done` 帧。当前第 52 行使用了 `aclosing`，所以资源关闭这一层已经做对了。

下一知识点建议进入：**asyncio 取消传播、Task、TaskGroup、`wait_for`、`timeout` 与 `shield` 的完整任务生命周期**。回复“继续”即可开始。

