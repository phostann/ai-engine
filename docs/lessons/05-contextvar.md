# ContextVar 与异步上下文隔离

> 本文逐字转录自原始课程对话，只添加角色标题和来源信息，未改写、删减或二次总结。
>
- 返回：[课程原文索引](README.md)
- 原始消息序号：`1014`、`1019`、`1055`、`1062`、`1067`

## 用户（原始消息 1014）

继续

## 助手（原始消息 1019）

下一课：**`ContextVar`、异步上下文隔离与请求级日志**。它解释为什么项目用 `_trace_id_var`，而不是模块级全局变量保存 `trace_id`，也是理解并发日志串线问题的核心。

## 助手（原始消息 1055）

**下一课：`ContextVar` 与异步上下文隔离**

先给结论：

```text
全局变量只有一份值
ContextVar 是同一个变量对象，但在不同上下文中可以有不同的值
```

项目里的 `trace_id` 不能用普通全局变量保存，否则并发请求会互相覆盖。

**1. 普通全局变量为什么不可靠**

```python
current_trace_id = "system"


async def handle_request(trace_id: str) -> None:
    global current_trace_id
    current_trace_id = trace_id
    await asyncio.sleep(1)
    print(current_trace_id)
```

同时处理两个请求：

```python
await asyncio.gather(
    handle_request("trace-A"),
    handle_request("trace-B"),
)
```

执行过程可能是：

```text
A 设置 current_trace_id = trace-A
A 遇到 await sleep，让出执行权
B 设置 current_trace_id = trace-B
B 遇到 await sleep
A 恢复并读取 current_trace_id
A 读到 trace-B，日志串号
```

注意：异步并发不等于多线程并发。即使整个事件循环只有一个线程，也会在 `await` 处交错执行多个任务，所以普通全局变量仍然不安全。

**2. `ContextVar` 保存的是一组上下文值**

```python
from contextvars import ContextVar

trace_id_var: ContextVar[str] = ContextVar("trace_id", default="system")
```

`trace_id_var` 这个对象本身在模块中只有一份，但它不直接保存某个字符串；它按照当前上下文保存值。

```python
trace_id_var.set("trace-A")
print(trace_id_var.get())  # trace-A
```

另一个任务中：

```python
trace_id_var.set("trace-B")
print(trace_id_var.get())  # trace-B
```

这两个值互不影响。

可以把它理解成：

```text
Context A:
    trace_id_var -> trace-A

Context B:
    trace_id_var -> trace-B
```

因此当前项目中，并发处理：

```text
请求 A -> Context A -> trace_id = A
请求 B -> Context B -> trace_id = B
请求 C -> Context C -> trace_id = C
```

彼此不会覆盖。

**3. `set()` 返回的 `Token` 是干什么的**

```python
token = _trace_id_var.set(trace_id)
try:
    yield trace_id
finally:
    _trace_id_var.reset(token)
```

`set()` 不仅设置新值，还会返回一个 `Token`，用来恢复设置前的值：

```python
print(_trace_id_var.get())     # system

token = _trace_id_var.set("A")
print(_trace_id_var.get())     # A

_trace_id_var.reset(token)
print(_trace_id_var.get())     # system
```

支持嵌套：

```python
token1 = var.set("A")
token2 = var.set("B")

var.reset(token2)   # 恢复为 A
var.reset(token1)   # 恢复为 system
```

`Token` 应该由执行 `set()` 的上下文负责 `reset()`，不要把它交给另一个任务使用。

必须使用 `try/finally`：

```python
token = var.set(trace_id)
try:
    ...
finally:
    var.reset(token)
```

否则中途异常时，当前上下文可能残留旧值。

**4. 协程和 `Task` 的上下文继承不同**

这是上一轮需要纠正的重点。

直接 `await` 一个协程：

```python
async def child():
    var.set("child")
    print(var.get())

await child()
print(var.get())
```

这里没有创建新任务，父子协程在同一个上下文中运行。因此子协程里的 `set()` 会留在当前上下文中。

创建新任务：

```python
async def child():
    var.set("child")
    print(var.get())

task = asyncio.create_task(child())
await task
print(var.get())
```

这里 `create_task()` 会复制当前上下文，作为新任务的上下文快照。子任务中的修改不会反向影响父任务。

准确关系是：

```text
直接 await 协程       -> 共享当前上下文
asyncio.create_task   -> 复制当前上下文快照
TaskGroup.create_task -> 复制当前上下文快照
```

**5. 子任务继承的是创建时的快照**

```python
var.set("A")

task = asyncio.create_task(child())  # 此刻复制 context，看到 A
var.set("B")

await task
```

子任务看到的仍然是它创建时的快照：

```text
子任务看到 A
父任务当前是 B
```

创建之后父任务再修改，不会自动同步到已经创建的子任务。

**6. 为什么日志能自动带上 `trace_id`**

当前项目定义了日志过滤器：

```python
class TraceIdFilter(logging.Filter):
    def filter(self, record: LogRecord) -> bool | LogRecord:
        record.trace_id = _trace_id_var.get("system")
        return True
```

每次产生日志时，过滤器从当前上下文中读取 `trace_id`，写入 `LogRecord`：

```python
record.trace_id = "trace-A"
```

日志格式再读取它：

```python
"%(asctime)s ... [%(trace_id)s] %(name)s: %(message)s"
```

所以业务代码不需要手动传递：

```python
logger.info("开始处理")
```

只要当前上下文里有 `trace_id`，日志就自动带上对应值：

```text
[2026-10-28 13:53:37] [INFO] [trace-A] ai_engine: 开始处理
```

`ContextVar` 负责保存请求上下文，`Logging Filter` 负责在日志产生时读取上下文，两者配合完成“日志染色”。

**7. 当前项目的执行链路**

```text
HTTP 请求到达
  ↓
get_request_trace_id 读取或生成 trace_id
  ↓
_trace_id_var.set(trace_id)，获得 token
  ↓
yield trace_id 给路由函数
  ↓
路由中的 logger.info 自动读取当前 trace_id
  ↓
SSE 流式输出期间继续使用该 trace_id
  ↓
请求和响应完整结束
  ↓
finally 执行 _trace_id_var.reset(token)
```

这解释了为什么 `TraceIdDep` 在 SSE 场景下需要 request scope。如果过早 reset，流式输出阶段的日志就会恢复默认值。

**8. ContextVar 适合存什么**

适合：

- `trace_id`
- `request_id`
- 当前用户 ID
- 当前租户 ID
- 语言和时区
- 权限上下文元数据

不适合存储：

```python
large_payload
database_session
http_client
file_content
```

这些对象有明确的资源所有权和生命周期，应由 `lifespan` 或请求依赖管理。

`ContextVar` 应该只保存“当前执行上下文需要的小型元数据”，不应该被当成隐藏的全局对象容器。

**9. ContextVar、ThreadLocal、全局变量的区别**

```text
普通全局变量：所有线程、任务共享一份值
threading.local：每个线程一份值
ContextVar：每个上下文一份值，异步任务可安全隔离
```

在异步 Web 服务中，请求会在同一线程的多个任务之间交错执行，因此不能使用普通全局变量保存请求身份。`ContextVar` 是专门为这种场景设计的。

**10. 当前项目中的隐患：两个不同的 ContextVar**

现在有两个文件分别定义：

```python
# core/context.py
_trace_id_var: ContextVar[str] = ContextVar("trace_id", default="system")

# core/lifecycle_ext.py
_trace_id_var: ContextVar[str] = ContextVar("trace_id", default="system")
```

它们名字相同，但实际上是两个不同的对象。

```text
context._trace_id_var != lifecycle_ext._trace_id_var
```

在其中一个变量中 `set()`，不会影响另一个变量读取到的值。

目前：

- 生产依赖从 `core.context` 导入。
- 部分测试从 `core.lifecycle_ext` 导入。

所以两套功能各自能通过测试，但它们并没有共享同一份追踪上下文。如果两个模块同时参与一条请求链路，日志中的 `trace_id` 可能不一致。

正确设计应该只保留一个 `ContextVar` 定义，例如统一放在：

```text
src/ai_engine/core/context.py
```

其他模块都从这里导入同一个对象。

**掌握标准**

你应该能回答：

1. 为什么异步单线程下普通全局变量仍会串数据？
2. `ContextVar.set()` 为什么需要返回 `Token`？
3. 直接 `await` 和 `create_task()` 的上下文行为有什么不同？
4. 子任务修改 `ContextVar` 后，父任务为什么看不到？
5. 日志过滤器如何取得当前请求的 `trace_id`？
6. 为什么两个模块定义同名 `ContextVar` 仍然是两个变量？
7. 为什么 `trace_id` 适合放 `ContextVar`，而数据库会话不适合？

## 用户（原始消息 1062）

1. 因为异步单线程下，事件循环会在多个任务中切换，就会导致串数据 2. 返回 token 方便重置回 set 前的值，一面同一个任务中发生错误 3. await 还在当前上下文中 而 create_task 会创建新的上下文 4. 子任务修改的是自己的副本，所以影响不到 5. 通过get方法获取请求上下文中的 trace_id 6. 因为他们是相互独立的变量啊，没有什么关联，只是恰巧名字相同 7. trace_id 是和上下文有关的，并且比较轻量，而数据库连接是全局共享的

## 助手（原始消息 1067）

**批改**

1. 基本正确。更准确地说：事件循环切换任务只是原因之一，根本原因是普通全局变量只有一份值。任务 A 设置后切到任务 B，B 再覆盖，A 恢复执行时就会读到错误值。

2. 正确，但重点是 `try/finally`。`Token` 用于精确恢复 `set()` 之前的值，并支持嵌套作用域；异常时必须在 `finally` 中 `reset(token)`。

3. 对，但要把“新上下文”说准确：`create_task()` 会复制当前上下文作为快照，不是创建一个完全空白、没有继承关系的上下文。子任务初始能看到父任务当时的值，之后修改互不影响。

4. 正确。

5. 正确。日志过滤器执行 `_trace_id_var.get()`，从当前执行上下文中读取值，再写入 `LogRecord.trace_id`。

6. 正确。模块名相同、变量名相同都不代表是同一个对象；`ContextVar("trace_id")` 创建了两次，就是两个独立变量。

7. 前半句正确，后半句需要修正。数据库连接并不一定是“全局共享”：

```text
连接池：应用级共享
会话：请求级独立
事务：绑定会话和借用到的连接
物理连接：从连接池临时借出，通常不能被两个事务同时使用
```

因此应该表述为：

> `trace_id` 是轻量的请求元数据，适合由上下文传播；数据库会话涉及事务隔离、连接借用和明确的生命周期，因此应由请求依赖管理，不能简单当成全局共享对象。

整体已经掌握。下一课建议学习 **Pydantic v2 的模型校验、字段约束与请求/响应边界**。

