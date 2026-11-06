# Pydantic 校验器、ValidationError 与 ConfigDict

> 本文逐字转录自原始课程对话，只添加角色标题和来源信息，未改写、删减或二次总结。
>
- 返回：[课程原文索引](README.md)
- 原始消息序号：`1254`、`1259`、`1266`、`1308`

## 用户（原始消息 1254）

继续

## 助手（原始消息 1259）

**Pydantic 第二段：校验器、`ValidationError` 与 `ConfigDict`**

这一段解决三个问题：

```text
字段格式对了，业务上是否合法？
多个字段之间的关系是否合法？
模型如何控制未知字段、别名、可变性和赋值？
```

**1. `field_validator` 管单字段或字段组**

当前代码：

```python
@field_validator("source_character", "target_character", mode="before")
@classmethod
def strip_whitespace(cls, v: object) -> object:
    if isinstance(v, str):
        return v.strip().strip("《》“”\"'")
    return v
```

它同时处理两个字段。

`mode="before"` 表示在 Pydantic 完成类型校验之前执行：

```text
原始输入
  ↓
strip_whitespace
  ↓
类型校验、min_length 校验
  ↓
模型实例
```

所以：

```python
" “唐格拉尔” "
```

先变成：

```python
"唐格拉尔"
```

再接受 `NonEmptyStr` 的长度检查。

如果使用 `mode="after"`，则输入已经通过类型检查，拿到的是 `str` 等确定类型：

```python
@field_validator("source_character", mode="after")
@classmethod
def validate_name(cls, value: str) -> str:
    if value == "未知":
        raise ValueError("人物姓名不能为未知")
    return value
```

两者用途不同：

- `before`：清洗、转换、兼容不同输入格式。
- `after`：基于已经确定类型的业务校验。

**2. 校验器必须是纯函数**

校验器应该只做确定性的数据检查或转换：

```python
if isinstance(v, str):
    return v.strip()
return v
```

不要在 validator 中：

- 调用数据库。
- 请求外部 API。
- 写日志文件。
- 发消息。
- 执行有副作用的操作。
- 使用异步客户端。

校验器可能在模型构造、测试、FastAPI 请求解析等不同场景被调用。带副作用的校验器会让行为难以预测。

**3. 不要在校验器里抛 `HTTPException`**

错误写法：

```python
from fastapi import HTTPException

@field_validator("prompt")
@classmethod
def validate_prompt(cls, value: str) -> str:
    if not value:
        raise HTTPException(status_code=400, detail="prompt 不能为空")
    return value
```

Pydantic 模型不应该依赖 FastAPI。正确方式是抛 `ValueError`：

```python
@field_validator("prompt")
@classmethod
def validate_prompt(cls, value: str) -> str:
    if not value:
        raise ValueError("prompt 不能为空")
    return value
```

FastAPI 会把 Pydantic 的 `ValidationError` 转成 `422 Unprocessable Entity`。模型层保持与 Web 框架解耦。

**4. `model_validator(mode="after")` 管跨字段关系**

当前代码：

```python
@model_validator(mode="after")
def check_not_self_relation(self) -> "CharacterRelation":
    if self.source_character == self.target_character:
        raise ValueError(f"人物关系不能指向自身：{self.source_character}")
    return self
```

执行时机是：

```text
source_character 校验完成
target_character 校验完成
relation_type 校验完成
evidence_quote 校验完成
  ↓
check_not_self_relation
```

因此它能看到所有字段：

```python
self.source_character
self.target_character
```

另一个例子：

```python
@model_validator(mode="after")
def check_high_risk_reason(self) -> "HumanApprovalAction":
    if self.risk_level == "high" and len(self.reason) < 10:
        raise ValueError("高风险操作必须提供至少 10 个字符的详细审批原因")
    return self
```

这是两个字段之间的关系：

```text
risk_level + reason
```

单字段 `Field(min_length=10)` 无法表达“只有 high 风险才要求长度至少 10”，所以必须放在模型级校验器中。

`mode="after"` 的校验器必须返回 `self`。如果忘记返回，模型构造会失败。

**5. `model_validator(mode="before")` 管原始对象**

```python
@model_validator(mode="before")
@classmethod
def normalize_input(cls, data: object) -> object:
    if isinstance(data, dict):
        ...

    return data
```

它在任何字段校验之前执行，拿到的是原始 `dict` 或其他输入对象。

适合：

- 兼容旧版字段名。
- 补全外部数据的默认结构。
- 对整体输入做一次预清洗。

不适合：

- 依赖已经完成类型校验的字段。
- 写复杂的业务逻辑。

**6. 校验执行顺序**

假设模型字段是：

```python
prompt: str
model: str
```

大致顺序是：

```text
model_validator(mode="before")
  ↓
prompt field_validator(mode="before")
  ↓
prompt 类型和约束校验
  ↓
prompt field_validator(mode="after")
  ↓
model field_validator(mode="before")
  ↓
model 类型和约束校验
  ↓
model field_validator(mode="after")
  ↓
model_validator(mode="after")
  ↓
模型实例
```

实际实现会按照 Pydantic 的字段展开和元数据规则执行，但这个顺序足以理解 `before` 和 `after` 的区别。

**7. `ValidationError` 的结构**

测试中：

```python
with pytest.raises(ValidationError) as exc_info:
    ChapterExtractionResult.model_validate_json(invalid_json)
```

得到的异常可以这样读取：

```python
exc = exc_info.value

for error in exc.errors():
    print(error["type"])
    print(error["loc"])
    print(error["msg"])
```

典型错误结构：

```python
{
    "type": "string_too_short",
    "loc": ("relations", 0, "evidence_quote"),
    "msg": "String should have at least 1 character",
    "input": "",
}
```

几个常见类型：

```text
missing              缺少必填字段
string_too_short     字符串太短
string_too_long      字符串太长
literal_error        Literal 值不合法
extra_forbidden      出现未声明字段
frozen_instance      修改 frozen 模型
value_error          自定义 ValueError
```

`loc` 是定位错误最重要的信息：

```python
("relations", 0, "source_character")
```

含义是：

```text
relations 列表第 0 个元素
source_character 字段
```

这非常适合直接反馈给 LLM：

```text
relations[0].source_character 不合法
```

**8. `ValueError` 和 `PydanticCustomError`**

简单业务错误：

```python
raise ValueError("人物关系不能指向自身")
```

错误类型会归为 `value_error`。

如果希望机器可识别的错误码：

```python
from pydantic_core import PydanticCustomError

raise PydanticCustomError(
    "self_relation",
    "人物关系不能指向自身：{name}",
    {"name": self.source_character},
)
```

这样 `errors()` 中会得到：

```python
{
    "type": "self_relation",
    "loc": (...),
    "msg": "人物关系不能指向自身：唐泰斯",
}
```

后台系统可以据此做错误码映射，而不是解析自然语言字符串。

**9. `ConfigDict(extra="forbid")`**

```python
model_config = ConfigDict(extra="forbid")
```

未知字段：

```python
CharacterRelation(
    source_character="A",
    target_character="B",
    relation_type="enemy",
    evidence_quote="证据",
    hallucinated_field="模型编出来的",
)
```

会报：

```text
extra_forbidden
```

三种选择：

```python
extra="ignore"   # 默认，静默丢弃未知字段
extra="allow"    # 保留未知字段
extra="forbid"   # 拒绝未知字段
```

处理 LLM 输出时通常推荐 `forbid`：

```text
LLM 多编造一个字段
  ↓
立刻校验失败
  ↓
要求模型重新生成
```

如果使用 `ignore`，模型可能以为字段生效了，实际数据被悄悄丢弃。

注意：`extra` 配置不会自动传递到所有嵌套模型。父模型和子模型都需要各自设置。

**10. `frozen=True` 的边界**

```python
model_config = ConfigDict(frozen=True)
```

它会阻止：

```python
action.top_k = 99
```

抛出：

```text
frozen_instance
```

但它只是浅层不可变。当前：

```python
class SystemPromptTemplate(BaseModel):
    model_config = ConfigDict(frozen=True)
    objectives: list[str]
```

以下操作仍然可能成功：

```python
template.objectives.append("新任务")
```

因为 `frozen=True` 禁止的是给字段重新赋值：

```python
template.objectives = []   # 被拒绝
```

但不会禁止修改列表内部。

如果需要更强的不可变性，可以使用不可变容器：

```python
objectives: tuple[str, ...] = Field(..., min_length=1)
```

这样就没有 `.append()` 方法。字典字段仍然需要额外处理。

**11. 赋值时默认不会重新校验**

即使没有 `frozen=True`：

```python
class Item(BaseModel):
    count: int = Field(ge=0)

item = Item(count=1)
item.count = -100
```

默认情况下，这个赋值可能不会重新执行 `ge=0` 校验。构造时校验通过，不代表后续赋值也校验。

如果需要验证赋值：

```python
model_config = ConfigDict(validate_assignment=True)
```

这样：

```python
item.count = -100
```

会触发 `ValidationError`。

- 对外部输入：构造时校验。
- 对内部可变模型：考虑 `validate_assignment=True`。
- 希望完全禁止重新赋值：考虑 `frozen=True`。

**12. `alias`、`populate_by_name` 和序列化**

当前：

```python
chapter_index: Annotated[int, Field(ge=1, alias="chapterIndex")]
```

默认情况下，Pydantic 优先接受别名：

```python
ChapterExtractionResult(chapterIndex=1, ...)
```

开启：

```python
model_config = ConfigDict(populate_by_name=True)
```

后，也接受 Python 字段名：

```python
ChapterExtractionResult(chapter_index=1, ...)
```

在较新的 Pydantic 中，也可以更明确地配置：

```python
model_config = ConfigDict(
    validate_by_alias=True,
    validate_by_name=True,
)
```

区分：

```python
Field(alias="chapterIndex")
```

同时影响验证名称和序列化名称。

```python
Field(validation_alias="chapterIndex", serialization_alias="chapter_index")
```

允许输入和输出使用不同名称。

默认：

```python
result.model_dump()
# chapter_index

result.model_dump(by_alias=True)
# chapterIndex
```

这就是当前测试中输出给前端驼峰字段的方式。

**13. 当前模型的设计评价**

`CharacterRelation`：

```python
extra="forbid"
```

适合约束 LLM 输出。

`strip_whitespace(mode="before")`

适合清洗姓名中的空格和引号。

`check_not_self_relation(mode="after")`

适合跨字段业务规则。

`ChapterExtractionResult`：

```python
extra="forbid"
populate_by_name=True
```

同时支持 LLM 输出的驼峰别名和 Python 内部的下划线字段名，设计合理。

`BaseAgentAction`：

```python
extra="forbid", frozen=True
```

配置会被子类继承，因此 `VectorSearchAction` 等动作也受到约束。

`SystemPromptTemplate`：

```python
frozen=True
```

只能保证字段不能重新赋值，不能保证列表内容不可变。这是后续需要留意的点。

**本段掌握标准**

你应该能回答：

1. 什么逻辑应该放在 `mode="before"`，什么逻辑应该放在 `mode="after"`？
2. 为什么 `model_validator(mode="after")` 必须返回 `self`？
3. 为什么跨字段规则不能只写 `Field(min_length=...)`？
4. `ValidationError.errors()` 中的 `loc` 如何定位嵌套列表字段？
5. `extra="ignore"` 和 `extra="forbid"` 对 LLM 输出有什么本质区别？
6. `frozen=True` 为什么不能阻止 `template.objectives.append(...)`？
7. `model_dump()` 和 `model_dump(by_alias=True)` 为什么输出不同？

下一段进入 **序列化、JSON Schema、判别联合类型和 `TypeAdapter`**。

## 用户（原始消息 1266）

1. 约束和校验之前的逻辑应该放在 mode="before" 比如 字段去空格之类的，约束校验之后的逻辑应该放在 mode="after" 例如每个字段单独校验通过后 ，还需校验字段之间的关系 2. 不返回 self 就会导致类构造失败 3. 因为 Field 只对当前字段生效 4. 不知道 5. ignore 本质是忽略，因此大模型根本不知道自己输出的字段实际是被抛弃了，forbid 是严禁出现不应该出现的字段，大模型就能够清晰知道，它的输出是不合法的 6. frozen 只能保证当前字段不被重新赋值，但对于引用类型的数据，可以通过引用修改类型本身，字段本身不会改变，所以阻止不了 7. 因为 model_dump 默认不使用 alias 加上 by_alias 就会主动使用 alias 所以结果可能不同

## 助手（原始消息 1308）

**批改与补充**

1. 基本正确，但要区分两个装饰器：

   ```python
   field_validator(mode="before")  # 单个字段：清洗、转换
   field_validator(mode="after")   # 单个字段：基于确定类型进行校验
   model_validator(mode="after")   # 多字段：业务关系校验
   ```

   当前“人物不能指向自己”和“高风险必须提供详细原因”都属于跨字段规则，应该使用 `model_validator`，不是 `field_validator(mode="after")`。

2. 更准确的说法不是“类构造一定失败”。在当前 `pydantic 2.14.1` 中实测：

   ```python
   class M(BaseModel):
       x: int

       @model_validator(mode="after")
       def check(self):
           pass
   ```

   通过构造调用 `M(x=1)` 时，Pydantic 会给出警告，但仍然可能返回 `M` 实例。

   更危险的是：

   ```python
   result = M.model_validate({"x": 1})
   ```

   此时 `result` 可能是 `None`，因为 `model_validator(mode="after")` 的返回值会成为最终校验结果。

   所以必须写成：

   ```python
   @model_validator(mode="after")
   def check(self) -> "M":
       ...
       return self
   ```

   这不是形式要求，而是保证所有验证入口都得到正确模型实例。

3. 正确。`Field` 是针对字段本身的约束，无法表达“只有 `risk_level == "high"` 时，`reason` 才必须至少 10 个字符”这种跨字段条件。

4. 这一点需要补上。`ValidationError.errors()` 返回结构化错误列表：

   ```python
   try:
       ChapterExtractionResult.model_validate_json(invalid_json)
   except ValidationError as exc:
       for error in exc.errors():
           print(error)
   ```

   典型字段错误：

   ```python
   {
       "type": "string_too_short",
       "loc": ("relations", 0, "evidence_quote"),
       "msg": "String should have at least 1 character",
       "input": ""
   }
   ```

   `loc` 表示错误位置：

   ```text
   relations[0].evidence_quote
   ```

   当前“人物关系不能指向自身”是模型级校验，实测错误位置是：

   ```python
   {
       "type": "value_error",
       "loc": ("relations", 0),
       "msg": "Value error, 人物关系不能指向自身：唐泰斯",
       "input": {...},
       "ctx": {"error": ValueError(...)}
   }
   ```

   这是因为错误发生在整个 `CharacterRelation` 模型上，而不是某一个字段上。

   `.errors()` 是给程序处理的：

   ```python
   error["type"]
   error["loc"]
   error["msg"]
   error["input"]
   ```

   `str(exc)` 是给人阅读的完整错误文本。API 和 LLM 重试流程应该优先使用 `.errors()`，因为可以精确定位。

5. 方向正确，但要补充：Pydantic 不会自动把错误告诉 LLM。

   发生 `extra_forbidden` 后，需要你的编排代码执行：

   ```text
   Pydantic 校验失败
     ↓
   读取 errors()
     ↓
   把 loc、type、msg 组织成反馈
     ↓
   重新调用或修复模型输出
   ```

   如果只记录服务端日志，大模型并不知道自己生成了非法字段。

6. 正确。更精确地说：`frozen=True` 阻止字段绑定被替换，但不阻止字段指向的可变对象被原地修改。

7. 正确。`model_dump()` 默认使用 Python 字段名；`model_dump(by_alias=True)` 才使用序列化别名。若配置了 `serialization_alias`，开启 `by_alias=True` 时优先使用该名称。

现在下一段可以进入：**`model_dump`、JSON Schema、判别联合类型、`TypeAdapter` 和 FastAPI 响应序列化**。

