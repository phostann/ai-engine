# Python 装饰器与异步装饰器

> 本文逐字转录自原始课程对话，只添加角色标题和来源信息，未改写、删减或二次总结。
>
- 返回：[课程原文索引](README.md)
- 原始消息序号：`1937`、`1975`、`1982`、`1987`

## 用户（原始消息 1937）

继续下一部分内容

## 助手（原始消息 1975）

**本课知识点：Python 装饰器与异步装饰器**

装饰器不是 Python 独有的语法，但它在 FastAPI、Pydantic、缓存、重试、权限校验和日志切面中非常常见。

这一课重点不是记住装饰器模板，而是理解：

- 函数本身也是对象
- 闭包如何保存原函数
- `@decorator` 实际做了什么
- 多个装饰器为什么有执行顺序
- 异步装饰器为什么必须 `await`
- 异步生成器为什么不能用普通异步装饰器
- 项目里的 `async_timer`、`async_retry` 有哪些生产风险

---

## 1. 函数是普通对象

Python 中函数可以像变量一样传递：

```python
def greet(name: str) -> str:
    return f"Hello, {name}"


func = greet
print(func("Alice"))
```

函数可以作为参数：

```python
def execute(fn):
    return fn("Alice")


print(execute(greet))
```

也可以作为返回值：

```python
def choose():
    return greet


func = choose()
print(func("Bob"))
```

这是装饰器能够成立的基础。

装饰器本质上就是：

> 接收一个函数，经过包装，再返回一个函数或其他可调用对象。

---

## 2. 最简单的装饰器

```python
import functools
import time


def timer(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        start = time.perf_counter()
        try:
            return func(*args, **kwargs)
        finally:
            cost = time.perf_counter() - start
            print(f"{func.__name__} 耗时 {cost:.4f}s")

    return wrapper
```

使用：

```python
@timer
def calculate_sum(n: int) -> int:
    return sum(range(n))
```

等价于：

```python
def calculate_sum(n: int) -> int:
    return sum(range(n))


calculate_sum = timer(calculate_sum)
```

注意最后一行：原来的 `calculate_sum` 被替换成了 `wrapper`。

所以之后调用：

```python
calculate_sum(100)
```

实际调用的是：

```python
wrapper(100)
```

然后 `wrapper` 内部再调用原来的函数。

---

## 3. 装饰器在什么时候执行

这一点很多人一开始会误解。

```python
@timer
def calculate_sum(n: int) -> int:
    ...
```

`timer(calculate_sum)` 在模块导入、函数定义完成时执行一次，而不是每次调用函数时都重新装饰。

也就是说，程序启动时：

```text
定义原始 calculate_sum
        ↓
timer 接收它
        ↓
创建 wrapper
        ↓
calculate_sum 名字指向 wrapper
```

以后每次调用，执行的是已经创建好的 `wrapper`。

这解释了两个现象。

第一，装饰器内部的初始化代码通常只执行一次：

```python
def decorator(func):
    print("装饰阶段执行一次")

    @functools.wraps(func)
    def wrapper():
        print("每次调用执行")
        return func()

    return wrapper
```

第二，闭包中的可变状态会在多次调用之间共享：

```python
def counter(func):
    count = 0

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        nonlocal count
        count += 1
        print(f"第 {count} 次调用")
        return func(*args, **kwargs)

    return wrapper
```

这个 `count` 属于闭包状态，不在每次调用时重新创建。

---

## 4. 闭包为什么能记住原函数

```python
def timer(func):
    def wrapper():
        return func()

    return wrapper
```

`timer()` 返回后，它的局部作用域按理说已经结束了，但 `wrapper` 仍然可以使用 `func`。

原因是 `wrapper` 形成了闭包，捕获了：

```python
func
```

可以把 `func` 理解成 `wrapper` 的一个隐藏属性。

每次装饰不同函数时，都会创建不同的闭包：

```python
@timer
def func_a():
    ...


@timer
def func_b():
    ...
```

可以近似理解为：

```python
func_a.__closure__ 保存原始 func_a
func_b.__closure__ 保存原始 func_b
```

它们互不影响。

---

## 5. 为什么需要 `functools.wraps`

如果不写：

```python
@functools.wraps(func)
```

装饰后：

```python
@timer
def calculate_sum(n: int) -> int:
    ...
```

函数名可能变成：

```python
print(calculate_sum.__name__)
```

输出：

```text
wrapper
```

这会影响日志、调试、文档、框架路由注册、依赖注入和其他反射机制。

`functools.wraps` 会复制原函数的大量元数据：

- `__name__`
- `__qualname__`
- `__doc__`
- `__module__`
- `__annotations__`
- `__dict__`
- `__wrapped__`

其中 `__wrapped__` 指回原函数，`inspect.signature()` 可以沿着它找到原函数签名。

例如：

```python
import inspect


@timer
def add(a: int, b: int = 0) -> int:
    return a + b


print(inspect.signature(add))
```

虽然实际执行的是 `wrapper(*args, **kwargs)`，但显示出来的仍然可能是：

```python
(a: int, b: int = 0) -> int
```

`functools.wraps` 不会改变实际调用逻辑，它只是保留可观察元数据。

---

## 6. 带参数装饰器

普通装饰器：

```python
@retry
def func():
    ...
```

带参数装饰器：

```python
@retry(max_retries=3, base_delay=0.5)
def func():
    ...
```

这种写法的结构多一层：

```python
def retry(max_retries: int = 3, base_delay: float = 0.5):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            ...
            return func(*args, **kwargs)

        return wrapper

    return decorator
```

调用过程是：

```python
@retry(max_retries=3)
def func():
    ...
```

等价于：

```python
func = retry(max_retries=3)(func)
```

拆开是两步：

```python
configured_decorator = retry(max_retries=3)
func = configured_decorator(func)
```

三个函数层次的职责分别是：

```text
retry(...)        接收装饰器参数
decorator(func)   接收被装饰函数
wrapper(...)      接收原函数调用参数
```

项目中的 `async_retry` 正是这种结构：

[C:\work\python\ai-agent-leran\ai-engine\src\ai_engine\core\decorators.py:30](C:\work\python\ai-agent-leran\ai-engine\src\ai_engine\core\decorators.py:30)

```python
def async_retry(max_retries: int = 3, base_delay: float = 0.5):
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            ...
        return wrapper

    return decorator
```

---

## 7. 多个装饰器的执行顺序

假设：

```python
@A
@B
def func():
    ...
```

等价于：

```python
func = A(B(func))
```

规则是：

> 装饰阶段从下往上应用，调用阶段从外往内执行。

调用时：

```text
A 的 wrapper 先执行
    ↓
B 的 wrapper 执行
    ↓
原始 func 执行
    ↓
B 的 wrapper 后置逻辑
    ↓
A 的 wrapper 后置逻辑
```

项目中：

[C:\work\python\ai-agent-leran\ai-engine\src\ai_engine\services\stream_service.py:8](C:\work\python\ai-agent-leran\ai-engine\src\ai_engine\services\stream_service.py:8)

```python
@async_timer
@async_retry(max_retries=3, base_delay=0.2)
async def check_model_health(...) -> bool:
    ...
```

等价于：

```python
check_model_health = async_timer(
    async_retry(max_retries=3, base_delay=0.2)(
        original_check_model_health
    )
)
```

所以调用过程是：

```text
async_timer 开始计时
        ↓
async_retry wrapper
        ↓
原始 check_model_health
        ↓
失败则 retry wrapper 等待并重试
        ↓
最终成功或失败
        ↓
async_timer 停止计时
```

因此 `async_timer` 统计的是**包含所有重试和退避等待在内的总耗时**。

如果把顺序反过来：

```python
@async_retry(max_retries=3)
@async_timer
async def check_model_health(...):
    ...
```

那么 `async_timer` 在 retry 内层，每次原始调用失败前都会记录一次耗时，而重试之间的等待不算在某一次计时里。

选择顺序取决于你要观测什么。

---

## 8. 同步装饰器和异步装饰器

同步装饰器：

```python
def sync_timer(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        start = time.perf_counter()
        try:
            return func(*args, **kwargs)
        finally:
            print(time.perf_counter() - start)

    return wrapper
```

如果把它用于异步函数：

```python
@sync_timer
async def fetch_data():
    await asyncio.sleep(1)
```

调用：

```python
coro = fetch_data()
```

`sync_timer` 的 `wrapper` 会执行：

```python
return func(*args, **kwargs)
```

这里返回的是 coroutine 对象，并没有执行里面的 `await`。

所以计时器马上结束，打印的耗时接近 `0`，真正的异步工作还未完成。

要正确统计异步函数：

```python
def async_timer(func):
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        start = time.perf_counter()
        try:
            return await func(*args, **kwargs)
        finally:
            print(time.perf_counter() - start)

    return wrapper
```

核心是：

1. `wrapper` 必须是 `async def`
2. 必须 `await func(...)`
3. 这样计时才覆盖协程真正执行的时间

项目的 `async_timer` 正是这样：

[C:\work\python\ai-agent-leran\ai-engine\src\ai_engine\core\decorators.py:18](C:\work\python\ai-agent-leran\ai-engine\src\ai_engine\core\decorators.py:18)

```python
async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
    start_time = time.perf_counter()
    try:
        return await func(*args, **kwargs)
    finally:
        ...
```

---

## 9. `await func()` 的前提

装饰器的类型约束写的是：

```python
Callable[P, Coroutine[Any, Any, R]]
```

含义是被装饰函数必须返回 coroutine。

普通异步函数满足：

```python
async def fetch_data() -> str:
    return "data"
```

调用：

```python
coro = fetch_data()
```

得到 coroutine，可以：

```python
result = await coro
```

但异步生成器不满足：

```python
async def stream_tokens() -> AsyncGenerator[str, None]:
    yield "A"
```

调用：

```python
gen = stream_tokens()
```

得到的是 async generator，不是 coroutine。

因此下面会失败：

```python
await func(...)
```

可能报：

```text
TypeError: object async_generator can't be used in 'await' expression
```

这就是上一课最后提到的装饰器边界。

---

## 10. 如何正确装饰异步生成器

假设有一个异步流：

```python
async def token_stream():
    yield "A"
    yield "B"
```

要给整个流计时，包装器本身也必须是异步生成器：

```python
from contextlib import aclosing


def async_generator_timer(func):
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        start = time.perf_counter()

        try:
            async with aclosing(func(*args, **kwargs)) as stream:
                async for item in stream:
                    yield item
        finally:
            cost = time.perf_counter() - start
            print(f"{func.__name__} 流式耗时 {cost:.4f}s")

    return wrapper
```

这个 `wrapper` 包含 `yield`，所以它是异步生成器函数。

调用：

```python
@async_generator_timer
async def token_stream():
    yield "A"
    yield "B"
```

之后仍然可以：

```python
async for token in token_stream():
    print(token)
```

几个关键点：

- 包装器必须保留异步生成器协议
- 不能只 `return await func(...)`
- 消费者提前 `break` 时，外层 `wrapper` 会被 `aclose()`
- 使用 `aclosing()` 确保内层生成器也被关闭
- `finally` 能覆盖正常完成、异常和提前关闭三种情况

---

## 11. 为什么不建议盲目重试异步生成器

项目中的 `async_retry` 适合普通异步请求函数：

```python
async def check_model_health(...) -> bool:
    ...
```

它只有一个最终结果，成功或失败。

但流式生成器可能已经输出了：

```text
你好
我是
AI
```

然后上游连接断开了。

如果装饰器简单重试整个流式调用，客户端可能收到：

```text
你好
我是
AI
你好
我是
AI
...
```

出现重复内容。

所以流式请求的重试边界要非常清楚：

- 还没向客户端发送任何 token：可以重试建立上游连接
- 已经发送部分 token：通常不能透明重试整个流
- 已经发送部分 token 后失败：应发送 SSE `error` 事件或中断连接

重试不是装饰器套上去就正确，必须结合业务幂等性和副作用边界。

---

## 12. 当前 `async_retry` 的潜在问题

项目代码：

[C:\work\python\ai-agent-leran\ai-engine\src\ai_engine\core\decorators.py:43](C:\work\python\ai-agent-leran\ai-engine\src\ai_engine\core\decorators.py:43)

```python
except Exception as exc:
```

这会捕获几乎所有业务异常，包括：

- `ValueError`
- `TypeError`
- `ValidationError`
- `KeyError`
- `RuntimeError`
- 业务代码 bug

但很多异常重试没有意义：

- 参数校验失败
- API Key 错误
- 权限不足
- 请求格式错误
- 代码本身的 `TypeError`

生产级重试通常只处理：

- 连接超时
- 读超时
- 临时网络错误
- 429
- 500、502、503、504
- 明确的临时服务不可用错误

同时还要考虑：

- 操作是否幂等
- 是否遵守 `Retry-After`
- 指数退避是否带随机抖动
- 是否有总超时
- 是否记录尝试次数
- 是否区分客户端错误和服务端错误

另外，`except Exception` 不会捕获 `CancelledError`，这是好事。

如果装饰器写成：

```python
except BaseException:
    ...
```

就可能把取消信号也捕获，必须避免。

---

## 13. `max_retries` 的名称与含义

当前代码：

```python
for attempt in range(1, max_retries + 1):
```

如果：

```python
max_retries=3
```

实际是总共尝试 3 次：

```text
第 1 次原始调用
第 2 次重试
第 3 次重试
```

严格来说：

```text
max_retries = 3
```

通常意味着原始调用 1 次，加 3 次重试，总共 4 次。

因此这个参数更准确的名称可能是：

```python
max_attempts = 3
```

或者循环逻辑改为：

```python
for attempt in range(max_retries + 1):
```

这是 API 命名和边界含义的问题。

---

## 14. `ParamSpec` 和 `TypeVar`

项目使用：

```python
def async_timer[**P, R](
    func: Callable[P, Coroutine[Any, Any, R]],
) -> Callable[P, Coroutine[Any, Any, R]]:
```

这是 Python 3.12 的泛型语法。

`ParamSpec` 表示参数列表：

```python
P = ParamSpec("P")
```

它让装饰器保留原函数的参数类型。

例如：

```python
@async_timer
async def fetch_user(user_id: int, *, include_orders: bool = False) -> User:
    ...
```

类型检查器仍然知道调用方式是：

```python
await fetch_user(123, include_orders=True)
```

而不是只知道：

```python
wrapper(*args, **kwargs)
```

`TypeVar` 表示返回类型：

```python
R = TypeVar("R")
```

因此：

```python
Callable[P, Coroutine[Any, Any, R]]
```

可以理解为：

- 接受任意参数列表 `P`
- 返回一个异步协程
- 协程最终结果是 `R`

项目同时在第 8、9 行定义了：

```python
P = ParamSpec("P")
R = TypeVar("R")
```

但函数第 12 行又使用了 PEP 695 的内联类型参数：

```python
def async_timer[**P, R](...)
```

这两套写法在概念上重复。既然使用了 `def async_timer[**P, R]`，模块级的 `P`、`R` 通常可以删除。

---

## 15. 装饰器不只用于“包装函数”

装饰器有多种用途。

**包装型装饰器**

例如：

```python
@timer
@retry
@lru_cache
```

它们会把函数替换成包装后的函数或缓存对象。

项目配置：

[C:\work\python\ai-agent-leran\ai-engine\src\ai_engine\core\config.py:37](C:\work\python\ai-agent-leran\ai-engine\src\ai_engine\core\config.py:37)

```python
@lru_cache
def get_settings() -> Settings:
    return Settings()
```

`get_settings` 被替换成带缓存能力的包装函数。

**注册型装饰器**

例如 FastAPI：

```python
@router.post("/chat")
async def chat():
    ...
```

它主要作用是告诉路由器：

> 这个函数应该处理某个 POST 路径。

它不一定像普通包装器那样替换函数。

**描述符型装饰器**

例如：

```python
@property
@staticmethod
@classmethod
```

它们会把函数转换成描述符对象。

因此看到 `@xxx` 时，不要默认理解成“就是包一层 wrapper”，需要看具体装饰器返回了什么。

---

## 16. `@asynccontextmanager` 也是装饰器

前面学过的：

```python
@asynccontextmanager
async def lifespan(app):
    ...
    yield
    ...
```

本质上是：

```python
lifespan = asynccontextmanager(lifespan)
```

它把一个只 `yield` 一次的异步生成器包装成异步上下文管理器工厂。

原来的异步生成器仍然存在，但 `asynccontextmanager` 给它增加了：

```python
__aenter__
__aexit__
```

所以可以用于：

```python
async with lifespan(app):
    ...
```

这正好把前面两组知识连接起来：

- 异步生成器
- 装饰器
- 异步上下文管理器
- FastAPI lifespan

---

## 本课核心结论

- 函数是对象，可以作为参数和返回值，这是装饰器的基础。
- `@decorator` 在函数定义时执行，不是每次调用时执行。
- 闭包让包装函数记住原函数和装饰器参数。
- 多装饰器应用顺序从下往上，调用顺序从外往内。
- `functools.wraps` 保留名称、文档、注解和 `__wrapped__`。
- 带参数装饰器比普通装饰器多一层函数。
- 异步函数必须由异步 wrapper 执行 `await`。
- 异步生成器必须由异步生成器 wrapper 通过 `async for` 消费。
- 流式输出已经发送部分数据后，不应盲目整体重试。
- `except Exception` 粒度太宽，重试必须限定在可重试异常上。

---

**验收问题**

1. `@decorator` 应用到函数 `func` 后，等价赋值是什么？
2. 装饰器的“应用阶段”是在每次函数调用时，还是在函数定义时？
3. 闭包为什么能让 `wrapper` 记住原函数和装饰器参数？
4. 多个装饰器 `@A`、`@B` 按什么顺序应用、按什么顺序执行？
5. `functools.wraps` 至少保留哪三类信息？
6. 带参数装饰器为什么要多一层函数？
7. 同步 wrapper 包异步函数时，为什么计时可能接近 0？
8. 项目中的 `async_timer` 为什么不能直接装饰 `stream_llm_tokens()`？
9. 装饰流式异步生成器时，包装器应该使用 `await` 还是 `async for`？为什么？
10. 项目 `async_retry` 捕获所有 `Exception` 有什么风险？为什么它不会捕获 `CancelledError`？

按编号回答即可，我会逐题批改。

## 用户（原始消息 1982）

1. 等价赋值是 decorated = decorator(func) 2. 在函数定义时，以及模块导入时执行一次 3. 原函数和装饰器参数就相当于闭包的局部变量了，自然能记住 4. 按照从上到下的应用顺序 先应用 A 再应用 B ，执行按照从外向内，先执行B 再执行 A 5. 保留函数签名 6. 为了形成闭包，记住装饰器参数 7. 因为内部没有 await 被包装的异步函数。 8. 因为 stream_llm_tokens 是异步生成器，如果装饰器要装饰他，需要内部使用  async for 然后把值 yield 出来 9. 使用 async for ，它是异步生成器又不是 coroutine  10. 捕获所有 Exception 可能会导致不能正确处理异常，并且漏捕获 CalcelledError 导致清理工作无法执行 ，CancelledError 是继承子 BaseExcetion 所以 Exception 捕获不到

## 助手（原始消息 1987）

**批改：7.5/10**

第 2、3、6、7、8、9 题基本正确。第 4 题把装饰器顺序理解反了；第 1、5、10 题需要补充精确性。

**1. 基本正确，但名字要说准**

```python
@decorator
def func():
    ...
```

严格等价于：

```python
def func():
    ...

func = decorator(func)
```

不是创建一个叫 `decorated` 的新名字，而是把原来的 `func` 这个名字重新绑定到装饰器返回的新对象上。

所以：

```python
@decorator
def func():
    ...
```

之后你调用 `func()`，实际调用的是 `decorator` 返回的 wrapper。

**2. 正确**

装饰器在函数定义完成时执行一次。通常就是模块导入时执行一次。

严格来说，模块被 `importlib.reload()` 重新加载时，函数会重新定义，装饰器也会再次执行。

**3. 基本正确**

更准确的术语是：

> `func` 和装饰器参数是被 `wrapper` 捕获的自由变量，保存在闭包单元中。

它们不是 `wrapper` 自己的局部变量，而是来自外层函数作用域：

```python
def retry(max_retries):
    def decorator(func):
        async def wrapper(...):
            # max_retries 和 func 都是自由变量
            ...
        return wrapper
    return decorator
```

**4. 错误：应用顺序和执行顺序都说反了**

对于：

```python
@A
@B
def func():
    ...
```

严格等价于：

```python
func = A(B(func))
```

因此应用顺序是：

```text
先应用 B 到原始 func
再应用 A 到 B 返回的 wrapper
```

调用顺序是：

```text
A wrapper 先进入
    ↓
B wrapper 进入
    ↓
原始 func 执行
    ↓
B wrapper 后置逻辑
    ↓
A wrapper 后置逻辑
```

也就是：

> 装饰阶段从下往上，调用阶段从外往内。

项目中的：

```python
@async_timer
@async_retry(max_retries=3, base_delay=0.2)
async def check_model_health(...):
    ...
```

等价于：

```python
check_model_health = async_timer(
    async_retry(max_retries=3, base_delay=0.2)(
        original_check_model_health
    )
)
```

所以最外层是 `async_timer`，调用时先开始计时，再进入 retry 包装器，最后调用原始函数。

**5. 不完整**

`functools.wraps` 主要保留：

- `__name__`
- `__qualname__`
- `__doc__`
- `__module__`
- `__annotations__`
- `__dict__`
- `__wrapped__`

它并不是真的改变了 wrapper 的实际参数列表。实际函数仍然是：

```python
def wrapper(*args, **kwargs):
    ...
```

但 `__wrapped__` 指向原函数，所以：

```python
inspect.signature(decorated_func)
```

通常会沿着 `__wrapped__` 找到原函数签名。

因此更准确的说法是：

> `functools.wraps` 保留函数元数据，并让反射工具能够找到原函数；它不是运行时强制恢复参数签名。

**6. 正确**

带参数装饰器需要先接收配置：

```python
@retry(max_retries=3)
```

第一步执行：

```python
configured_decorator = retry(max_retries=3)
```

第二步才把函数传进去：

```python
func = configured_decorator(func)
```

所以需要：

```text
retry(...)       接收配置
decorator(func)  接收函数
wrapper(...)     接收函数调用参数
```

**7. 正确**

同步 wrapper：

```python
def wrapper(*args, **kwargs):
    start = time.perf_counter()
    result = func(*args, **kwargs)
    print(time.perf_counter() - start)
    return result
```

如果 `func` 是异步函数，`func()` 只创建 coroutine，不会执行协程体，所以计时会很快结束。

正确方式：

```python
async def wrapper(*args, **kwargs):
    start = time.perf_counter()
    try:
        return await func(*args, **kwargs)
    finally:
        print(time.perf_counter() - start)
```

**8. 正确**

`stream_llm_tokens()` 返回异步生成器，不是 coroutine。

`async_timer` 内部是：

```python
await func(*args, **kwargs)
```

对异步生成器执行 `await` 会报类似：

```text
TypeError: object async_generator can't be used in 'await' expression
```

**9. 正确**

装饰异步生成器时，wrapper 也必须是异步生成器：

```python
def decorator(func):
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        async for item in func(*args, **kwargs):
            yield item

    return wrapper
```

因为这里出现了 `yield`，`wrapper` 本身也变成了异步生成器函数。

如果还要确保内层流被关闭，应加上：

```python
async with aclosing(func(*args, **kwargs)) as stream:
    async for item in stream:
        yield item
```

**10. 结论大体正确，但最后一句有矛盾**

你前面说“漏捕获 `CancelledError`”，后面又说“`Exception` 捕获不到它”。正确的是后者。

`CancelledError` 继承自 `BaseException`，所以：

```python
except Exception:
    ...
```

不会捕获它。这是设计上的正确行为，不是“漏捕获”。

如果改成：

```python
except BaseException:
    ...
```

反而可能把取消信号吞掉，导致任务无法正常停止。

项目 `async_retry` 的主要风险是：

- 对参数错误、401、403、422 等不可恢复错误进行无意义重试
- 对代码 bug 进行重试
- 对非幂等操作进行重试，可能重复扣款、重复创建资源
- 没有区分临时网络错误和业务错误
- 流式接口已经输出部分 token 后，重试可能造成重复内容

宽泛的 `except Exception` 不一定是错的。例如在 HTTP 请求最外层，可以用它记录日志并转换成 500 响应。但它不适合作为“所有异常都重试”的判断条件。

**本课小结**

你需要再巩固的核心是：

```text
@A
@B
def f():
    ...
```

等于：

```python
f = A(B(f))
```

应用时从下往上，执行时从外往内。

下一步建议学习：**Python 异常体系与错误边界**，包括 `Exception`、`BaseException`、异常链、`raise from`、自定义异常、`ExceptionGroup`，以及哪些错误应该重试、哪些应该直接返回给客户端。回复“继续”开始。

