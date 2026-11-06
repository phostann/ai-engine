# Python 异常体系与错误边界

> 本文逐字转录自原始课程对话，只添加角色标题和来源信息，未改写、删减或二次总结。
>
- 返回：[课程原文索引](README.md)
- 原始消息序号：`1995`、`2029`、`2036`、`2041`、`2048`、`2091`

## 用户（原始消息 1995）

继续下一课

## 助手（原始消息 2029）

**本课知识点：Python 异常体系与错误边界**

异常处理的核心不是“多写几个 `except`”，而是回答三个问题：

1. 这个错误应该由谁处理？
2. 这个错误应该转换成什么对外结果？
3. 这个错误是否应该重试？

很多生产事故不是因为没有捕获异常，而是因为捕获位置错误、异常类型太宽，或者把不可恢复错误错误地重试了。

---

## 1. `BaseException` 与 `Exception`

Python 异常体系的顶层是：

```text
BaseException
├── SystemExit
├── KeyboardInterrupt
├── GeneratorExit
├── asyncio.CancelledError
└── Exception
    ├── ValueError
    ├── TypeError
    ├── RuntimeError
    ├── OSError
    ├── httpx.HTTPError
    ├── pydantic.ValidationError
    └── ...
```

普通业务异常都应该继承 `Exception`：

```python
class BudgetExceeded(Exception):
    pass
```

不应该随意继承 `BaseException`。

### 为什么不能随便捕获 `BaseException`

```python
try:
    await task()
except BaseException:
    print("全部吃掉")
```

这会把以下控制信号也吞掉：

- `KeyboardInterrupt`：用户按 `Ctrl+C`
- `SystemExit`：进程准备退出
- `asyncio.CancelledError`：任务取消
- `GeneratorExit`：生成器关闭

结果是程序可能无法停止、任务无法取消、资源清理被破坏。

所以一般业务代码只捕获：

```python
except Exception:
    ...
```

但即使在 `Exception` 范围内，也不能看到异常就重试，后面会讲。

### `CancelledError` 的特殊性

现代 Python 中：

```python
issubclass(asyncio.CancelledError, Exception)  # False
issubclass(asyncio.CancelledError, BaseException)  # True
```

因此：

```python
except Exception:
    ...
```

不会捕获任务取消。

这是正确行为。取消信号应该继续向上传播：

```python
except asyncio.CancelledError:
    logger.info("任务被取消")
    raise
```

或者：

```python
try:
    ...
finally:
    await cleanup()
```

---

## 2. `try`、`except`、`else`、`finally`

完整结构：

```python
try:
    response = await request_upstream()
except TimeoutError:
    logger.warning("上游超时")
    raise
except ValueError:
    logger.warning("响应格式错误")
    raise
else:
    return response
finally:
    logger.info("请求处理结束")
```

各块含义：

| 代码块 | 何时执行 |
|---|---|
| `try` | 总是执行 |
| `except` | `try` 中对应异常出现时 |
| `else` | `try` 没有异常时 |
| `finally` | 无论成功、异常、`return` 都会执行 |

`else` 的价值是避免捕获到不该捕获的异常。

例如：

```python
try:
    data = parse_response(response)
except ValueError:
    ...
else:
    return process_data(data)
```

如果 `process_data()` 内部也抛出 `ValueError`，它不会被上面的 `except` 捕获，因为 `else` 中的异常不属于 `try` 块。

### `finally` 中的 `return` 很危险

```python
def func():
    try:
        raise ValueError("原始错误")
    finally:
        return "finally 返回值"
```

最终 `func()` 返回：

```text
finally 返回值
```

原始异常被 `finally` 的 `return` 吞掉了。

同理，`finally` 中再抛新异常，可能覆盖原始异常：

```python
finally:
    raise RuntimeError("清理失败")
```

这会掩盖真正的原始错误。所以 `finally` 应该只做清理和记录，不要随便 `return` 或抛出新异常。

---

## 3. 异常匹配顺序

```python
try:
    do_something()
except Exception:
    print("通用异常")
except ValueError:
    print("值错误")
```

第二个 `except` 永远不可达，因为 `ValueError` 已经先被 `Exception` 捕获。

必须从具体到宽泛：

```python
try:
    do_something()
except ValueError:
    ...
except Exception:
    ...
```

这和多态匹配一样，前面的父类会截获子类。

---

## 4. 裸 `raise` 与 `raise exc`

在 `except` 中：

```python
except ValueError as exc:
    logger.warning("值错误: %s", exc)
    raise
```

这里的裸 `raise` 会重新抛出当前异常，并保留完整 traceback。

对比：

```python
except ValueError as exc:
    raise exc
```

`raise exc` 也会抛出这个异常，但会增加当前 `raise` 位置的 traceback 帧，通常不如裸 `raise` 清晰。

所以“记录后继续抛”的标准写法是：

```python
except Exception:
    logger.exception("处理失败")
    raise
```

---

## 5. 异常链：`raise ... from ...`

假设底层抛出了：

```python
httpx.ReadTimeout("读取上游响应超时")
```

我们希望在业务层抛出更明确的异常：

```python
class UpstreamTimeout(Exception):
    pass
```

可以写：

```python
try:
    response = await client.get("/chat")
except httpx.TimeoutException as exc:
    raise UpstreamTimeout("模型服务响应超时") from exc
```

这会保留异常链：

```text
UpstreamTimeout: 模型服务响应超时
The above exception was the direct cause of the following exception:
httpx.ReadTimeout: 读取上游响应超时
```

原始错误在：

```python
exc.__cause__
```

新异常在：

```python
new_exc.__context__
```

因此日志和调试时不会丢失根因。

如果写：

```python
raise UpstreamTimeout("模型服务响应超时") from None
```

就会隐藏原始异常链。除非你明确不希望暴露底层细节，否则内部日志一般应保留 `from exc`。

### 什么时候使用 `from`

推荐模式：

```python
except httpx.TimeoutException as exc:
    raise UpstreamTimeout(...) from exc
```

业务异常表示上层语义，底层异常表示技术原因。

---

## 6. 自定义异常

不要所有地方都抛：

```python
raise ValueError("Token 超限")
```

因为 `ValueError` 太宽泛，调用方无法区分：

- Token 预算超限
- JSON 解析失败
- 数字转换失败
- 某个参数格式错误

项目中当前是：

[C:\work\python\ai-agent-leran\ai-engine\src\ai_engine\core\tokenizer.py:41](C:\work\python\ai-agent-leran\ai-engine\src\ai_engine\core\tokenizer.py:41)

```python
class TokenBudgetGuard:
    ...
```

预算校验建议定义专用异常：

```python
class TokenBudgetExceeded(Exception):
    def __init__(
        self,
        prompt_tokens: int,
        max_completion_tokens: int,
        max_context_limit: int,
    ) -> None:
        self.prompt_tokens = prompt_tokens
        self.max_completion_tokens = max_completion_tokens
        self.max_context_limit = max_context_limit

        super().__init__(
            f"上下文 Token 超限: "
            f"{prompt_tokens} + {max_completion_tokens} > {max_context_limit}"
        )
```

然后抛出：

```python
raise TokenBudgetExceeded(
    prompt_tokens=prompt_tokens,
    max_completion_tokens=max_completion_tokens,
    max_context_limit=self.max_context_limit,
)
```

调用方就能精确处理：

```python
except TokenBudgetExceeded as exc:
    ...
```

而不是捕获所有 `ValueError`。

### 自定义异常应该带什么信息

通常包含：

- 稳定的错误码
- 面向用户的简短消息
- 面向日志的详细信息
- 可选的 HTTP 状态码
- 是否可重试
- 相关字段位置

例如：

```python
class AppError(Exception):
    code: str
    retryable: bool = False

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class TokenBudgetExceeded(AppError):
    code = "TOKEN_BUDGET_EXCEEDED"
    retryable = False


class UpstreamUnavailable(AppError):
    code = "UPSTREAM_UNAVAILABLE"
    retryable = True
```

生产系统不应该靠匹配错误字符串判断类型：

```python
if "超限" in str(exc):
    ...
```

这是脆弱的。应该依赖异常类或稳定错误码。

---

## 7. 当前项目中的错误边界

一个后端服务的错误大致分布在几个边界：

```text
HTTP 请求边界
    ↓
认证、参数校验边界
    ↓
业务规则边界
    ↓
数据库、缓存、上游服务边界
    ↓
响应序列化边界
```

### 请求参数错误

请求体不合法时，FastAPI/Pydantic 通常返回 `422`：

```json
{
  "detail": [
    {
      "type": "string_too_short",
      "loc": ["body", "prompt"],
      "msg": "String should have at least 1 character"
    }
  ]
}
```

这类错误不应该被包装成 `500`。

- `400`：请求格式或业务参数有问题
- `422`：字段结构、类型、约束校验失败
- `401`：未认证
- `403`：已认证但无权限
- `404`：资源不存在
- `409`：资源状态冲突
- `429`：被限流

### 依赖未初始化

项目依赖代码：

[C:\work\python\ai-agent-leran\ai-engine\src\ai_engine\api\deps.py:33](C:\work\python\ai-agent-leran\ai-engine\src\ai_engine\api\deps.py:33)

```python
if client is None:
    raise HTTPException(
        status_code=500,
        detail="NativeLLMClient 尚未在 lifespan 中初始化",
    )
```

这里使用 `HTTPException` 是合适的，因为它是 FastAPI 能识别的 API 错误。

不过从语义上看，依赖尚未就绪有时更像：

```python
status.HTTP_503_SERVICE_UNAVAILABLE
```

具体使用 `500` 还是 `503`，取决于这是部署初始化错误还是临时服务不可用。

### 上游服务错误

调用大模型时可能出现：

- 连接超时
- 读取超时
- 网络断开
- DNS 解析失败
- 429 限流
- 500/502/503/504
- 响应不是合法 JSON
- SSE 数据格式错误

这些错误的处理方式不同：

```text
连接失败、临时网络错误       → 可能重试
429                         → 遵守 Retry-After 后重试
502/503/504                 → 视幂等性重试
401/403                     → 不重试，检查凭据
400/422                     → 不重试，修复请求
JSON 解析失败               → 可能转 502，不应无限重试
```

项目 HTTP 客户端：

[C:\work\python\ai-agent-leran\ai-engine\src\ai_engine\core\http_client.py:60](C:\work\python\ai-agent-leran\ai-engine\src\ai_engine\core\http_client.py:60)

定义了：

```python
retryable_codes = {429, 500, 502, 503, 504}
```

并且对：

```python
except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError)
```

做区分。

这个方向是对的：不是所有异常都重试，而是识别临时网络错误和可重试状态码。

---

## 8. 项目 `chat.py` 中的异常边界问题

当前代码：

[C:\work\python\ai-agent-leran\ai-engine\src\ai_engine\api\v1\chat.py:70](C:\work\python\ai-agent-leran\ai-engine\src\ai_engine\api\v1\chat.py:70)

```python
except ValueError as val_err:
    logger.error(f"Token 预算拦截失败: {val_err}")
    yield {
        "event": "error",
        "data": json.dumps({"code": 40001, "message": str(val_err)}),
    }
```

这里有两个潜在问题。

### 问题一：`ValueError` 太宽泛

任何 `ValueError` 都会被解释成 Token 预算错误，例如：

- JSON 解析失败
- 字段转换失败
- 第三方库内部使用了 `ValueError`
- 代码其他位置使用了 `ValueError`

如果这些错误被误报成“Token 预算超限”，前端和用户会收到错误提示，日志也会误导排查。

更合理的是：

```python
except TokenBudgetExceeded as exc:
    ...
```

而不是捕获所有 `ValueError`。

### 问题二：把所有未知异常说成“上游抖动”

```python
except Exception as exc:
    logger.exception(...)
    yield {
        "event": "error",
        "data": json.dumps(
            {"code": 50000, "message": "网关上游推理服务发生抖动，请稍后重试"}
        ),
    }
```

这可能掩盖代码 bug。

例如程序内部出现：

```python
AttributeError("NoneType has no attribute get")
```

它并不是上游抖动，而是本地代码错误。

更合理的边界是：

```python
except (httpx.TimeoutException, httpx.NetworkError) as exc:
    yield upstream_error_frame(...)
except httpx.HTTPStatusError as exc:
    ...
except Exception:
    logger.exception("网关内部未知错误")
    yield internal_error_frame(...)
```

注意：已进入 SSE 流式响应后，通常已经发送了：

```http
HTTP/1.1 200 OK
Content-Type: text/event-stream
```

此时不能再把 HTTP 状态码改成 `500`，只能通过 SSE 的 `error` 事件告诉客户端：

```text
event: error
data: {"code":"INTERNAL_ERROR","message":"服务内部错误"}
```

这不是 HTTP 层面的错误，而是流协议层面的错误事件。

---

## 9. `HTTPException` 和普通异常

FastAPI 中：

```python
from fastapi import HTTPException

raise HTTPException(
    status_code=404,
    detail="会话不存在",
)
```

适合表示：

> 这是一个预期的 API 错误，框架应该将它转换成对应的 HTTP 响应。

普通异常：

```python
raise ValueError("内部数据格式错误")
```

适合表示程序内部错误，需要由更上层转换成合适的 API 响应。

不要在很深的数据层直接写：

```python
raise HTTPException(400, "参数错误")
```

这样会把 HTTP 概念渗透到业务层，导致：

- 单元测试必须依赖 FastAPI
- 非 HTTP 调用方无法复用业务逻辑
- 业务层和 Web 框架强耦合

更好的分层是：

```text
业务层抛出 TokenBudgetExceeded
        ↓
API 层捕获并转换成 HTTPException 或 SSE error 事件
```

---

## 10. FastAPI 全局异常处理器

可以针对特定异常注册处理器：

```python
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


@app.exception_handler(TokenBudgetExceeded)
async def token_budget_handler(
    request: Request,
    exc: TokenBudgetExceeded,
) -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content={
            "code": "TOKEN_BUDGET_EXCEEDED",
            "message": str(exc),
        },
    )
```

这样业务代码只负责抛异常，HTTP 映射集中在 API 层。

但流式响应要特别注意：

- 如果 SSE 还没开始发送，可以由异常处理器生成 HTTP 错误响应
- 如果 SSE 已经发送了第一帧，HTTP 状态码已经是 200
- 之后只能发送 SSE `error` 事件

所以流式接口不能在生成器内部依赖普通 `HTTPException` 自动变成 `500`。

---

## 11. `ExceptionGroup` 与 `except*`

TaskGroup 会抛：

```python
ExceptionGroup([
    TimeoutError(...),
    ValueError(...),
])
```

普通 `except` 只能处理整个组：

```python
try:
    await run_tasks()
except ExceptionGroup as group:
    logger.exception("多个任务失败", exc_info=group)
```

想按子异常类型分别处理，使用：

```python
try:
    await run_tasks()
except* TimeoutError:
    logger.warning("部分任务超时")
except* ValueError:
    logger.error("部分任务参数错误")
```

`except*` 会拆分异常组。

注意：

- `ExceptionGroup` 可以嵌套
- 匹配到其中一部分后，未处理的异常可能继续传播
- 不要为了“清空错误”而捕获后什么也不做

---

## 12. `finally` 与异步清理

```python
async def request_scope() -> None:
    resource = await acquire()
    try:
        await use(resource)
    finally:
        await release(resource)
```

无论：

- 正常完成
- 中途 `return`
- 抛出业务异常
- 任务被取消
- 生成器被关闭

`finally` 通常都会进入。

但要注意：

- `finally` 中的 `await` 也可能被第二次取消
- 关键清理可以使用 `asyncio.shield`
- 清理代码应尽量短，不要无限等待
- `GeneratorExit` 不是普通异常，不能依赖 `except Exception` 捕获

项目中的流式结算：

[C:\work\python\ai-agent-leran\ai-engine\src\ai_engine\services\stream_service.py:52](C:\work\python\ai-agent-leran\ai-engine\src\ai_engine\services\stream_service.py:52)

```python
finally:
    print(f"本次流式会话共吐出 {generated_count} 个 Token 块")
```

就是对正常结束、异常、取消和生成器关闭的统一收尾点。

---

## 13. `assert` 不是业务异常处理

```python
assert last_error is not None
```

这个断言只是内部不变量检查。

因为 Python 使用优化模式运行时：

```bash
python -O
```

断言会被移除。

所以不能用 `assert` 做：

```python
assert user.is_authenticated
```

也不能用：

```python
assert prompt is not None
```

用户输入、权限、配置校验都应该显式抛异常：

```python
if not user.is_authenticated:
    raise AuthenticationRequired(...)
```

---

## 14. 一个推荐的异常处理流程

```python
class AppError(Exception):
    code = "APP_ERROR"
    retryable = False


class BudgetExceeded(AppError):
    code = "BUDGET_EXCEEDED"


class UpstreamUnavailable(AppError):
    code = "UPSTREAM_UNAVAILABLE"
    retryable = True
```

请求处理：

```python
try:
    response = await call_upstream()
except httpx.TimeoutException as exc:
    raise UpstreamUnavailable("上游服务超时") from exc
except httpx.HTTPStatusError as exc:
    if exc.response.status_code == 401:
        raise AppError("上游凭据无效") from exc
    raise UpstreamUnavailable("上游服务异常") from exc
except Exception:
    logger.exception("未预期的内部错误")
    raise
```

API 边界：

```python
except BudgetExceeded as exc:
    raise HTTPException(400, detail=exc.message) from exc
except UpstreamUnavailable as exc:
    raise HTTPException(503, detail=exc.message) from exc
except Exception:
    logger.exception("未知服务错误")
    raise
```

核心原则：

```text
底层异常保留细节
业务层转换成语义明确的异常
API 层转换成 HTTP 或 SSE 错误
未知异常记录完整 traceback
不要把内部堆栈和密钥返回给客户端
```

---

**本课核心结论**

- 业务异常通常继承 `Exception`，不要随便继承 `BaseException`。
- `CancelledError`、`GeneratorExit` 是控制信号，不是普通业务错误。
- `finally` 适合清理，不应通过 `return` 吞掉异常。
- 异常处理要从具体类型到宽泛类型。
- 用 `raise ... from exc` 保留根因链。
- 用自定义异常和稳定错误码代替宽泛 `ValueError`。
- 可重试错误应限制在超时、网络错误、429 和部分 5xx。
- SSE 已经发送响应头后，只能发送错误事件，不能再改 HTTP 状态码。
- 未知异常要记录堆栈，但不能把内部细节泄露给客户端。

---

**验收问题**

1. `Exception` 和 `BaseException` 的继承关系是什么？哪些常见异常不属于 `Exception`？
2. `try/except/else/finally` 中，`else` 和 `finally` 分别什么时候执行？
3. 为什么 `finally` 中的 `return` 很危险？
4. `raise` 和 `raise exc` 的主要区别是什么？
5. `raise NewError(...) from exc` 的作用是什么？什么时候用 `from None`？
6. 为什么项目里用 `except ValueError` 表示 Token 超限不够精确？
7. 哪些 HTTP 状态码和网络异常通常适合重试？
8. 为什么流式响应已经开始后，不能依赖普通 FastAPI 异常处理器改成 500？
9. `HTTPException` 应该在哪一层使用？为什么不应该在数据访问层直接抛？
10. `ExceptionGroup` 和 `except*` 分别解决什么问题？

按编号回答即可，我会逐题批改。

## 用户（原始消息 2036）

1. Exception 继承自 BaseException，CancelledError 不属于Exception 2. else 在 try语句中没有抛出异常的时候执行 finally 始终都会执行 3. finally 中的 return 会覆盖 exception 中的 异常，所以很危险，也会覆盖 try 中正常 return 的值 4. raise 是将原始的错误抛出，raise exc 会带上当前堆栈信息  5. 作用是保留原始错误堆栈，方便排查 6. 太过宽泛，未必是 token 超限引起的 valueerror 7. 429 和部分 500 8. 流式响应第一帧就发送了 200 状态码，没有机会再改成 500 了，只能发送错误事件 9. HttpException 在框架层使用  10. ExceptionGroup 解决要捕获多个异常的问题，except\* 解决要匹配 ExceptionGroup 中某个精确错误的问题

## 助手（原始消息 2041）

**批改：8/10**

第 2、3、6、8 题正确；第 1、7、9 题基本正确但需要补充；第 4、5、10 题需要修正。

**1. 基本正确**

```python
issubclass(Exception, BaseException)  # True
```

常见但不属于 `Exception` 的异常包括：

- `asyncio.CancelledError`
- `GeneratorExit`
- `KeyboardInterrupt`
- `SystemExit`

所以：

```python
except Exception:
    ...
```

不会捕获这些控制信号。

**2. 正确**

```python
try:
    ...
except ...:
    ...
else:
    ...
finally:
    ...
```

- `else`：`try` 块没有异常时执行
- `finally`：无论正常、异常、`return`，通常都会执行

`finally` 也可能因为进程被强制杀死、解释器崩溃等情况来不及执行，但正常情况下都会执行。

**3. 正确**

```python
def func():
    try:
        raise ValueError("原始错误")
    finally:
        return "finally 返回值"
```

最终返回 `"finally 返回值"`，原始 `ValueError` 被吞掉。

它也会覆盖 `try` 中的正常返回值：

```python
def func():
    try:
        return "try 返回值"
    finally:
        return "finally 返回值"
```

最终返回：

```text
finally 返回值
```

**4. 不够准确**

裸 `raise`：

```python
except ValueError as exc:
    logger.warning("发生错误: %s", exc)
    raise
```

会重新抛出当前异常，并保留原有 traceback。

`raise exc`：

```python
except ValueError as exc:
    raise exc
```

它仍然会抛这个异常，但会在 traceback 中增加当前 `raise exc` 位置，且会重新绑定异常。通常没有必要这样写。

更准确地说：

> 裸 `raise` 用于在 `except` 中保持原始异常上下文；`raise exc` 是重新抛出异常对象，可能增加额外 traceback 帧。

因此“记录后继续抛”应使用：

```python
except Exception:
    logger.exception("处理失败")
    raise
```

**5. 不准确**

`raise NewError(...) from exc` 的主要作用是建立**显式异常因果链**：

```python
try:
    await upstream_call()
except httpx.ReadTimeout as exc:
    raise UpstreamTimeout("上游服务超时") from exc
```

这里：

- `UpstreamTimeout` 是上层业务异常
- `exc` 是底层技术异常
- `UpstreamTimeout.__cause__` 指向 `exc`
- 日志会同时显示两者

它不只是“保留原始堆栈”，而是：

> 把新异常作为上层语义，把原始异常作为底层原因保留下来。

`from None`：

```python
raise UpstreamTimeout("上游服务超时") from None
```

作用是抑制异常上下文的展示，不会把底层异常作为“直接原因”显示出来。它不会真的删除原始异常对象，只是控制 traceback 的展示。

**6. 正确**

```python
except ValueError:
    ...
```

可能捕获：

- Token 超限
- JSON 解析失败
- 数字转换错误
- 第三方库内部参数错误
- 其他代码的格式问题

所以应使用：

```python
class TokenBudgetExceeded(Exception):
    pass
```

以及：

```python
except TokenBudgetExceeded:
    ...
```

**7. 基本正确**

适合重试的典型情况包括：

- `408 Request Timeout`
- `425 Too Early`
- `429 Too Many Requests`
- `500 Internal Server Error`
- `502 Bad Gateway`
- `503 Service Unavailable`
- `504 Gateway Timeout`
- 连接超时、读超时、临时 DNS/网络错误

但还要满足：

- 操作是幂等的
- 没有产生不可重复的副作用
- 遵守 `Retry-After`
- 有最大重试次数和总超时
- 使用退避和抖动

不应盲目重试：

- `400 Bad Request`
- `401 Unauthorized`
- `403 Forbidden`
- `404 Not Found`
- `422 Unprocessable Entity`
- 参数校验失败
- 代码 bug

`500` 也不一定永远能重试。如果服务端每次调用都因为同一个程序错误返回 `500`，重试只会浪费时间。

**8. 正确**

流式响应一旦发送了：

```http
HTTP/1.1 200 OK
Content-Type: text/event-stream
```

HTTP 响应头就已经固定。后续无法再把状态码改成 `500`。

只能发送：

```text
event: error
data: {"code":"INTERNAL_ERROR","message":"服务内部错误"}
```

普通的 FastAPI 全局异常处理器通常不能把已经开始的 SSE 响应改成 JSON 500。

**9. 基本正确，但“框架层”要再具体**

`HTTPException` 应该用在 API/Web 边界：

- FastAPI 路由函数
- FastAPI 依赖函数
- API 层异常处理器

不应该在：

- 数据库访问层
- 纯业务服务层
- 领域模型内部
- 通用工具函数

直接抛出：

```python
raise HTTPException(404, "用户不存在")
```

否则业务层会依赖 FastAPI，无法被 CLI、后台任务或单元测试复用。

更好的结构是：

```text
业务层抛出 UserNotFound
API 层捕获并转换成 HTTPException(404)
```

**10. 需要修正**

`ExceptionGroup` 解决的不是“如何捕获多个异常”这个简单问题，而是：

> 用一个统一对象表示多个可能同时发生的异常，并支持嵌套。

例如：

```python
ExceptionGroup(
    "多个任务失败",
    [
        TimeoutError("任务 A 超时"),
        ValueError("任务 B 数据错误"),
    ],
)
```

`except*` 则用于按异常类型拆分和处理 `ExceptionGroup`：

```python
try:
    await run_tasks()
except* TimeoutError as group:
    print("处理所有超时错误")
except* ValueError as group:
    print("处理所有值错误")
```

它的关键不是“精确匹配一个错误”，而是：

- 可以把异常组按类型分组
- 一个 `except*` 可以处理多个同类型子异常
- 未匹配的异常会继续传播
- 匹配到的异常集合会交给对应分支

所以更准确的表述是：

> `ExceptionGroup` 表示多个异常，`except*` 对异常组按类型拆分和处理。

---

**本课核心结论**

```text
具体异常优先于宽泛异常
业务异常优先于字符串匹配
异常链使用 raise ... from ...
取消信号不能吞掉
未知错误记录 traceback
对外错误信息要脱敏
流式响应开始后不能再改 HTTP 状态码
```

下一步建议进入：**Python 类型系统与泛型**，重点讲 `Any`、`object`、`TypeVar`、`ParamSpec`、`Protocol`、`Callable`、泛型类和运行时类型检查。回复“继续”开始。

## 用户（原始消息 2048）

我再问一个问题，如果 except* ValueError 然后 ValueError 在嵌套的第四层，会被捕获到吗？如果有多个呢 ，优惠如何，有多个的情况下连续捕获呢

## 助手（原始消息 2091）

**会捕获，但要区分“嵌套的 ExceptionGroup”和“异常因果链”。**

---

## 1. 第四层 `ExceptionGroup` 中的 ValueError 会被捕获

假设异常结构是：

```text
ExceptionGroup: top
└── ExceptionGroup: level1
    └── ExceptionGroup: level2
        └── ExceptionGroup: level3
            ├── ValueError("deep1")
            ├── ValueError("deep2")
            └── TypeError("other")
```

对于：

```python
except* ValueError as group:
    ...
```

**会递归找到第四层的两个 `ValueError`**。异常嵌套深度本身不会影响匹配。

例如：

```python
try:
    raise ExceptionGroup(
        "top",
        [
            ExceptionGroup(
                "level1",
                [
                    ExceptionGroup(
                        "level2",
                        [
                            ExceptionGroup(
                                "level3",
                                [
                                    ValueError("deep1"),
                                    ValueError("deep2"),
                                    TypeError("other"),
                                ],
                            )
                        ],
                    )
                ],
            )
        ],
    )

except* ValueError as group:
    print(repr(group))
```

实际捕获到的 `group` 仍然是嵌套结构，但只保留匹配的 `ValueError`：

```python
ExceptionGroup(
    "top",
    [
        ExceptionGroup(
            "level1",
            [
                ExceptionGroup(
                    "level2",
                    [
                        ExceptionGroup(
                            "level3",
                            [
                                ValueError("deep1"),
                                ValueError("deep2"),
                            ],
                        )
                    ],
                )
            ],
        )
    ],
)
```

没有被匹配的：

```python
TypeError("other")
```

会被移除出来，留待后续 `except*` 或最终重新抛出。

所以：

> `except*` 会递归匹配 `ExceptionGroup` 树中的叶子异常，而不是只看第一层。

---

## 2. 多层嵌套结构会被保留

假设原始结构是：

```text
ExceptionGroup: top
├── ValueError("v1")
└── ExceptionGroup: nested
    ├── ValueError("v2")
    └── TypeError("t1")
```

执行：

```python
except* ValueError as group:
    ...
```

捕获到的 `group.exceptions` 类似于：

```python
(
    ValueError("v1"),
    ExceptionGroup(
        "nested",
        [ValueError("v2")],
    ),
)
```

注意：

- 两个 `ValueError` 都会被捕获
- 原来的嵌套层次不会被完全拍平
- `nested` 中的 `TypeError` 被暂时移出

如果后续还有：

```python
except* TypeError as group:
    ...
```

它捕获的是剩余结构：

```python
(
    ExceptionGroup(
        "nested",
        [TypeError("t1")],
    ),
)
```

---

## 3. 多个同类型异常会在同一个 `except*` 中处理

如果有多个 `ValueError`：

```python
except* ValueError as group:
    print(len(group.exceptions))
```

它们会一起进入这个分支。

例如：

```python
try:
    raise ExceptionGroup(
        "top",
        [
            ValueError("v1"),
            ValueError("v2"),
            ValueError("v3"),
        ],
    )
except* ValueError as group:
    print(group.exceptions)
```

输出类似：

```python
(ValueError('v1'), ValueError('v2'), ValueError('v3'))
```

不会为每个 `ValueError` 分别调用一次 `except*`。一次 `except*` 会接收所有匹配的子异常。

即使只有一个匹配异常，`except*` 也会把它包装成异常组：

```python
except* ValueError as group:
    print(type(group).__name__)  # ExceptionGroup
    print(group.exceptions)     # (ValueError(...),)
```

---

## 4. 多个 `except*` 是连续分流处理

代码：

```python
try:
    raise ExceptionGroup(
        "top",
        [
            ValueError("v1"),
            ExceptionGroup(
                "nested",
                [
                    ValueError("v2"),
                    TypeError("t1"),
                ],
            ),
            TypeError("t2"),
        ],
    )

except* ValueError as group:
    print("处理 ValueError:", group)

except* TypeError as group:
    print("处理 TypeError:", group)
```

执行过程：

```text
第一轮：except* ValueError
    ├── 取走 v1
    └── 从 nested 中取走 v2

第二轮：except* TypeError
    ├── 取走 nested 中的 t1
    └── 取走 t2
```

两个分支都会执行，但处理的是不同的剩余异常。

大致输出：

```text
处理 ValueError: ExceptionGroup('top', [
    ValueError('v1'),
    ExceptionGroup('nested', [ValueError('v2')])
])

处理 TypeError: ExceptionGroup('top', [
    ExceptionGroup('nested', [TypeError('t1')]),
    TypeError('t2')
])
```

---

## 5. 一个异常只会被一个 `except*` 捕获

每个匹配到的异常都会从“未处理异常集合”中移走。

因此：

```python
except* ValueError:
    ...

except* Exception:
    ...
```

第一个分支会先取走所有 `ValueError`，第二个分支不会再看到它们，只能看到剩余的其他异常。

如果顺序反过来：

```python
except* Exception:
    ...

except* ValueError:
    ...
```

那么第一个分支会把所有 `Exception` 子类都取走，后面的 `ValueError` 分支通常不会执行。

所以 `except*` 和普通 `except` 一样，也存在匹配顺序问题。应当从具体到宽泛。

例如：

```python
except* FileNotFoundError:
    ...

except* OSError:
    ...
```

不要把 `OSError` 放在前面，否则 `FileNotFoundError` 会先被 `OSError` 捕获。

---

## 6. 没有匹配的异常会继续传播

假设：

```python
try:
    raise ExceptionGroup(
        "top",
        [
            ValueError("v1"),
            KeyError("k1"),
        ],
    )
except* ValueError as group:
    print("只处理 ValueError")
```

`ValueError` 被处理，但 `KeyError` 没有被处理。

`except*` 结束后，剩余异常会继续向上传播，通常仍表现为一个 `ExceptionGroup`：

```python
ExceptionGroup(
    "top",
    [KeyError("k1")],
)
```

不要以为匹配了一个异常，整个异常组就被完全吞掉了。

---

## 7. “第四层”如果指因果链，则不会被捕获

这一点很重要。

`except*` 只递归遍历：

```text
ExceptionGroup 树
```

它不会沿着：

```python
__cause__
__context__
```

去查找异常。

例如：

```python
try:
    try:
        raise ValueError("底层原因")
    except ValueError as exc:
        raise RuntimeError("上层错误") from exc
except* ValueError as group:
    ...
```

最终向外抛出的是：

```python
RuntimeError
```

`ValueError` 只是：

```python
exc.__cause__
```

它是异常因果链的一部分，不是 `ExceptionGroup` 的子异常。

所以 `except* ValueError` 不会因为因果链里有 `ValueError` 就捕获 `RuntimeError`。

这一点和普通异常处理一样：

```python
except ValueError:
```

匹配的是当前抛出的实际异常类型，不是它的 `__cause__` 类型。

---

## 8. 如何把嵌套匹配结果展开

`except*` 保留嵌套结构。如果你想处理所有叶子异常：

```python
def iter_exception_leaves(group: BaseExceptionGroup):
    for exc in group.exceptions:
        if isinstance(exc, BaseExceptionGroup):
            yield from iter_exception_leaves(exc)
        else:
            yield exc
```

使用：

```python
try:
    ...
except* ValueError as group:
    for exc in iter_exception_leaves(group):
        print(exc)
```

这样即使 `ValueError` 在第四层，也能逐个处理。

---

## 9. 两个语法限制

**不能混用 `except` 和 `except*`**

同一个 `try` 中通常不能同时出现：

```python
try:
    ...
except ValueError:
    ...
except* TypeError:
    ...
```

这会触发语法错误。

**`except*` 绑定的是异常组**

即使只匹配到一个异常：

```python
except* ValueError as group:
```

这里的 `group` 仍是 `ExceptionGroup`，不是直接的 `ValueError`。

想拿到单个异常，需要访问：

```python
group.exceptions[0]
```

或递归遍历。

---

## 最终回答

- 第四层 `ExceptionGroup` 中的 `ValueError`：会被 `except* ValueError` 递归捕获。
- 有多个 `ValueError`：会在同一个 `except*` 分支中一起捕获。
- 有多个 `except*`：按从上到下的顺序分流，每个子异常只会被处理一次。
- 前一个分支处理完的异常会从剩余异常组中移除。
- 未处理的异常继续向上传播。
- 匹配的是 `ExceptionGroup` 树中的叶子异常，不会追溯 `__cause__` 因果链。

