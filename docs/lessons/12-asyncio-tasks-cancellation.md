# asyncio 任务生命周期、取消、结构化并发与超时

> 本文逐字转录自原始课程对话，只添加角色标题和来源信息，未改写、删减或二次总结。
>
- 返回：[课程原文索引](README.md)
- 原始消息序号：`1792`、`1825`、`1832`、`1837`、`1844`、`1847`

## 用户（原始消息 1792）

继续

## 助手（原始消息 1825）

**本课知识点：asyncio 任务生命周期、取消、结构化并发与超时**

这一课把几个经常混在一起的概念拆开：

- coroutine、Task、Future 的区别
- `cancel()` 到底做了什么
- `TaskGroup` 与 `gather()` 的区别
- `Semaphore` 如何限制并发
- `asyncio.timeout()` 与 `wait_for()`
- `shield()` 保护什么
- 这些机制在当前项目中的实际应用

---

## 1. coroutine 不是 Task

下面这个函数只是异步函数：

```python
async def fetch_data() -> str:
    await asyncio.sleep(1)
    return "data"
```

调用它：

```python
coro = fetch_data()
```

此时函数体不会执行，只会得到一个 coroutine 对象。

coroutine 必须被驱动：

```python
result = await coro
```

或者包装成 Task：

```python
task = asyncio.create_task(coro)
```

两者的关键区别是：

```python
# 当前任务一直等待它完成
await fetch_data()

# 立即交给事件循环调度，当前任务继续执行
task = asyncio.create_task(fetch_data())
```

`create_task()` 不会等待任务结束，它会马上返回一个 `Task` 对象。

可以把它理解为：

```text
coroutine：一份待执行的工作说明书
Task：已经提交给事件循环、正在被管理的工作
Future：一个未来会得到结果的占位对象
```

---

## 2. Task 的生命周期

Task 主要有三种状态：

```text
PENDING
   ↓
DONE
 ├── 正常完成
 ├── 抛出异常
 └── 被取消
```

创建任务：

```python
task = asyncio.create_task(work())
```

检查状态：

```python
task.done()
task.cancelled()
task.cancelling()
```

读取结果：

```python
result = await task
```

如果任务抛出了异常，`await task` 会重新抛出这个异常。

也可以用：

```python
task.result()
task.exception()
```

但通常更推荐 `await task`，因为异常不会被悄悄丢掉。

### 裸 `create_task()` 的一个重要陷阱

下面的代码有一个隐患：

```python
asyncio.create_task(background_job())
```

创建完以后没有保存 `task` 引用。

事件循环对 Task 通常只保留弱引用，如果这个 Task 没有其他强引用，理论上可能在完成前被垃圾回收。

更稳妥的写法是保存引用：

```python
background_tasks: set[asyncio.Task] = set()

task = asyncio.create_task(background_job())
background_tasks.add(task)
task.add_done_callback(background_tasks.discard)
```

或者直接使用 `TaskGroup`，因为 `TaskGroup` 会替我们持有并管理所有子任务。

---

## 3. `cancel()` 不是“立即杀死任务”

`task.cancel()` 只是发出取消请求：

```python
task.cancel()
```

它返回的 `True` 也只表示取消请求已经提交，不表示任务已经停止。

真正的取消是协作式的：

1. 任务通常在下一个 `await` 处收到 `CancelledError`
2. 协程可以执行 `finally` 进行清理
3. 如果协程重新抛出 `CancelledError`，任务最终变成 cancelled
4. 如果协程吞掉了 `CancelledError`，任务可能继续运行

例如：

```python
async def worker() -> None:
    try:
        await asyncio.sleep(10)
    except asyncio.CancelledError:
        print("收到取消信号")
        raise
```

这里的 `raise` 非常重要。

再看一个反例：

```python
async def bad_worker() -> None:
    try:
        await asyncio.sleep(10)
    except asyncio.CancelledError:
        return "我假装没收到取消"
```

取消信号被吞掉，调用方可能以为任务已经停止，但实际语义已经被破坏。

### 取消只能发生在 await 等挂起点

如果任务正在执行纯 CPU 同步代码：

```python
while True:
    x = x * 2
```

即使执行了：

```python
task.cancel()
```

它也无法插入 `CancelledError`，因为协程根本没有把控制权交还给事件循环。

所以：

- `await asyncio.sleep()` 可被取消
- `await client.get()` 可被取消
- `requests.get()` 会阻塞整个事件循环，不能及时取消
- 长时间 CPU 计算也不会自动被取消

在异步程序中，所有阻塞操作都应该使用异步版本，或者放进线程池/进程池。

---

## 4. `finally` 中可以做清理，但清理也可能被打断

例如：

```python
async def worker() -> None:
    try:
        await asyncio.sleep(10)
    finally:
        await close_connection()
```

收到第一次取消后，`await asyncio.sleep(10)` 抛出 `CancelledError`，代码进入 `finally`。

但 `finally` 里的 `await close_connection()` 并不是绝对安全的。如果又来了第二次取消，它也可能被打断。

因此生产系统通常会：

- 让清理逻辑尽量短
- 给清理设置独立超时
- 使用 `shield` 保护关键清理
- 对计费等关键操作使用持久化队列

---

## 5. `asyncio.gather()` 与 `TaskGroup`

假设有三个任务：

```python
task1 = fetch_user()
task2 = fetch_orders()
task3 = fetch_balance()
```

用 `gather`：

```python
users, orders, balance = await asyncio.gather(task1, task2, task3)
```

返回结果顺序与传入顺序一致，而不是按完成时间排序。

常见参数：

```python
await asyncio.gather(
    task1,
    task2,
    return_exceptions=True,
)
```

这会把异常当成结果返回，而不是立刻抛出。

### `gather` 的关键行为

如果某个任务抛出普通异常，并且 `return_exceptions=False`：

- `gather` 会向调用方抛出这个异常
- 默认情况下，其他已经提交的任务不会被自动取消
- 它们可能继续运行

`gather` 拿到的如果只是 coroutine，会由内部包装为任务；如果你提前创建了 Task，它管理的是这些已有 Task。

### `TaskGroup` 是结构化并发

项目中的写法：

```python
async with asyncio.TaskGroup() as tg:
    tg.create_task(task1)
    tg.create_task(task2)
    tg.create_task(task3)
```

它保证：

1. 父作用域不会先退出，而把子任务丢在后台
2. 任意一个子任务抛出未处理异常
3. TaskGroup 自动取消同组其他子任务
4. 等待所有子任务结束
5. 将多个异常包装成 `ExceptionGroup`

例如：

```python
try:
    async with asyncio.TaskGroup() as tg:
        tg.create_task(task1)
        tg.create_task(task2)
except* ValueError:
    print("至少有一个任务抛出了 ValueError")
```

如果任务 1 抛出 `ValueError`，任务 2 还在运行，TaskGroup 会取消任务 2。

两者可以简单对比：

| 特性 | `asyncio.gather` | `asyncio.TaskGroup` |
|---|---|---|
| 结果顺序 | 保持输入顺序 | 需要自己收集 |
| 一个任务失败 | 默认不取消其他任务 | 自动取消兄弟任务 |
| 异常形式 | 原始异常或结果列表 | `ExceptionGroup` |
| 子任务生命周期 | 较弱 | 结构化托管 |
| 推荐场景 | 简单聚合 | 需要明确成败边界的并发 |

---

## 6. 项目中 `Semaphore + TaskGroup + timeout`

看这个文件：

[C:\work\python\ai-agent-leran\ai-engine\src\ai_engine\core\concurrency.py](C:\work\python\ai-agent-leran\ai-engine\src\ai_engine\core\concurrency.py)

核心结构是：

```python
semaphore = asyncio.Semaphore(max_concurrency)

async def _worker_wrapper(index: int, item: T) -> None:
    async with semaphore:
        async with asyncio.timeout(timeout_per_item):
            results[index] = await worker_fn(item)

async with asyncio.TaskGroup() as tg:
    for idx, item in enumerate(items):
        tg.create_task(_worker_wrapper(idx, item))
```

它同时解决三个问题：

### `Semaphore` 限制同时运行数量

```python
async with semaphore:
    ...
```

`max_concurrency=3` 表示最多有 3 个 worker 同时进入临界区。

注意：TaskGroup 仍然会为所有 `items` 创建任务，只是同一时刻最多 3 个任务能执行 `worker_fn`。

如果 items 有几百万个，先创建几百万个 Task 并不合理。那时应该使用固定数量的 worker 从队列取任务：

```python
queue = asyncio.Queue()
```

### 用固定索引保证结果顺序

```python
results[index] = await worker_fn(item)
```

虽然任务完成顺序可能不同，但结果写回预分配的位置：

```text
items:   [A, B, C]
tasks:   [task-A, task-B, task-C]
results: [r-A, r-B, r-C]
```

因此最终结果仍然与输入顺序一致。

### 任一任务失败时取消其余任务

TaskGroup 会自动取消兄弟任务。项目中测试验证了：

```python
if item_id == 1:
    raise ValueError("任务 1 发生异常")
```

另一个任务收到取消后，会进入：

```python
except asyncio.CancelledError:
    sibling_was_cancelled = True
    raise
```

### 当前代码有一个小问题

最后一行：

```python
return [r for r in results if r is not None]
```

类型声明允许 `R` 是任意类型，因此 `worker_fn()` 理论上可以正常返回 `None`：

```python
async def worker(item: int) -> None:
    ...
```

这时 `None` 会被过滤掉，导致结果数量和输入数量不一致。

更严谨的做法是：

1. 限制 `R` 不能是 `None`，或者
2. 使用独立标记判断槽位是否已填充，或者
3. 保留 `None`，直接做类型断言后返回。

例如：

```python
return [result for result in results if result is not _MISSING]
```

但这个改动不属于当前课程，知道这个边界即可。

---

## 7. `asyncio.timeout()`

Python 3.11+ 提供了：

```python
async with asyncio.timeout(3):
    await call_llm()
```

如果 3 秒内没有完成：

- 当前任务会收到取消
- `asyncio.timeout` 将这次取消转换成 `TimeoutError`
- 代码可以捕获：

```python
try:
    async with asyncio.timeout(3):
        await call_llm()
except TimeoutError:
    print("调用超时")
```

在项目里：

```python
async with semaphore:
    async with asyncio.timeout(timeout_per_item):
        results[index] = await worker_fn(item)
```

超时发生后，当前 worker Task 被取消，最终表现为 `TimeoutError`。

然后 TaskGroup 看见子任务抛出了 `TimeoutError`，会取消其他兄弟任务，并以 `ExceptionGroup` 形式向父级传播。

因此最终可能是：

```python
ExceptionGroup(
    "unhandled errors in a TaskGroup",
    [TimeoutError()]
)
```

捕获时可以写：

```python
try:
    await run_bounded_task_group(...)
except* TimeoutError:
    ...
```

### `asyncio.timeout()` 的两个边界

第一，它只能取消当前任务，不能取消一个不相关的后台任务。

第二，它依赖协作式取消。如果被调用代码一直执行同步 CPU 循环，不回到事件循环，超时也无法及时生效。

### `timeout()` 与 `wait_for()` 的区别

```python
await asyncio.wait_for(work(), timeout=3)
```

`wait_for()` 会在超时时取消被等待的 awaitable，然后抛出 `TimeoutError`。

```python
async with asyncio.timeout(3):
    await work()
```

`timeout()` 是上下文管理器，它取消的是当前任务，通过异常作用域把自身的取消转换为 `TimeoutError`。

现代 Python 中通常优先使用：

```python
async with asyncio.timeout(...):
    ...
```

因为它可以覆盖多个 await 语句，边界更清晰。

---

## 8. 再看 `asyncio.shield`

项目中的关键代码：

```python
billing_task = asyncio.create_task(
    save_token_billing_to_db(consumed, billing_ledger)
)

try:
    await asyncio.shield(billing_task)
except asyncio.CancelledError:
    await billing_task
    raise
```

假设外层流式任务被取消：

```text
外层 Task.cancel()
        ↓
await shield(billing_task) 收到 CancelledError
        ↓
billing_task 仍然继续运行
        ↓
外层捕获 CancelledError
        ↓
等待 billing_task 完成
        ↓
重新 raise CancelledError
```

需要特别强调：

**`shield` 保护的是内部的 `billing_task`，不是外层任务。**

外层任务仍然被取消，只是取消不会继续传播到 `billing_task`。

这个模式不是万能保险：

- 多个任务同时被取消时，计费任务仍可能承受压力
- 第二次取消可能打断后面的等待
- 进程崩溃、容器被杀死时完全无效
- 事件循环关闭过快时也可能来不及完成

所以生产级计费更倾向于：

```text
请求完成
  ↓
写入消息队列 / outbox 表
  ↓
独立消费者可靠落库
```

`shield` 适合保护短暂的收尾工作，不适合作为唯一的数据可靠性机制。

---

## 9. 项目中其他相关代码

流式服务：

[C:\work\python\ai-agent-leran\ai-engine\src\ai_engine\services\stream_service.py](C:\work\python\ai-agent-leran\ai-engine\src\ai_engine\services\stream_service.py)

```python
except asyncio.CancelledError:
    print("检测到客户端主动中断生成")
    raise
finally:
    print("结算")
```

这里顺序是正确的：

1. 捕获取消，进行必要记录
2. 重新抛出，保留取消语义
3. `finally` 做最终清理

HTTP 重试：

[C:\work\python\ai-agent-leran\ai-engine\src\ai_engine\core\http_client.py](C:\work\python\ai-agent-leran\ai-engine\src\ai_engine\core\http_client.py)

```python
await asyncio.sleep(sleep_time)
```

重试等待是可取消的。如果服务正在优雅关闭，这个 sleep 可以被取消，不会强行等待几秒。

而且这里捕获的是：

```python
except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError)
```

没有捕获 `CancelledError`，所以任务取消可以正常向外传播，这是正确行为。

---

## 本课核心结论

- coroutine 是待执行对象，Task 是被事件循环管理的执行单元。
- `cancel()` 是请求，不是强制终止；取消依赖 `await` 挂起点。
- `CancelledError` 必须向外传播，清理逻辑放在 `finally`。
- `gather()` 适合简单聚合，但一个任务失败不保证取消其他任务。
- `TaskGroup` 保证结构化并发，失败时取消兄弟任务，并汇总为 `ExceptionGroup`。
- `Semaphore` 限制同时运行数量，不等于 QPS 限流。
- `asyncio.timeout()` 用取消和异常转换实现超时。
- `shield()` 保护内部任务不被外层取消，但不会让外层任务停止。

---

**验收问题**

1. coroutine 和 Task 的区别是什么？
2. `task.cancel()` 返回 `True`，是否代表任务已经停止？为什么？
3. 一个协程执行纯 CPU 死循环时，调用 `task.cancel()` 为什么可能无效？
4. `TaskGroup` 中一个子任务抛出 `ValueError` 后，其他兄弟任务会发生什么？
5. 为什么 `TaskGroup` 的普通异常通常表现为 `ExceptionGroup`？
6. 项目中的 `Semaphore` 限制了并发数，为什么仍可能创建过多 Task？
7. `asyncio.timeout()` 超时后，当前任务最初收到的是什么异常？最终对外表现为什么异常？
8. 外层任务取消时，`await asyncio.shield(inner_task)` 中的 `inner_task` 会怎样？
9. 为什么 `except Exception` 通常不会捕获 `asyncio.CancelledError`？
10. 项目 `run_bounded_task_group()` 中用 `None` 过滤结果有什么潜在问题？

按编号回答即可，我会逐题批改。

## 用户（原始消息 1832）

1. coroutine 是待执行对象，task 是被事件循环管理的执行单元 2. 不代表，只是代表请求发送成功了，具体的取消依赖事件循环调度。3. 无法取消同步任务 4. 其他兄弟也会被取消 5. 因为taskgroup是结构化并发，本身管理多个子任务，所以需要group的形式来容纳多个错误。6. semaphore 只是限制并发，管不了创建任务的数量， 7. 最初收到 cancelerror 对外是 timeouterror 8. inner_task 会继续执行 9. 因为 cancellederror 是继承自 basedexception 的 ，并不继承于 exception 10. 导致结果顺序不一致。

## 助手（原始消息 1837）

**批改：9/10**

整体掌握得不错。第 10 题答错了，第 3、5 题需要补充精确性。

**1. 正确**

coroutine 是待执行的协程对象，Task 是被事件循环调度和管理的执行单元。

**2. 正确**

`task.cancel()` 返回 `True` 只表示取消请求已提交，不对应“任务已经停止”。真正停止取决于任务是否在挂起点收到并处理 `CancelledError`。

**3. 基本正确，表述需要修正**

不是“无法取消同步任务”，因为 `asyncio.Task` 执行的仍然是协程。更准确地说：

> 该协程一直没有遇到 `await` 等挂起点，事件循环拿不到执行权，因此无法向它注入 `CancelledError`。

例如：

```python
async def worker() -> None:
    while True:
        pass
```

执行：

```python
task = asyncio.create_task(worker())
task.cancel()
```

取消请求已经提交，但 `worker()` 永远不让出事件循环，所以 `cancel()` 无法生效，整个事件循环也会被阻塞。

**4. 正确**

TaskGroup 会取消仍在运行的兄弟任务，并等待它们退出。

**5. 部分正确**

“结构化并发管理多个任务”是对的，但 `ExceptionGroup` 的原因不在于“必须容纳多个错误”。

关键点是：

> TaskGroup 会收集所有子任务的未处理异常，统一包装为 `ExceptionGroup`；即使只有一个子任务失败，也会得到一个只包含一个异常的组。

例如：

```python
try:
    async with asyncio.TaskGroup() as tg:
        tg.create_task(task1())
except* ValueError as group:
    print(group.exceptions)
```

即使只有 `task1()` 抛出 `ValueError`，得到的仍然是：

```text
ExceptionGroup([ValueError(...)])
```

TaskGroup 这样做是为了建立统一的结构化失败边界：

- 一个子任务失败
- 其他子任务被取消
- 所有子任务退出
- 所有未处理异常汇总
- 父级统一处理

多个任务同时失败时，里面就可能包含多个异常。

**6. 正确**

`Semaphore` 控制同时进入临界区的数量，不控制 Task 的数量：

```python
async with asyncio.TaskGroup() as tg:
    for item in items:
        tg.create_task(worker(item))
```

假设有 100 万个 `items` 和 `max_concurrency=3`：

- 仍然是 100 万个 Task
- 同一时刻最多只有 3 个执行 `worker_fn`
- 其余 Task 都在等待 Semaphore

如果任务数量非常大，应使用固定数量的 worker：

```python
async def worker() -> None:
    while True:
        item = await queue.get()
        ...
```

**7. 基本正确**

准确过程是：

1. 超时作用域触发当前任务取消
2. 当前任务收到 `asyncio.CancelledError`
3. `asyncio.timeout()` 判断这是自己的超时导致的取消
4. 将异常转换为内置 `TimeoutError`
5. 对外抛出 `TimeoutError`

注意不是 `cancelerror`，正确名称是 `asyncio.CancelledError`。

**8. 正确**

`inner_task` 会继续执行，因为 `shield()` 阻止取消传播到被保护任务。

但有一个重要边界：外层任务仍然会收到 `CancelledError`，因此还需要保存 `inner_task`，并在合适的地方等待它完成：

```python
try:
    await asyncio.shield(inner_task)
except asyncio.CancelledError:
    await inner_task
    raise
```

否则如果直接丢失 `inner_task` 引用，任务管理和可靠收尾都会变得困难。

**9. 正确**

现代 Python 中：

```python
issubclass(asyncio.CancelledError, BaseException)  # True
issubclass(asyncio.CancelledError, Exception)      # False
```

所以：

```python
except Exception:
    ...
```

不会捕获 `CancelledError`，这是有意设计的，避免普通业务异常处理逻辑误吞取消信号。

**10. 错误**

过滤 `None` 不会导致结果顺序不一致，而是可能导致：

- 结果数量减少
- 合法的 `None` 返回值被丢弃
- 结果与输入无法一一对应

当前代码：

```python
return [r for r in results if r is not None]
```

如果 worker 合法返回 `None`：

```python
async def worker(item: int) -> None:
    ...
```

那么：

```text
输入: [1, 2, 3]
结果槽: [None, "res-2", "res-3"]
返回: ["res-2", "res-3"]
```

第一个输入对应的结果被误删了。

当前代码的位置是：

[C:\work\python\ai-agent-leran\ai-engine\src\ai_engine\core\concurrency.py:29](C:\work\python\ai-agent-leran\ai-engine\src\ai_engine\core\concurrency.py:29)

更稳妥的方式是使用独立哨兵值：

```python
_MISSING = object()
results: list[R | object] = [_MISSING] * len(items)
```

最后检查每个槽位都已经被填充，而不是用 `None` 判断是否完成。

**下一步建议**

进入下一个知识点：**Python 异步迭代协议、`AsyncIterator`、`AsyncGenerator` 与 `async for` 的底层协议**。这会补齐你前面学习 SSE 时留下的一层原理，并且能解释 `__aiter__()`、`__anext__()`、`StopAsyncIteration`、`aclose()` 之间的关系。回复“继续”开始。

## 用户（原始消息 1844）

我突然有点不理解了，taskgroup不是任一任务失败，都会取消其他所有任务吗，为什么还需要收集及多个任务，收集一个不就行了吗？反正其他的都会被取消啊

## 助手（原始消息 1847）

**因为“取消其他任务”不等于“其他任务还没有失败”。**

`TaskGroup` 的确会在发现第一个子任务失败后，尽快取消其他兄弟任务。但取消不是瞬间完成的，也不是原子操作。

时间线可能是这样：

```text
Task A 执行失败：ValueError
Task B 也在同一轮事件循环中失败：KeyError
TaskGroup 还没来得及处理取消
        ↓
两个任务都已经处于 DONE 状态
```

一个已经失败并结束的 Task 无法再被取消。因此 TaskGroup 最终会同时看到：

```python
ExceptionGroup([
    ValueError(...),
    KeyError(...),
])
```

如果只保留第一个异常，另一个真实故障就会丢失。

---

**更关键的是：任务在取消过程中也可能产生新异常**

例如：

```python
async def task_b() -> None:
    try:
        await asyncio.sleep(10)
    finally:
        await close_connection()  # 这里也可能失败
```

当 TaskGroup 取消 `task_b` 后，`task_b` 会进入 `finally` 清理。假设：

```python
finally:
    raise RuntimeError("连接关闭失败")
```

最终可能同时出现：

```text
ExceptionGroup([
    ValueError("任务 A 的业务异常"),
    RuntimeError("任务 B 清理失败"),
])
```

如果只收集第一个异常：

- 原始业务故障可能被保留
- 清理阶段的故障被隐藏
- 日志、告警和排查信息不完整

TaskGroup 的目标是：

> 尽早发起取消，但等所有子任务都退出后，再完整汇报所有未处理异常。

可以概括为：

```text
fail fast：发现失败后尽快取消
wait all：等待所有子任务结束
report all：汇总所有异常
```

---

**还有一个容易忽略的边界：取消依赖 `await` 挂起点**

假设：

```python
async def task_b() -> None:
    while True:
        pass
```

TaskGroup 调用了 `task_b.cancel()`，但 `task_b` 一直没有 `await`，事件循环拿不到执行权，它无法立刻停止。

在它真正停下来之前，可能又发生了其他事情。

再例如：

```python
async def task_b() -> None:
    while True:
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            # 如果这里不重新抛出，还可能继续运行
            continue
```

这种行为虽然错误，但说明 TaskGroup 不能假设 `cancel()` 一调用，其他任务就立刻消失。

---

**如果只有一个任务失败，为什么也返回 `ExceptionGroup`？**

因为 TaskGroup 采用统一的结构化错误边界：不管一个任务失败还是多个任务失败，都把未处理异常放进组中。

只有一个失败时：

```python
ExceptionGroup([
    ValueError("only one error"),
])
```

多个失败时：

```python
ExceptionGroup([
    ValueError(...),
    RuntimeError(...),
])
```

如果有时返回普通异常、有时返回 `ExceptionGroup`，调用方就要写两套处理逻辑。统一成 `ExceptionGroup` 后，使用 `except*` 即可：

```python
try:
    async with asyncio.TaskGroup() as tg:
        ...
except* ValueError as group:
    ...
except* RuntimeError as group:
    ...
```

---

所以你的理解可以修正成这一句：

> TaskGroup 会在第一个普通异常出现后取消其他任务，但其他任务可能已经失败，或者在取消和清理过程中再次失败；因此它要等所有任务结束后，统一收集并报告异常集合。

这也正是 TaskGroup 和简单 `gather()` 的重要区别：前者不仅“取消兄弟任务”，还保证所有兄弟任务完成收尾，并且不隐藏并发故障。

