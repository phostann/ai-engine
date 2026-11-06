# FastAPI 请求、响应与异常边界

> 本文逐字转录自原始课程对话，只添加角色标题和来源信息，未改写、删减或二次总结。
>
- 返回：[课程原文索引](README.md)
- 原始消息序号：`1595`、`1600`、`1635`、`1642`、`1647`、`1654`、`1659`

## 用户（原始消息 1595）

继续

## 助手（原始消息 1600）

下一课进入：**FastAPI 请求模型、响应模型与统一异常处理**。前面已经分别学过 Pydantic、依赖注入和 SSE，这一课把它们串成完整的 HTTP 边界。

## 助手（原始消息 1635）

**下一课：FastAPI 请求、响应与异常边界**

这一课的核心是一条完整链路：

```text
HTTP 请求
  ↓
路由匹配
  ↓
依赖解析
  ↓
请求体校验
  ↓
路由函数
  ↓
响应模型校验与序列化
  ↓
HTTP 响应
```

任何阶段出错，都应该由明确的边界负责转换成客户端能理解的错误。

**1. 请求处理顺序**

对于当前接口：

```python
@router.post("/completions/stream")
async def stream_chat_completions(
    request: Request,
    body: GatewayChatRequest,
    llm_client: LLMClientDep,
    trace_id: TraceIdDep,
) -> EventSourceResponse:
    ...
```

FastAPI 大致执行：

```text
1. 匹配 POST /api/v1/chat/completions/stream
2. 解析依赖 LLMClientDep 和 TraceIdDep
3. 读取 JSON 请求体
4. 构造 GatewayChatRequest
5. 校验失败则返回 422，不执行路由函数
6. 校验通过后调用 stream_chat_completions
7. 返回 EventSourceResponse
8. 持续发送 SSE 数据帧
```

因此路由函数内部可以认为：

```python
body
llm_client
trace_id
```

都已经满足声明要求。不要把大量请求格式检查重复散落在业务代码里。

**2. 请求模型应该描述完整契约**

当前：

```python
class GatewayChatRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=2000)
    model: str = Field(default="gpt-4o-mini")
    system_override: str | None = Field(default=None)
```

它还存在一些边界缺口：

- `"   "` 可以通过 `min_length=1`。
- `model` 目前允许任意字符串。
- `system_override` 没有长度限制。
- 未知字段默认可能被忽略。

更严格的版本可以设计成：

```python
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

NonBlankPrompt = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=2000),
]


class GatewayChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt: NonBlankPrompt
    model: Literal["gpt-4o-mini", "gpt-4.1-mini"] = "gpt-4o-mini"
    system_override: str | None = Field(default=None, max_length=10000)
```

这里每一层含义不同：

```text
prompt：不能为空，最多 2000 字符
model：只允许服务端支持并计价的模型
system_override：限制提示词覆盖长度
extra="forbid"：拒绝拼错的未知字段
```

特别是 `model`。如果允许客户端传任意模型名，客户端可能调用昂贵模型，或者尝试访问未授权的模型。模型选择应该由服务端白名单控制。

**3. FastAPI 如何知道哪个参数是请求体**

```python
async def endpoint(body: GatewayChatRequest):
```

参数类型是 Pydantic 模型，FastAPI 会把它当作 JSON 请求体。

```python
async def endpoint(prompt: str):
```

简单类型默认通常会被当作查询参数，除非声明 `Body()`。

```python
async def endpoint(
    prompt: Annotated[str, Body()],
):
```

路径参数、查询参数、请求头和 Cookie 也都有各自声明方式：

```python
id: int                                  # 路径或查询，取决于路径模板
q: str | None = None                     # 查询参数
token: Annotated[str, Header()]          # 请求头
session: Annotated[str, Cookie()]        # Cookie
body: GatewayChatRequest                 # 请求体
```

不要用 `request.json()` 绕过 Pydantic 再手动校验；只有流式原始读取或特殊协议才需要直接操作 `Request`。

**4. 响应模型是输出契约**

普通 JSON 接口推荐显式声明：

```python
class ChatResponse(BaseModel):
    content: str
    model: str
    trace_id: str


@router.post("/completions", response_model=ChatResponse)
async def chat(...) -> ChatResponse:
    return ChatResponse(...)
```

`response_model` 负责：

- 生成 OpenAPI 文档。
- 校验路由返回的数据。
- 按输出模型过滤字段。
- 应用输出别名。
- 把 Python 对象序列化为 JSON。

例如内部返回：

```python
{
    "id": 1,
    "name": "Alice",
    "password_hash": "secret",
}
```

如果：

```python
class UserResponse(BaseModel):
    id: int
    name: str
```

则 `password_hash` 不会出现在响应中。

但不要依赖过滤来保护密钥。更好的设计是让内部模型从一开始就不要把密钥交给响应层。

**5. 返回模型与返回 `Response` 的区别**

返回 Pydantic 模型：

```python
return ChatResponse(...)
```

FastAPI 会执行响应模型校验和序列化。

返回 `Response` 子类：

```python
return JSONResponse(...)
return StreamingResponse(...)
return EventSourceResponse(...)
```

FastAPI 通常不会再对它执行普通 `response_model` 序列化。响应对象已经自己负责编码。

当前 SSE 接口返回：

```python
return EventSourceResponse(...)
```

所以每帧数据必须手动编码：

```python
yield {
    "event": "message",
    "data": json.dumps(
        {"content": token},
        ensure_ascii=False,
    ),
}
```

**6. 常用 HTTP 状态码**

```text
200 OK                  查询或处理成功
201 Created             资源创建成功
202 Accepted            已接收，异步处理
204 No Content          成功但没有响应体
400 Bad Request         请求语义错误
401 Unauthorized        未认证
403 Forbidden           已认证但无权限
404 Not Found           资源不存在
409 Conflict            版本冲突、重复创建
422 Unprocessable       请求格式正确但数据校验失败
429 Too Many Requests   限流
500 Internal Server     未预期的服务端错误
502 Bad Gateway         上游返回非法结果
503 Service Unavailable 服务未就绪或暂时不可用
504 Gateway Timeout     上游超时
```

FastAPI 的请求体校验默认返回 `422`。

`401` 和 `403` 要区分：

```text
401：你是谁还不知道，或者凭证无效
403：知道你是谁，但不允许执行该操作
```

**7. `HTTPException` 用于可预期的 HTTP 错误**

```python
from fastapi import HTTPException, status

raise HTTPException(
    status_code=status.HTTP_404_NOT_FOUND,
    detail="章节不存在",
)
```

`detail` 可以是字符串，也可以是可 JSON 序列化的结构：

```python
raise HTTPException(
    status_code=429,
    detail={
        "code": "RATE_LIMITED",
        "message": "请求过于频繁",
    },
    headers={"Retry-After": "5"},
)
```

当前依赖中：

```python
if client is None:
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="NativeLLMClient 尚未在 lifespan 中初始化",
    )
```

这里更适合使用：

```text
503 Service Unavailable
```

因为表示的是应用资源尚未准备好，而不是发生了一个未知的内部错误。

**8. 不要在业务层到处抛 `HTTPException`**

不推荐让 LLM 客户端、Token 计算、数据库层直接依赖 FastAPI：

```python
# service/llm_client.py
from fastapi import HTTPException  # 不推荐
```

推荐定义业务异常：

```python
class TokenBudgetExceeded(Exception):
    pass


class UpstreamTimeout(Exception):
    pass
```

在 HTTP 边界统一映射：

```python
try:
    ...
except TokenBudgetExceeded:
    raise HTTPException(status_code=400, detail="Token 超限")
except UpstreamTimeout:
    raise HTTPException(status_code=504, detail="上游推理超时")
```

否则业务层会和 Web 框架强耦合，也难以在后台任务、CLI 或消息消费者中复用。

**9. `RequestValidationError` 是 FastAPI 的请求校验异常**

请求体、路径参数、查询参数、请求头校验失败时，FastAPI 会抛出：

```python
from fastapi.exceptions import RequestValidationError
```

默认响应大致是：

```json
{
  "detail": [
    {
      "type": "string_too_short",
      "loc": ["body", "prompt"],
      "msg": "String should have at least 1 character",
      "input": ""
    }
  ]
}
```

`loc` 的常见结构：

```text
["body", "prompt"]
["body", "relations", 0, "source_character"]
["query", "limit"]
["header", "x-trace-id"]
```

统一错误响应可以这样注册：

```python
from fastapi import Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    errors = [
        {
            "loc": list(error["loc"]),
            "type": error["type"],
            "msg": error["msg"],
        }
        for error in exc.errors()
    ]

    return JSONResponse(
        status_code=422,
        content=jsonable_encoder(
            {
                "code": "VALIDATION_ERROR",
                "message": "请求参数校验失败",
                "errors": errors,
            }
        ),
    )
```

注意不要直接返回完整的 `error`，因为其中可能包含 `ctx`、原始 `input` 或敏感内容。

默认 `422` 响应可能回显请求输入。如果请求中有密码、API Key 或其他敏感字段，需要自定义处理并删除 `input`。

**10. `HTTPException` 与通用异常处理**

FastAPI 的 `HTTPException` 继承自 Starlette 的异常。捕获时通常注册 Starlette 类型：

```python
from starlette.exceptions import HTTPException as StarletteHTTPException


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(
    request: Request,
    exc: StarletteHTTPException,
) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "code": "HTTP_ERROR",
            "message": exc.detail,
        },
        headers=exc.headers,
    )
```

这样 FastAPI 自身和 Starlette 内部抛出的 HTTP 异常都会经过同一个处理器。

通用异常处理：

```python
@app.exception_handler(Exception)
async def unhandled_exception_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    logger.exception("未处理的服务端异常")
    return JSONResponse(
        status_code=500,
        content={
            "code": "INTERNAL_ERROR",
            "message": "服务器内部错误",
        },
    )
```

对客户端只返回通用信息，完整 Traceback 只写入服务端日志。

不要把下面内容返回给客户端：

```text
异常字符串
数据库连接信息
文件路径
上游响应体
API Key
完整 Traceback
```

**11. SSE 是特殊的错误边界**

普通接口可以先抛出异常，再由异常处理器返回 `400/500`：

```text
请求
  ↓
异常
  ↓
HTTP 4xx/5xx 响应
```

SSE 一旦开始输出，HTTP 状态码和响应头已经发送：

```text
HTTP/1.1 200 OK
Content-Type: text/event-stream
  ↓
持续发送事件
```

此时上游超时不能再改成 `504`。只能发送一个 SSE `error` 事件：

```python
yield {
    "event": "error",
    "data": json.dumps(
        {
            "code": "UPSTREAM_TIMEOUT",
            "message": "上游推理超时",
        },
        ensure_ascii=False,
    ),
}
yield {"event": "done", "data": "[DONE]"}
```

当前代码就是这样处理的：

```python
except ValueError:
    yield error(code=40001)
    yield done

except Exception:
    yield error(code=50000)
    yield done
```

但这里有一个设计问题：`except ValueError` 太宽泛。任何业务代码中的普通 `ValueError` 都会被解释成 Token 预算错误。

更稳妥的方式是定义专用异常：

```python
class TokenBudgetExceeded(Exception):
    pass
```

然后只捕获：

```python
except TokenBudgetExceeded as exc:
    ...
```

**12. 流式接口的客户端契约**

客户端必须同时处理两个阶段：

```text
请求建立阶段
  -> 可能收到普通 HTTP 422/401/503 JSON

流式输出阶段
  -> HTTP 200
  -> message 事件
  -> error 事件
  -> done 事件
```

错误事件必须有稳定结构，例如：

```json
{
  "code": "TOKEN_BUDGET_EXCEEDED",
  "message": "上下文 Token 超限",
  "retryable": false
}
```

不要只依赖中文错误消息，程序应使用稳定的 `code`。

**13. OpenAPI 中声明错误响应**

可以在路由中补充错误文档：

```python
@router.post(
    "/completions/stream",
    responses={
        422: {"description": "请求参数校验失败"},
        503: {"description": "LLM 客户端尚未初始化"},
    },
)
```

这不会改变运行逻辑，但能让接口文档明确展示错误契约。

**14. 当前项目需要重点关注的地方**

- `GatewayChatRequest` 没有限制 `model` 白名单。
- `system_override` 没有最大长度。
- `prompt` 尚未禁止全空白。
- 请求模型未设置 `extra="forbid"`。
- LLM 客户端未初始化时使用 `500`，更准确应为 `503`。
- 没有统一的 `RequestValidationError` 错误格式。
- 没有统一的 `HTTPException` 错误格式。
- SSE 中通过 `except ValueError` 判断 Token 预算错误，过于宽泛。
- 当前 SSE 错误帧已经避免把上游异常细节泄露给客户端，这一点是正确的。

**掌握标准**

你应该能回答：

1. FastAPI 在路由函数执行前会完成哪些工作？
2. 请求模型、响应模型分别解决什么问题？
3. `response_model` 为什么能过滤掉密码字段？
4. `401`、`403`、`422`、`500`、`503` 分别适合什么场景？
5. `HTTPException` 和通用 `Exception` 的使用边界是什么？
6. `RequestValidationError` 的 `loc` 如何定位请求字段？
7. 为什么请求校验失败时不能返回 `200`？
8. 为什么 SSE 开始输出后不能再把状态码改成 `504`？
9. 为什么 `except ValueError` 不适合作为明确的 Token 预算错误处理？
10. 客户端应该如何处理普通 HTTP 错误和 SSE `error` 事件这两种不同错误通道？

## 用户（原始消息 1642）

开始这一课

## 助手（原始消息 1647）

好，这一课分四段讲：

```text
1. FastAPI 请求处理链路与请求模型
2. 响应模型与序列化边界
3. HTTPException、422 与统一错误响应
4. SSE 流式接口的特殊错误处理
```

先开始第一段。

**请求处理链路**

当前接口：

```python
@router.post("/completions/stream")
async def stream_chat_completions(
    request: Request,
    body: GatewayChatRequest,
    llm_client: LLMClientDep,
    trace_id: TraceIdDep,
) -> EventSourceResponse:
    ...
```

FastAPI 在调用这个函数前会完成：

```text
1. 匹配 HTTP 方法和路径
2. 识别参数来源
3. 解析依赖
4. 读取并解析 JSON
5. 构造 GatewayChatRequest
6. 校验失败则返回 422，不执行路由函数
7. 校验通过后调用路由函数
```

因此路由函数内部不需要再写：

```python
if not isinstance(body, dict):
    ...
```

这些边界检查已经由 FastAPI 和 Pydantic 完成。

**参数来源由声明决定**

```python
request: Request
```

FastAPI 注入当前请求对象，可以访问请求头、客户端地址、连接状态等。

```python
body: GatewayChatRequest
```

因为它是 Pydantic 模型，FastAPI 把它识别为 JSON 请求体，并把字典转换成模型实例。

```python
llm_client: LLMClientDep
```

虽然它看起来是一个普通参数，但别名中包含：

```python
Annotated[NativeLLMClient, Depends(get_llm_client)]
```

所以它不是请求体，而是依赖注入。

```python
trace_id: TraceIdDep
```

同理，它不是普通字符串参数，而是通过：

```python
Depends(get_request_trace_id)
```

取得的值。

这四个参数展示了 FastAPI 的核心机制：

```text
参数类型决定基础语义
Annotated 元数据决定具体来源
```

**请求模型是客户端契约**

当前模型：

```python
class GatewayChatRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=2000)
    model: str = Field(default="gpt-4o-mini")
    system_override: str | None = Field(default=None)
```

合法请求：

```json
{
  "prompt": "解释一下 FastAPI 的生命周期"
}
```

经过校验后，路由收到的是：

```python
GatewayChatRequest(
    prompt="解释一下 FastAPI 的生命周期",
    model="gpt-4o-mini",
    system_override=None,
)
```

可以属性访问：

```python
body.prompt
body.model
body.system_override
```

它不是原始字典。

非法请求：

```json
{
  "prompt": ""
}
```

会在调用路由函数之前得到 `422`：

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

`loc` 表示：

```text
请求体 body 中的 prompt 字段
```

**当前请求模型的三个缺口**

第一，全空白字符串：

```json
{"prompt": "   "}
```

长度为 3，可以通过 `min_length=1`。如果业务不接受全空白，需要先清洗再检查：

```python
type NonBlankPrompt = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=2000),
]
```

第二，模型没有白名单：

```python
model: str
```

客户端可以传任意模型名。更安全的是：

```python
model: Literal["gpt-4o-mini", "gpt-4.1-mini"] = "gpt-4o-mini"
```

否则客户端可能调用未授权或成本更高的模型。

第三，未知字段默认被忽略：

```json
{
  "prompt": "你好",
  "systemOveride": "客户端拼错的字段"
}
```

因为 `BaseModel` 默认是 `extra="ignore"`，所以 `systemOveride` 会被静默丢弃，系统继续使用默认提示词。

如果接口要求字段严格匹配：

```python
model_config = ConfigDict(extra="forbid")
```

未知字段会返回 `extra_forbidden`。

但这是接口设计选择：

- 公共接口可能选择 `ignore`，方便向后兼容。
- 内部接口或 LLM 结构化输出通常选择 `forbid`，避免拼写错误被隐藏。

**什么时候直接使用 `Request`**

普通 JSON 接口不需要：

```python
raw = await request.json()
body = GatewayChatRequest.model_validate(raw)
```

因为 FastAPI 已经自动做了。

直接使用 `Request` 适合：

- 检查客户端是否断开。
- 读取原始字节。
- 处理非标准 Content-Type。
- 实现 SSE、WebSocket 或文件上传。
- 读取 FastAPI 参数系统之外的信息。

当前代码使用：

```python
if await request.is_disconnected():
```

这是合法用途，因为流式输出期间需要检测客户端是否已经断开。

**第一段要记住的结论**

```text
路由参数类型和 Annotated 元数据共同决定数据来源
请求体在进入路由函数前完成 Pydantic 校验
校验失败不会执行路由函数
请求模型就是客户端契约
extra 策略、类型范围和长度限制决定边界严格程度
Request 用于访问底层请求信息，不应取代常规请求模型
```

先确认这几个问题：

1. `body: GatewayChatRequest` 为什么会被识别为请求体？
2. `trace_id: TraceIdDep` 为什么不是普通字符串查询参数？
3. `{"prompt": "   "}` 为什么当前可能通过校验？
4. `extra="ignore"` 对拼错的请求字段有什么影响？
5. 为什么不能把 `model: str` 直接暴露给客户端调用任意模型？

## 用户（原始消息 1654）

我还是回答上面那个比较全面的问题列表 1. 在路由函数执行前会先进行路径匹配和参数校验 2. 请求模型是对客户端的约束，响应模型是对系统内部要返回给前端内容的约束3. response_model 中没有密码字段或者使用了 pydantic secretstr 本身就做了特殊处理 4. 401 未认证 403 认证但无权限，422 参数解析失败 500 服务内部错误，503 服务资源未准备好。 5. httpexception 主要用于fastapi 返回数据的依据，普通 exception 则在后端程序内部使用 6。loc 会返回字段名和位置吧，大概是这样 7. 校验失败根本不会执行函数，所以不能给客户端返回 200 8. sse 第一帧返回后状态码就是  200 了，做不到后续再改状态码为 504 且强行这样做可能会引起错误。9. valueError 太宽泛了 10。 普通 http 错误使用状态码，sse 通过事件类型来传递错误

## 助手（原始消息 1659）

**批改：9/10，整体理解已经正确，主要补充精确性。**

1. 不完整。路由函数执行前还包括：

   ```text
   路径和方法匹配
   解析参数来源
   递归解析依赖
   读取并解析请求体
   执行 Pydantic 校验
   ```

   任何必要步骤失败，路由函数都不会执行。

2. 正确。可以表述为：

   ```text
   请求模型：外部输入 -> 内部可信数据
   响应模型：内部数据 -> 对外稳定输出
   ```

   响应模型同时负责输出校验、字段过滤和 OpenAPI 文档生成。

3. 正确，但这是两种不同机制：

   - `response_model` 中不声明密码字段，所以字段被过滤。
   - `SecretStr` 防止该字段在 `repr` 和 JSON 序列化中意外暴露。

   最安全的仍然是专门定义输出模型，从一开始就不把密码字段传进响应模型。

4. 正确。`422` 更准确地说是：

   ```text
   请求格式可以被解析
   但字段类型、范围、必填性或业务结构不合法
   ```

   另外，响应数据不符合 `response_model` 属于服务端错误，应返回 `500`，不是 `422`。

5. 需要修正表述。`HTTPException` 不只是“返回数据的依据”，它表示可预期的 HTTP 协议错误：

   ```python
   raise HTTPException(status_code=404, detail="资源不存在")
   ```

   普通未处理异常则属于程序错误，通常由全局异常处理器记录日志，并向客户端返回不包含内部细节的 `500`。

   服务层最好不要直接抛 `HTTPException`，而应抛业务异常，到 HTTP 边界再转换。

6. 太模糊。`loc` 是错误位置路径，典型形式是：

   ```python
   ("body", "prompt")
   ("body", "relations", 0, "source_character")
   ("query", "limit")
   ("header", "x-trace-id")
   ```

   分别表示：

   ```text
   请求体 prompt 字段
   relations 列表第 0 个元素的 source_character
   查询参数 limit
   X-Trace-ID 请求头
   ```

   模型级校验错误可能定位到整个模型：

   ```python
   ("body", "relations", 0)
   ```

7. 正确。校验失败不会进入路由函数，框架会在 HTTP 边界返回 `422`。

8. 正确。SSE 已经开始发送后：

   ```text
   HTTP 状态行和响应头已发送
   后续只能发送事件数据
   ```

   此时不能修改状态码，只能发送：

   ```text
   event: error
   data: {"code": "...", "message": "..."}
   ```

   然后通过：

   ```text
   event: done
   data: [DONE]
   ```

   明确结束流。

9. 正确。`except ValueError` 会把业务异常和程序自身的普通 `ValueError` 混在一起。应该定义：

   ```python
   class TokenBudgetExceeded(Exception):
       pass
   ```

   然后只捕获这个专用异常。

10. 正确。完整客户端契约是：

   ```text
   请求建立阶段失败 -> 普通 HTTP 状态码 + JSON 错误体
   流式输出阶段失败 -> HTTP 200 + SSE error 事件
   ```

   客户端必须同时处理两个错误通道，不能只判断 HTTP 状态码。

你已经掌握了这一课的核心。接下来可以进入 **SSE 与异步生成器**，重点学习 `EventSourceResponse`、流式帧格式、客户端断连和生成器取消。

