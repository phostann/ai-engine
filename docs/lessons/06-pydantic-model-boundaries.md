# Pydantic 模型边界、字段声明与约束

> 本文逐字转录自原始课程对话，只添加角色标题和来源信息，未改写、删减或二次总结。
>
- 返回：[课程原文索引](README.md)
- 原始消息序号：`1079`、`1084`、`1166`、`1178`、`1203`、`1213`、`1247`

## 用户（原始消息 1079）

安排下一课内容

## 助手（原始消息 1084）

下一课按项目现有模型来设计：**Pydantic v2 的请求/响应边界**。内容包括模型校验、字段约束、类型转换、嵌套模型、别名、序列化、配置和错误处理，并结合当前 schema 逐个说明。

## 助手（原始消息 1166）

下一课安排为：**Pydantic v2 工程化建模与 FastAPI 数据边界**

按项目锁定的版本讲解：`pydantic 2.14.1`。这不是再泛读一遍 API，而是围绕当前 schema 解释“为什么要这样建模”。

**课程目标**

学完后应该能独立完成：

- 为 FastAPI 请求设计输入模型。
- 为 LLM 结构化输出设计可校验模型。
- 区分字段校验和跨字段校验。
- 控制未知字段、别名、默认值和不可变约束。
- 正确完成 JSON 解析、模型校验和序列化。
- 使用 `TypeAdapter` 校验联合类型。
- 看懂 `ValidationError` 并定位错误字段。

**课程内容**

1. **模型边界**

   - `dict`、dataclass、`BaseModel` 的区别。
   - 输入模型、内部领域模型、输出模型的职责。
   - 为什么不要把一个模型同时用于所有场景。

   对应代码：`GatewayChatRequest`

2. **字段声明与约束**

   - `BaseModel`、`Field`、`Annotated`。
   - `min_length`、`max_length`、`ge`、`le`。
   - 必填字段、默认值、`default_factory`。
   - 为什么不能写 `relations: list = []`。

   对应代码：`NonEmptyStr`、`ConfidenceScore`、`SystemPromptTemplate`

3. **类型转换与严格校验**

   - Pydantic 默认的类型转换。
   - `Literal` 如何限制枚举值。
   - `str`、`int`、`float` 的宽松和严格模式。
   - 什么时候应该开启 `strict=True`。

4. **字段校验器**

   - `field_validator(mode="before")`：先清洗，再校验。
   - `field_validator(mode="after")`：在类型校验完成后检查。
   - 为什么要返回清洗后的值。
   - 为什么 validator 要写成 `classmethod`。

   对应代码：`strip_whitespace`

5. **跨字段校验**

   - `model_validator(mode="after")`。
   - 为什么必须返回 `self`。
   - 单字段约束和模型级业务约束的区别。
   - 错误信息如何提供给 LLM 进行重试。

   对应代码：`check_not_self_relation`、`check_high_risk_reason`

6. **`ConfigDict` 的核心配置**

   - `extra="forbid"`：拒绝未声明字段，适合约束 LLM 输出。
   - `frozen=True`：禁止重新赋值，但它只是浅层不可变。
   - `populate_by_name` 与新版 `validate_by_name` 的关系。
   - `alias`、`validation_alias`、`serialization_alias` 的区别。

   会特别说明当前 `SystemPromptTemplate` 的 `frozen=True` 并不能阻止 `objectives.append(...)`。

7. **嵌套模型与错误定位**

   - 模型嵌套时如何递归校验。
   - `ValidationError.errors()` 中的 `loc`、`type`、`msg`。
   - 如何把错误转成面向 API 客户端的响应。
   - FastAPI 为什么自动返回 `422`。

   对应代码：`ChapterExtractionResult -> list[CharacterRelation]`

8. **验证、解析与序列化**

   - `model_validate()`。
   - `model_validate_json()`。
   - 属性访问与字典访问的区别。
   - `model_dump()` 与 `model_dump(mode="json")`。
   - `by_alias=True` 如何输出驼峰字段。
   - `model_json_schema()` 如何生成给 LLM 的结构说明。

9. **判别联合类型**

   - `VectorSearchAction | HumanApprovalAction | FinalReplyAction`。
   - `Field(discriminator="action_type")` 如何实现 O(1) 路由。
   - 为什么每个分支的 discriminator 必须唯一。
   - 为什么 `TypeAdapter` 应该在模块级创建一次。

   对应代码：`AGENT_DECISION_ADAPTER`

10. **Pydantic Settings 与普通模型的区别**

    - `BaseSettings` 从环境变量和 `.env` 读取配置。
    - `extra="ignore"` 为什么常用于配置中心。
    - `@lru_cache` 与 Settings 单例的关系。
    - 为什么环境变量读取失败应该在启动阶段暴露。

    对应代码：`Settings`

**课堂练习**

1. 用三个非法 JSON 分别触发字段长度错误、额外字段错误和跨字段错误，并解释 `errors()` 输出。
2. 判断 `frozen=True` 后以下操作是否允许：

   ```python
   template.role_identity = "new"
   template.objectives.append("new")
   ```

3. 为聊天接口拆分 `ChatRequest` 和 `ChatResponse`，说明输入模型和输出模型为什么不能混用。
4. 为 `AgentStepDecision` 增加一个新动作，并验证 discriminator 是否正确路由。
5. 将 `GatewayChatRequest` 的字段错误映射成更友好的 API 错误格式。

**本课验收标准**

你应该能回答：

- 为什么 `extra="forbid"` 对 LLM 输出特别重要？
- `mode="before"` 和 `mode="after"` 分别适合做什么？
- `frozen=True` 为什么不能保证列表字段不可变？
- `alias` 和 `serialization_alias` 有什么区别？
- 为什么 `TypeAdapter` 不应该在请求函数内部反复创建？
- `model_validate_json` 和 `json.loads` 后 `model_validate` 有什么区别？
- FastAPI 接收到非法请求体后为什么自动返回 `422`？

下一轮从第 1、2 部分开始，直接结合 `GatewayChatRequest`、`NonEmptyStr` 和 `ConfidenceScore` 进入实际代码。

## 用户（原始消息 1178）

开始

## 助手（原始消息 1203）

**Pydantic 第一段：模型边界、字段声明与约束**

这一段的重点不是记 API，而是先搞清楚：**哪些数据应该进入模型、在什么位置校验、模型字段如何准确表达业务规则。**

**1. 模型是数据边界，不只是“高级字典”**

普通字典：

```python
payload = {"prompt": "你好", "model": "gpt-4o-mini"}
```

它的问题是：

- 无法保证 `prompt` 一定存在。
- 无法保证 `prompt` 是非空字符串。
- 无法保证长度不超过 2000。
- 无法知道有哪些合法字段。
- 无法在进入业务代码前统一拒绝脏数据。

Pydantic 模型：

```python
class GatewayChatRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=2000)
    model: str = Field(default="gpt-4o-mini")
    system_override: str | None = Field(default=None)
```

它表达的是边界契约：

```text
请求必须是什么结构
哪些字段必填
哪些字段可选
类型是什么
取值范围是什么
缺省值是什么
```

FastAPI 收到请求体后，会先构造 `GatewayChatRequest`，只有校验通过，路由函数才会执行。非法请求会在进入业务逻辑前被拦截，并返回 `422`。

**2. 输入模型、内部模型、输出模型不要混用**

以聊天接口为例：

```text
前端 JSON
  ↓
GatewayChatRequest        输入模型
  ↓
业务处理 / 调用 LLM
  ↓
ChatResponse              输出模型
  ↓
前端 JSON
```

输入模型负责接收外部数据，输出模型负责描述返回数据。即使字段看起来相同，也建议分开，因为它们的生命周期和安全要求不同：

- 输入模型可能需要隐藏密码、限制字符串长度。
- 输出模型可能包含 ID、时间、状态，但不应包含密钥。
- 内部模型可能包含连接池、数据库会话等不可序列化对象。

当前 `GatewayChatRequest` 就是输入模型。它只应承载请求数据，不应该加入 `llm_client`、`trace_id` 这类运行时对象。

**3. 必填字段与默认字段**

```python
class GatewayChatRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=2000)
    model: str = Field(default="gpt-4o-mini")
    system_override: str | None = Field(default=None)
```

`Field(...)` 中的 `...` 表示必填：

```python
GatewayChatRequest(model="gpt-4o-mini")
# 缺少 prompt，报错

GatewayChatRequest(prompt="你好")
# model 和 system_override 使用默认值
```

`system_override: str | None = None` 表示：

```text
允许字段缺失
允许字段值为 null
允许字段值为字符串
```

这与：

```python
system_override: str = None
```

不同。后者在类型检查层面是错误的，因为 `None` 不是 `str`。Pydantic 可能出于转换规则接受它，但模型语义不清晰。

**4. `Field` 约束**

```python
prompt: str = Field(..., min_length=1, max_length=2000)
```

这里包含三类信息：

- `...`：必填。
- `min_length=1`：空字符串不合法。
- `max_length=2000`：防止超大输入。

需要注意：`min_length=1` 只能保证字符串长度至少为 1，不能保证去掉空白后仍然有内容。

```python
GatewayChatRequest(prompt="   ")
```

会通过长度校验，因为字符串长度是 3。若业务要求“不能全是空白”，需要额外校验：

```python
@field_validator("prompt", mode="before")
@classmethod
def strip_prompt(cls, value: object) -> object:
    if isinstance(value, str):
        return value.strip()
    return value
```

再加上：

```python
prompt: str = Field(..., min_length=1, max_length=2000)
```

清洗顺序很重要：先用 `before` 去掉空白，再让 `min_length` 检查清洗后的结果。

**5. `Annotated` 和可复用约束类型**

当前项目定义了：

```python
type NonEmptyStr = Annotated[str, Field(min_length=1, description="非空字符串")]
type ConfidenceScore = Annotated[float, Field(ge=0.0, le=1.0)]
```

`Annotated` 的含义是：

```text
底层类型仍然是 str / float
附加的 Field 元数据是约束和文档
```

它可以复用：

```python
source_character: NonEmptyStr
target_character: NonEmptyStr
chapter_title: NonEmptyStr
```

等价于重复写：

```python
source_character: str = Field(min_length=1, description="非空字符串")
```

但复用类型有三个好处：

- 多处规则保持一致。
- 字段含义更容易阅读。
- 修改约束时只改一处。

`ConfidenceScore` 的约束是：

```python
0.0 <= confidence <= 1.0
```

Pydantic 会拒绝：

```python
confidence = -0.1
confidence = 1.5
```

**6. `Literal` 是有限枚举，不是普通字符串**

```python
relation_type: Literal["ally", "enemy", "mentor", "family", "unknown"]
```

它只允许这五种值。相比：

```python
relation_type: str
```

使用 `Literal` 后：

- OpenAPI 文档会展示可选值。
- IDE 能做补全。
- 非法值在进入业务逻辑前就被拒绝。
- 不需要手写 `if value not in ...`。

```python
CharacterRelation(
    source_character="A",
    target_character="B",
    relation_type="friend",
    evidence_quote="...",
)
```

会校验失败，因为 `"friend"` 不在 Literal 中。

**7. `default_factory` 为什么必须使用**

不要这样写：

```python
relations: list[CharacterRelation] = []
```

列表是可变对象。这个默认值可能在多个模型实例之间共享，导致一个对象修改列表，另一个对象也受到影响。

正确写法：

```python
relations: list[CharacterRelation] = Field(default_factory=list)
```

`default_factory=list` 的意思是：每次创建模型实例时调用一次 `list()`，生成新的空列表。

同样：

```python
constraints: list[str] = Field(default_factory=list)
```

**8. 嵌套模型与递归校验**

```python
class CharacterRelation(BaseModel):
    ...


class ChapterExtractionResult(BaseModel):
    relations: list[CharacterRelation] = Field(default_factory=list)
```

构造时，Pydantic 会对每个元素递归校验：

```python
ChapterExtractionResult(
    chapter_index=1,
    chapter_title="马赛港",
    summary="这是一个足够长的章节梗概内容。",
    relations=[
        {
            "source_character": "唐格拉尔",
            "target_character": "唐泰斯",
            "relation_type": "enemy",
            "evidence_quote": "原文证据",
        }
    ],
)
```

`relations` 中的字典会被转换成 `CharacterRelation` 实例，而不是原样保留为字典。

**9. `model_validate_json` 与 `model_validate`**

当前测试使用：

```python
result = ChapterExtractionResult.model_validate_json(raw_llm_output)
```

适合原始 JSON 字符串，直接交给 Pydantic：

```text
JSON 字符串
  ↓
JSON 解析
  ↓
类型校验
  ↓
模型实例
```

也可以先手动解析：

```python
data = json.loads(raw_llm_output)
result = ChapterExtractionResult.model_validate(data)
```

但直接使用 `model_validate_json` 通常少一次中间步骤，也更容易保持错误定位的上下文。

需要区分：

```python
model_validate_json()  # 输入是 JSON 文本
model_validate()       # 输入是 Python 对象，例如 dict
```

**10. `model_construct` 不能用于不可信输入**

```python
obj = Model.model_construct(...)
```

它会绕过校验，通常只适合内部已经确定可信的数据。处理 LLM 输出、HTTP 请求体、配置文件时，不应使用它来“避免报错”。

**11. 字段默认值不等于业务默认规则**

```python
confidence: ConfidenceScore = 0.9
```

这表示模型输入没提供 `confidence` 时使用 `0.9`。它不会自动检查“用户输入的默认值是否合理”，也不会表达业务逻辑。

如果默认值本身也要经过校验，需要关注 `validate_default` 配置。默认情况下，Pydantic 对默认值的校验策略与字段声明有关；不要把业务约束完全寄托在默认值上。

**12. 本段要记住的模型设计原则**

```text
外部输入先建模
字段类型要准确
业务范围用 Field 表达
固定枚举用 Literal
可变默认值用 default_factory
嵌套对象递归建模
不可信数据必须走 validate
```

下一段会进入：

```text
field_validator
model_validator
ValidationError
ConfigDict
extra="forbid"
frozen=True
alias
```

那时我们会解释当前项目中的：

```python
strip_whitespace()
check_not_self_relation()
check_high_risk_reason()
```

是怎样把“格式正确”提升为“业务上合法”的。

## 用户（原始消息 1213）

进入之前我有个疑问 type NonEmptyStr = Annotated[str, Field(min_length=1, description="非空字符串")] 如果要保证字段不鞥你是 "    " 这种，是不是要在每次使用的时候 搭配 field_validator("prompt", mode="before")  那不是很麻烦

## 助手（原始消息 1247）

不需要在每个字段上重复写 `field_validator`。`Annotated` 不仅可以携带 `Field`，还可以携带可复用的校验器或字符串约束。

当前的问题确实存在：

```python
type NonEmptyStr = Annotated[str, Field(min_length=1)]
```

这里的 `min_length=1` 只检查原始字符串长度：

```python
"   ".model_validate(...)  # 长度为 3，能通过
```

**推荐写法：`StringConstraints`**

```python
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

type NonBlankStr = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1),
    Field(description="去除首尾空白后不能为空"),
]
```

使用时只声明类型：

```python
class GatewayChatRequest(BaseModel):
    prompt: NonBlankStr
```

行为是：

```python
GatewayChatRequest(prompt="  hello  ").prompt
# "hello"

GatewayChatRequest(prompt="   ")
# ValidationError: string_too_short
```

已验证当前 `pydantic 2.14.1` 的执行顺序是先执行 `strip_whitespace`，再检查 `min_length`。

**如果只想拒绝全空白，但保留原字符串**

```python
from typing import Annotated

from pydantic import AfterValidator, BaseModel


def reject_blank(value: str) -> str:
    if not value.strip():
        raise ValueError("不能只包含空白字符")
    return value


type NonBlankStr = Annotated[str, AfterValidator(reject_blank)]


class Request(BaseModel):
    prompt: NonBlankStr
```

此时：

```python
Request(prompt="  hello  ").prompt
# "  hello  "，保留原值

Request(prompt="   ")
# ValidationError: 不能只包含空白字符
```

**当前项目还可以进一步复用“人物名清洗”**

现在项目是：

```python
@field_validator("source_character", "target_character", mode="before")
@classmethod
def strip_whitespace(cls, v: object) -> object:
    if isinstance(v, str):
        return v.strip().strip("《》“”\"'")
    return v
```

如果这种清洗规则以后还会用于更多人物名字段，可以改成可复用类型：

```python
from typing import Annotated

from pydantic import BeforeValidator, Field, StringConstraints


def normalize_character_name(value: object) -> object:
    if isinstance(value, str):
        return value.strip().strip("《》“”\"'")
    return value


type CharacterName = Annotated[
    str,
    BeforeValidator(normalize_character_name),
    StringConstraints(min_length=1),
    Field(description="清洗后非空的人物姓名"),
]
```

然后：

```python
class CharacterRelation(BaseModel):
    source_character: CharacterName
    target_character: CharacterName
```

这样就不用在每个模型、每个字段上重复 validator。

**三种方案如何选择**

- 只要求“不能全是空白”，且希望自动去掉首尾空白：

  ```python
  StringConstraints(strip_whitespace=True, min_length=1)
  ```

- 只要求“不能全是空白”，但必须保留用户原始输入：

  ```python
  AfterValidator(reject_blank)
  ```

- 还需要去除书名号、引号等业务特定字符：

  ```python
  BeforeValidator(normalize_character_name)
  ```

另外，也可以在模型配置中统一开启：

```python
model_config = ConfigDict(str_strip_whitespace=True)
```

但它会作用于模型的所有字符串字段。像 `system_override`、Markdown、代码块这类内容，不应无差别全局清洗，所以用可复用的 `Annotated` 类型通常更精确。

所以你的直觉是对的：当前 `NonEmptyStr` 名字和约束不够准确；推荐改成 `NonBlankStr`，并把清洗、长度约束封装到类型本身。

