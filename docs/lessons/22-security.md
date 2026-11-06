# 安全威胁建模与信任边界（仅讲解，未批改）

> 本文记录本轮安全专题课程，保留完整讲解、代码证据、运行时实验和验收问题。
>
> - 知识点：`security`
> - 日期：2026-11-05
> - 说明：旧版安全综述已由本文覆盖；本课只讲安全威胁建模与信任边界。

## 用户（课程开始）

继续

## 助手（知识点讲解与考题）

**本课知识点：安全威胁建模与信任边界**

上一轮我给的更像“安全专题提纲”，不是之前那种课程。之前第 20 课拆成了 ASGI、lifespan、中间件、依赖、请求顺序、SSE、测试等 20 个小节；第 21 课拆成了 logging 模型、Handler、trace_id、异步上下文、SSE 日志、日志测试等 21 个小节。

这次重新按旧方式讲。

---

## 0. 本课要解决的问题

这一课不先写认证代码，也不先改 CORS。

先回答一个更基础的问题：

> 这个 AI Gateway 到底有哪些东西值得保护？谁会攻击？攻击从哪条边界进入？每条路径会造成什么后果？

如果不先回答这个问题，直接加 API Key、限制 CORS、使用 `SecretStr`，很容易变成“配置了一堆东西，但不知道自己防住了什么”。

本课的主线是：

```text
资产
  ↓
攻击者
  ↓
信任边界
  ↓
攻击路径
  ↓
威胁
  ↓
控制措施
  ↓
残余风险
```

后面几节会逐步展开这条链。

---

## 1. 安全不是一组配置项

很多人对安全的第一反应是记住这些措施：

```text
加 API Key
加 JWT
加 CORS
使用 SecretStr
不要返回异常堆栈
加限流
```

这些措施本身没有错，但它们是“手段”，不是“分析过程”。

比如：

```text
给接口加 API Key 就一定安全吗？
```

不一定。

如果：

- API Key 被日志打印出来；
- API Key 允许调用任意模型；
- API Key 被写进前端代码；
- API Key 通过 Cookie 传递，但接口没有 CSRF 防护；
- API Key 没有额度限制；
- API Key 泄露后没有轮换机制；

那么“有认证”并不等于“系统安全”。

所以安全应该从资产和边界开始，而不是从配置项开始。

---

## 2. 威胁建模的五个基本元素

后面所有安全课程都可以套用这个结构：

| 元素 | 要回答的问题 |
| --- | --- |
| Asset 资产 | 有什么值得保护 |
| Actor 角色 | 谁可能访问或攻击 |
| Trust Boundary 信任边界 | 数据或控制权在哪里发生变化 |
| Threat 威胁 | 攻击者能做什么，会造成什么后果 |
| Control 控制 | 用什么机制降低风险 |

它们的关系是：

```text
资产
  ↑
谁会碰它？
  ↑
他从哪里进来？
  ↑
他能做什么？
  ↑
我们用什么阻止他？
```

注意：威胁建模不是把所有攻击都列出来，而是找出最值得优先处理的风险。

---

## 3. 这个项目的资产盘点

先不要看“安全功能”，先看项目里有什么东西。

### 3.1 上游大模型 API Key

项目配置中有：

```python
llm_api_key: SecretStr = Field(..., description="大模型 API 密钥")
```

位置：

```text
src/ai_engine/core/config.py:23
```

它被用于请求上游：

```python
headers = {
    "Authorization": f"Bearer {self.settings.llm_api_key.get_secret_value()}",
    "Content-Type": "application/json",
}
```

位置：

```text
src/ai_engine/services/llm_client.py:43-46
```

这个 Key 是典型的高价值资产：

- 攻击者拿到后可以直接调用上游。
- 可能产生真实费用。
- 不一定会触发本项目的日志或权限控制。
- 可能无法立即判断是谁泄露的。

所以它不是普通配置项，而是凭据。

### 3.2 调用额度和成本控制能力

即使 Key 没有泄露，攻击者也可以通过本项目消耗额度。

当前请求模型允许调用方传：

```python
model: str = Field(default="gpt-4o-mini", description="模型名称")
system_override: str | None = Field(default=None, description="可选覆盖系统提示词")
```

位置：

```text
src/ai_engine/api/v1/chat.py:23-26
```

这意味着调用方可以影响：

- 使用哪个模型；
- 使用多长的系统提示词；
- 最终的 Token 消耗；
- 输出行为。

如果服务端没有模型白名单、Token 限制和频率限制，成本和可用性就不完全在自己的控制里。

### 3.3 系统提示词和行为约束

项目有默认系统提示词：

```python
DEFAULT_SYSTEM_PROMPT = SystemPromptTemplate(
    role_identity="资深全栈架构师",
    objectives=[
        "以严谨、高内聚低耦合的工程视角解答用户提问",
        "给出生产可落地的架构建议与代码",
    ],
    constraints=[
        "严禁给出脱离工程实际的伪代码",
        "禁止编造不存在的三方库 API",
    ],
    output_format="输出技术规范严谨的 Markdown 格式",
)
```

但请求可以覆盖：

```python
system_content = body.system_override or DEFAULT_SYSTEM_PROMPT.render()
```

位置：

```text
src/ai_engine/api/v1/chat.py:44
```

这里有一个非常重要的安全区别：

```text
普通 Prompt：
    用户问什么

System Prompt：
    模型应该如何行动
```

`system_override` 控制的不是“用户问题”，而是“模型行为规则”。

所以它属于控制面输入，不是普通文本字段。

### 3.4 用户 Prompt 和业务数据

请求中的 `prompt` 可能包含：

- 源代码；
- 内部文档；
- 业务数据；
- 用户隐私；
- 生产环境信息。

这些数据会经过：

```text
客户端
  ↓
FastAPI
  ↓
日志
  ↓
上游大模型
```

如果日志记录了完整 Prompt，或者错误信息把 Prompt 返回给客户端，就会形成新的泄露路径。

安全不只是“防止别人偷数据库”，还要考虑：

- 数据会进入哪些第三方服务；
- 数据会不会进入日志；
- 数据会不会进入错误响应；
- 数据会不会被缓存。

### 3.5 日志和 trace 信息

项目通过：

```python
class TraceIdFilter(logging.Filter):
    def filter(self, record: LogRecord) -> bool:
        record.trace_id = _trace_id_var.get("system")
        return True
```

把 trace_id 注入日志。

位置：

```text
src/ai_engine/core/logger.py:8-13
```

日志本身也是资产。

因为日志可能包含：

- 请求路径；
- 上游状态码；
- 异常堆栈；
- Prompt 长度；
- trace_id；
- 内部主机名或类名；
- 未来可能加入的请求 Header。

开发阶段日志多一点没关系，生产环境必须有脱敏规则。

### 3.6 服务可用性

流式接口天然是长连接：

```python
return EventSourceResponse(stream_generator, ping=15)
```

位置：

```text
src/ai_engine/api/v1/chat.py:95-104
```

长连接意味着：

- 每个请求会占用连接和协程资源；
- 上游慢会拖住下游；
- 客户端慢读会造成背压；
- 没有并发上限时，大量请求可能耗尽连接池；
- 没有请求超时和取消处理时，资源释放会变复杂。

所以“可用性”也是安全资产。

---

## 4. 这个项目里的攻击者角色

威胁建模不能只写“黑客”。

至少要区分以下角色。

### 4.1 匿名调用方

没有 API Key、没有 Cookie、没有 token，直接访问接口。

当前路由签名：

```python
@router.post("/completions/stream")
async def stream_chat_completions(
    request: Request,
    body: GatewayChatRequest,
    llm_client: LLMClientDep,
    trace_id: TraceIdDep,
) -> EventSourceResponse:
```

位置：

```text
src/ai_engine/api/v1/chat.py:95-104
```

参数里有 `Request`、请求体、LLM 客户端和 trace_id，但没有认证依赖。

这意味着项目当前没有在路由入口表达“调用方必须是谁”。

需要注意：没有认证依赖，不等于请求一定成功；它可能在依赖初始化、参数校验或上游请求阶段失败。但“失败原因”不等于“身份认证”。

### 4.2 合法但恶意的调用方

假设以后增加了 API Key。

一个合法调用方仍然可能：

- 使用未授权的模型；
- 传入超长 `system_override`；
- 消耗其他租户的额度；
- 高频请求；
- 通过错误信息探测内部实现；
- 伪造 trace_id。

这类攻击比匿名攻击更隐蔽，因为请求看起来是合法的。

所以认证之后还必须有授权。

### 4.3 恶意网页

攻击者可以控制一个网页，让用户的浏览器发起请求：

```text
https://evil.example
```

恶意网页不一定会直接拿到服务端文件，但它可以：

- 发起跨源请求；
- 读取允许读取的响应；
- 利用浏览器携带的 Cookie；
- 利用错误配置扩大攻击面。

CORS 就是为这个场景服务的浏览器安全机制。

但 CORS 不是认证，也不是服务端防 curl。

### 4.4 运维误配置

很多安全事故不是攻击者直接“打穿”，而是：

- API Key 写进 `.env` 后误提交；
- `.env` 没有被 `.gitignore` 忽略；
- 日志中打印了完整配置；
- `allow_origins` 为了方便写成 `*`；
- `extra="ignore"` 让拼错的配置被静默忽略；
- 生产环境仍然开放调试信息。

误配置也是威胁模型的一部分。

### 4.5 上游模型服务

上游服务也不是完全可信的。

它可能：

- 返回异常格式；
- 返回超长内容；
- 返回 429 或 5xx；
- 中断连接；
- 返回包含敏感信息的错误；
- 产生不符合预期的输出。

当前 `llm_client` 会解析上游 SSE：

```python
async for line in response.aiter_lines():
    if not line or not line.startswith("data: "):
        continue
    data_str = line[len("data: ") :].strip()
    if data_str == "[DONE]":
        break
    chunk = json.loads(data_str)
    delta = chunk.get("choices", [{}])[0].get("delta", {})
    content_token = delta.get("content")
    if content_token:
        yield content_token
```

位置：

```text
src/ai_engine/services/llm_client.py:54-70
```

这说明上游输出已经进入本服务的数据面。

后续要考虑：

- JSON 解析失败怎么办；
- 上游返回空 choices 怎么办；
- 上游返回超长内容怎么办；
- 上游错误是否会被转换成内部错误；
- 上游错误是否会把内部信息带给客户端。

---

## 5. 信任边界到底是什么

“信任边界”不是网络图画出来的一条线。

它表示：

> 从一个区域进入另一个区域后，原来的信任假设不再成立。

例如：

```text
浏览器传来的 Header
```

不能因为它是 HTTP Header 就信任。

```text
请求体里的 model
```

不能因为 Pydantic 接受了这个字段就信任。

```text
上游返回的 JSON
```

不能因为状态码是 200 就信任。

```text
客户端传入的 X-Trace-ID
```

不能因为格式像 trace_id 就信任。

---

## 6. 画出当前项目的请求链路

当前实际链路可以画成：

```text
浏览器 / 脚本客户端
        │
        │  1. 外部请求进入 FastAPI
        ▼
FastAPI + CORSMiddleware
        │
        │  2. 参数校验、Header 解析
        ▼
路由函数
        │
        │  3. 依赖注入：trace_id、llm_client
        ▼
app.state.llm_client
        │
        │  4. NativeLLMClient 使用上游 Key
        ▼
HTTPX → 上游模型服务
        │
        │  5. 流式响应返回
        ▼
EventSourceResponse → 客户端
```

这个链路中有六个边界。

### 6.1 边界一：客户端 → FastAPI

跨越内容：

- Body 中的 `prompt`
- Body 中的 `model`
- Body 中的 `system_override`
- Header 中的 `X-Trace-ID`
- 未来的 API Key、Cookie、JWT

需要问的问题：

```text
调用方是谁？
请求体字段是否可信？
model 是否允许？
system_override 是否允许？
X-Trace-ID 是否可信？
请求大小是否有限制？
```

当前事实：

- `prompt` 有 `max_length=2000`；
- `model` 没有白名单；
- `system_override` 没有长度限制；
- `X-Trace-ID` 由客户端直接传入；
- 没有认证依赖。

### 6.2 边界二：路由 → 依赖和业务逻辑

跨过路由后，程序会执行：

```python
llm_client: LLMClientDep
```

它从 `app.state` 取全局客户端：

```python
async def get_llm_client(request: Request) -> NativeLLMClient:
    client: NativeLLMClient | None = getattr(request.app.state, "llm_client", None)
```

位置：

```text
src/ai_engine/api/deps.py:30-38
```

这个边界要问：

```text
调用方有没有权限使用全局客户端？
调用方有没有权限使用指定模型？
这次调用是否应该消耗全局额度？
```

当前依赖只检查：

```text
app.state 里有没有 llm_client
```

这不等于检查：

```text
调用方是谁
调用方能不能用这个 client
调用方能不能用这个模型
```

### 6.3 边界三：本服务 → 上游模型

跨过这里时，使用：

```python
Authorization: Bearer <llm_api_key>
```

这一步的风险是：

- Key 泄露；
- Key 被用于未授权模型；
- 请求被发到错误 base_url；
- Prompt 被上游记录；
- 错误信息从上游回传；
- 上游超时导致资源占用。

这里的第一原则是：

> 上游 Key 是服务端凭据，不是客户端凭据。

### 6.4 边界四：进程 → 配置和 `.env`

配置层：

```python
model_config = SettingsConfigDict(
    env_file=".env", env_file_encoding="utf-8", case_sensitive=False, extra="ignore"
)
```

位置：

```text
src/ai_engine/core/config.py:11-13
```

要问：

- `.env` 会不会进 Git？
- 环境变量拼错会不会静默忽略？
- 配置会不会被打印到日志？
- 生产配置和开发配置是否分开？
- Secret 是否支持轮换？
- 配置是否由系统 Secret 管理器提供？

当前：

- `.env` 在 `.gitignore` 中；
- `SecretStr` 存在；
- `masked_api_key` 存在但没有调用；
- `extra="ignore"` 会静默忽略未知配置项。

### 6.5 边界五：应用 → 日志

日志不是只读旁路。

日志会接收来自多个边界的数据：

```text
请求 Header
Prompt
异常字符串
上游状态码
trace_id
```

如果不对这些数据做边界处理，就会出现：

- 密钥泄露；
- Prompt 泄露；
- 错误堆栈泄露；
- trace_id 注入；
- 日志格式被破坏。

安全日志的原则不是“多打日志”，而是：

> 打足够定位问题的信息，但不打不能进入日志的敏感信息。

### 6.6 边界六：应用 → 客户端响应

HTTP 响应包括：

- 正常 JSON；
- 错误 `detail`；
- SSE `data`；
- SSE `event`；
- trace_id 响应头。

当前部分错误直接返回内部字符串：

```python
raise HTTPException(
    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
    detail="NativeLLMClient 尚未在 lifespan 中初始化",
)
```

位置：

```text
src/ai_engine/api/deps.py:34-37
```

流式错误也会返回：

```python
{"code": 40001, "message": str(val_err)}
```

位置：

```text
src/ai_engine/api/v1/chat.py:72-76
```

这里要问：

```text
这个错误信息能不能让客户端知道？
它是否暴露了类名、路径、Token、Prompt 或内部状态？
客户端能否利用它探测系统？
```

---

## 7. Data Plane 和 Control Plane

这是 LLM 网关安全里非常重要的一对概念。

### Data Plane

数据面是用户实际处理的内容：

```text
prompt
messages
token 内容
用户文档
模型输出
```

### Control Plane

控制面是决定“系统如何行动”的输入：

```text
model
system_override
max_tokens
temperature
tenant
permission
```

在这个项目中：

```python
model
system_override
```

都属于控制面。

为什么控制面更危险？

因为攻击者改了普通 Prompt，最多影响一次内容生成。

但攻击者如果控制了：

```text
model = 最贵的模型
system_override = 绕过安全规则
max_tokens = 很大
```

就可能导致：

- 成本失控；
- 行为失控；
- 安全规则失效；
- 服务资源被耗尽。

所以后面的授权课程要讨论：

```text
谁可以修改 model
谁可以修改 system_override
谁可以设置 max_tokens
谁可以改变租户额度
```

---

## 8. 当前代码中的四个关键事实

### 8.1 上游 Key 已经保护使用边界，但还不能保护入口

```python
llm_api_key: SecretStr
```

和：

```python
self.settings.llm_api_key.get_secret_value()
```

说明项目已经意识到 Key 是敏感数据，并在上游请求构造处取值。

但这只解决：

```text
代码误打印 SecretStr
```

不能解决：

```text
任何客户端都可以调用入口
```

### 8.2 入口没有认证依赖

当前路由签名只有：

```text
Request
GatewayChatRequest
LLMClientDep
TraceIdDep
```

没有：

```text
ApiKeyDep
CurrentUserDep
AuthenticatedClientDep
```

这表示项目当前没有把“调用方身份”作为路由执行的前提。

### 8.3 请求模型接受任意模型和超长覆盖

我们实际跑了 Python 验证：

```python
from ai_engine.api.v1.chat import GatewayChatRequest

request = GatewayChatRequest(
    prompt="x",
    model="totally-unknown-model",
    system_override="A" * 100000,
)

print(request.model)
print(len(request.system_override))
```

实际结果：

```text
accepted=True
model=totally-unknown-model
override_len=100000
```

这说明 Pydantic 只执行了字段类型和显式约束。

它不知道：

- 哪些模型是允许的；
- 系统提示词最长多少；
- 这个调用方有没有权限；
- 这个模型是否昂贵；
- 这次请求是否超出成本预算。

Pydantic 是数据边界工具，不是安全策略引擎。

### 8.4 错误状态码和错误内容没有形成统一边界

当前未初始化依赖：

```text
HTTP 500
{"detail":"NativeLLMClient 尚未在 lifespan 中初始化"}
```

这证明：

- 错误信息包含内部实现状态；
- 500 这个状态码不一定最准确；
- 客户端能够看到内部组件名。

后续错误边界课程会重新设计：

```text
401：未认证
403：无权限
422：参数结构不合法
429：限流
500：真正未预期的内部错误
503：服务未就绪或依赖暂不可用
```

---

## 9. 运行时验证：CORS 现状

我们使用 ASGITransport 发了一个跨源请求：

```text
GET /health
Origin: https://evil.example
```

实际结果：

```text
200
access-control-allow-origin: https://evil.example
access-control-allow-credentials: true
```

预检请求：

```text
OPTIONS /api/v1/chat/completions/stream
Origin: https://evil.example
Access-Control-Request-Method: POST
```

实际结果：

```text
200
access-control-allow-origin: https://evil.example
access-control-allow-credentials: true
access-control-allow-methods:
DELETE, GET, HEAD, OPTIONS, PATCH, POST, PUT, QUERY
```

这段结果能说明什么？

能说明：

- 当前中间件允许任意 Origin 的跨源访问；
- 当前允许的方法范围很宽；
- 当前允许 credentials；
- 当前 `/health` 也受到全局 CORS 配置影响；
- 当前没有一个明确的受信任 Origin 白名单。

不能说明什么？

不能说明：

- CORS 已经实现认证；
- 非浏览器客户端不能访问；
- API Key 已经安全；
- 当前已经存在可被窃取的 Cookie 会话。

当前项目还没有 Cookie 会话，所以“credentials + 任意 Origin”的即时风险可能受限；但配置本身是错误的，一旦未来引入 Cookie 认证，就会变成安全漏洞。

---

## 10. 威胁模型表

现在可以把前面的内容收敛成一张表。

| 风险 | 资产 | 攻击者 | 边界 | 当前现状 | 控制措施 |
| --- | --- | --- | --- | --- | --- |
| 匿名刷接口 | 额度、可用性 | 匿名调用方 | 客户端 → FastAPI | 无认证依赖 | API Key/JWT、401、限流 |
| 换用未授权模型 | 成本、行为 | 合法恶意调用方 | 请求 → 业务 | `model` 自由字符串 | 模型白名单、403 |
| 覆盖系统提示词 | 行为约束 | 合法恶意调用方 | 请求 → 业务 | `system_override` 无权限和长度限制 | 字段限制、权限策略、审计 |
| 任意 Origin 访问 | 浏览器数据、响应 | 恶意网页 | 浏览器 → FastAPI | `*` + credentials，回显任意 Origin | Origin 白名单 |
| 上游 Key 泄露 | 上游账号 | 运维/攻击者 | 应用 → 配置/日志 | SecretStr 存在，脱敏未闭环 | 日志脱敏、轮换、扫描 |
| 错误信息泄露 | 内部实现 | 任意调用方 | 应用 → 客户端 | detail 和 `str(exc)` 可直出 | 稳定错误码、trace_id、日志分层 |
| 成本放大 | 额度、可用性 | 任意调用方 | 请求 → 上游 | 输入限制不完整，TokenGuard 未完成 | Token、请求体、并发、频率限制 |
| trace 污染 | 日志、审计 | 任意调用方 | Header → 日志 | 客户端 Header 直接采用 | 格式校验、长度限制、生成策略 |
| 上游异常透传 | 可用性、响应 | 上游服务 | 上游 → 本服务 | 异常可能进入 SSE error | 规范错误映射、超时、重试 |

这里的每一行，都可以对应后面的一节课。

---

## 11. 常见误解

### 误解一：有了 CORS 就有认证

错误。

CORS 决定浏览器是否允许读取跨源响应。

它不负责验证调用方身份。

### 误解二：有了 SecretStr 就不会泄露密钥

错误。

SecretStr 主要防止代表值和默认序列化直接显示密钥。

主动调用：

```python
get_secret_value()
```

仍然可以拿到明文。

如果日志、异常、请求体或响应把它带出去，SecretStr 不能阻止。

### 误解三：Pydantic 校验通过，就说明请求安全

错误。

Pydantic 能验证：

```text
类型
长度
格式
必填
```

它不能自动知道：

```text
这个调用方有没有权限
这个模型是否允许
这个租户是否超额
```

### 误解四：项目有 TokenBudgetGuard，就说明有成本控制

错误。

当前代码里：

```python
# TODO 3: 校验 prompt_tokens + max_completion_tokens 是否超过限制
pass
```

说明这个组件还没有完整执行预算校验。

“组件存在”和“控制生效”是两件事。

### 误解五：返回 500 就说明请求被认证拦住了

错误。

500 可能是：

```text
依赖未初始化
代码异常
上游异常
配置错误
```

认证失败应该返回 401，而不是让请求因为没有初始化客户端而 500。

---

## 12. 标准做法与项目现状

| 维度 | 标准做法 | 项目现状 |
| --- | --- | --- |
| 入口身份 | 明确认证依赖，缺失凭据返回 401 | 没有入口认证 |
| 授权 | 默认拒绝，按调用方、租户、模型判断 | `model` 是自由字符串 |
| 系统提示词 | 系统控制，限制覆盖权限 | `system_override` 可覆盖 |
| CORS | 明确 Origin、Method、Header 白名单 | 任意 Origin、宽泛 Method |
| Secret | SecretStr + 脱敏 + 轮换 + 日志防护 | SecretStr 已有，masked 未调用 |
| 成本 | Token、请求体、并发、频率共同限制 | TokenGuard 尚未完成 |
| 错误 | 稳定错误码 + trace_id | 部分内部信息直出 |
| 追踪 | 服务端可信 trace 策略 | 客户端 Header 直接采用 |

需要区分两类结论：

```text
FastAPI 保证：
    请求体按模型解析
    参数类型和显式约束生效
    依赖注入按声明执行

FastAPI 不保证：
    调用方已认证
    调用方有授权
    模型名安全
    系统提示词不可覆盖
    错误信息已脱敏
```

---

## 13. 后面的课程怎么接上

本课只是建立地图。

后面的课程会逐个处理：

### 第 2 课：API 认证

解决：

```text
调用方是谁？
未认证为什么应在进入业务前返回 401？
SSE 已经返回 200 后为什么不能再改状态码？
```

### 第 3 课：授权

解决：

```text
认证通过后，允许调用哪些模型？
system_override 谁能用？
租户额度如何隔离？
403 和 422 怎么区分？
```

### 第 4 课：CORS 和 CSRF

解决：

```text
Origin 如何判断？
OPTIONS 预检发生了什么？
为什么 CORS 不是认证？
Cookie 认证和 Bearer Token 的 CSRF 风险有什么不同？
```

### 第 5 课：Secret 生命周期

解决：

```text
Key 如何加载、脱敏、轮换？
SecretStr 的边界在哪里？
.env、日志、异常如何避免泄露？
```

### 第 6 课：错误脱敏

解决：

```text
401、403、422、429、500、503 如何选择？
流式错误如何表达？
如何把完整异常留在日志，把安全信息返回给客户端？
```

---

## 本课核心结论

1. 威胁建模的顺序是“资产 → 攻击者 → 信任边界 → 威胁 → 控制”，不是“看到问题就加配置”。
2. 上游大模型 Key 只证明本服务能访问上游，不证明入口调用方已经认证。
3. `model` 和 `system_override` 是控制面输入，危险程度高于普通 Prompt 内容。
4. CORS 是浏览器安全机制，不是 API 认证，也不能阻止 curl 或服务端脚本。
5. `SecretStr` 只能降低意外展示风险，不能保证完整密钥生命周期安全。
6. Pydantic 只验证字段类型和显式约束，不会自动执行认证、授权或成本策略。
7. `TokenBudgetGuard` 当前存在但预算校验未完成，不能作为已生效的成本控制。
8. 错误响应、日志、响应头都是信任边界，必须区分对外信息和对内信息。
9. 客户端传入的 `X-Trace-ID` 是不可信输入，不能无条件当作可信审计标识。
10. 本项目当前最优先的风险是：入口无认证、模型无白名单、系统提示词可覆盖、CORS 过宽、错误信息泄露和成本控制不足。

---

## 验收问题

请按编号回答。尽量写出理由和对应的项目位置，不要只写名词。

1. 为什么“项目里有 `llm_api_key`”不能证明“入口接口已经有认证”？请分别说明客户端到本服务、本服务到上游模型这两个方向。

2. 列出这个项目的至少 4 个安全资产，以及至少 3 条信任边界。每条边界说明一个可能被攻击的输入。

3. `SecretStr` 能防住什么？不能防住什么？为什么 `masked_api_key` 定义了但没有调用，不能算作完整的脱敏链路？

4. `model` 是自由字符串、`system_override` 没有长度和权限限制，这两者分别会造成什么安全问题？各举一个具体后果。

5. （验证型）请描述如何用 `ASGITransport` 验证 `Origin: https://evil.example` 时 `GET /health` 的 CORS 行为；说明应该观察哪些响应头，以及这个实验能证明什么、不能证明什么。

6. 观察到一个 `GatewayChatRequest` 能接受 `model="totally-unknown-model"` 和长度为 100000 的 `system_override`，这说明 Pydantic 已经完成了什么校验，又没有完成什么安全校验？

7. 如果 `TokenBudgetGuard.validate_budget_or_raise()` 当前实际上执行 `pass`，为什么不能把它写进“项目已完成的成本控制”？你会用什么实验验证它没有生效？

8. 未带认证的 POST 请求如果因为 lifespan 未启动而返回 500，为什么这不能证明接口有认证？在加入认证后，这个请求应该在哪一步返回什么状态码？

9. SSE 已经发送第一帧 `200` 后，如果上游发生异常，为什么不能把 HTTP 状态码改成 401、403 或 500？正确做法应该是什么？

10. 请为“匿名调用方消耗上游额度”写一条最小威胁模型记录，包含：资产、攻击者、信任边界、威胁、当前现状、控制措施、验证方式。

## 用户（补充说明）

直接写入文档，我不回答了。

## 助手（课程说明）

本文按要求作为“仅讲解，未批改”版本保存。验收问题保留，后续复习时可以直接自测；本课不伪造用户作答或批改结果。
