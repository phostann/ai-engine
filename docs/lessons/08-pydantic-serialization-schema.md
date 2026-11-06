# Pydantic 序列化、Schema、判别联合与 TypeAdapter

> 本文逐字转录自原始课程对话，只添加角色标题和来源信息，未改写、删减或二次总结。
>
- 返回：[课程原文索引](README.md)
- 原始消息序号：`1315`、`1342`、`1352`、`1366`

## 用户（原始消息 1315）

继续

## 助手（原始消息 1342）

**Pydantic 第三段：序列化、Schema、判别联合与 `TypeAdapter`**

这一段解决两类问题：

```text
模型中的 Python 对象，如何安全地变成 dict / JSON / API 响应？
一个字段可能是多种模型时，如何准确判断它到底是哪一种？
```

**1. `model_dump()` 与 `model_dump_json()`**

当前模型实例：

```python
result = ChapterExtractionResult.model_validate({
    "chapterIndex": 1,
    "chapterTitle": "马赛港",
    "summary": "这是一段超过十个字的正常章节梗概内容。",
})
```

Python 模式：

```python
result.model_dump()
```

输出：

```python
{
    "chapter_index": 1,
    "chapter_title": "马赛港",
    "summary": "这是一段超过十个字的正常章节梗概内容。",
    "relations": [],
    "confidence": 0.9,
}
```

它得到的是 Python 字典，嵌套模型会转成字典，但值不一定能被标准 `json.dumps()` 序列化。例如 `datetime`、`UUID`、`set`、自定义类型等可能仍然保留为 Python 对象。

JSON 兼容字典：

```python
result.model_dump(mode="json")
```

它会把值转换为 JSON 可表达的类型，例如：

```text
datetime  -> ISO 字符串
UUID      -> 字符串
set       -> list
tuple     -> list
```

直接生成 JSON 字符串：

```python
result.model_dump_json(by_alias=True)
```

输出：

```json
{
  "chapterIndex": 1,
  "chapterTitle": "马赛港",
  "summary": "这是一段超过十个字的正常章节梗概内容。",
  "relations": [],
  "confidence": 0.9
}
```

三者关系：

```text
model_dump()             -> Python dict
model_dump(mode="json")  -> JSON 兼容 dict
model_dump_json()        -> JSON 字符串
```

**2. `by_alias` 控制外部字段名**

内部字段名：

```python
chapter_index
chapter_title
```

外部别名：

```python
chapterIndex
chapterTitle
```

默认导出：

```python
result.model_dump()
```

得到：

```python
{"chapter_index": 1, "chapter_title": "..."}
```

使用别名：

```python
result.model_dump(by_alias=True)
```

得到：

```python
{"chapterIndex": 1, "chapterTitle": "..."}
```

当前测试：

```python
frontend_dict = result.model_dump(by_alias=True)
assert frontend_dict["chapterIndex"] == 1
```

就是通过 `by_alias=True` 输出前端需要的驼峰命名。

需要记住：

```text
alias 影响验证名称和序列化名称
by_alias=True 决定导出时是否使用该名称
```

默认 `model_dump()` 不启用别名，因此不能误以为定义了 `alias` 就一定会自动输出驼峰字段。

**3. `validation_alias` 与 `serialization_alias`**

三者区别：

```python
Field(alias="chapterIndex")
```

验证和序列化都使用 `chapterIndex`。

```python
Field(
    validation_alias="chapterIndex",
    serialization_alias="chapter_index",
)
```

输入接受驼峰，输出使用下划线。

```python
Field(
    validation_alias="chapter_index",
    serialization_alias="chapterIndex",
)
```

输入接受下划线，输出使用驼峰。

适合外部协议和内部模型命名不一致的场景。

**4. JSON Schema 是模型对外的结构说明**

```python
schema = ChapterExtractionResult.model_json_schema(by_alias=True)
```

典型结构：

```python
{
    "type": "object",
    "properties": {
        "chapterIndex": {...},
        "chapterTitle": {...},
        "summary": {...},
        "relations": {...},
        "confidence": {...},
    },
    "$defs": {
        "CharacterRelation": {...},
        "NonEmptyStr": {...},
        "ConfidenceScore": {...},
    },
}
```

`$defs` 存放可复用或嵌套模型的定义，`$ref` 引用这些定义。

例如 `relations` 可能引用：

```json
{
  "$ref": "#/$defs/CharacterRelation"
}
```

JSON Schema 的用途：

- 给前端生成类型定义。
- 给 LLM 说明结构化输出格式。
- 生成 OpenAPI。
- 工具调用参数校验。
- 约束 Agent 输出的动作结构。

注意：Schema 是“说明书”，不是数据本身。LLM 是否严格遵守，仍取决于模型能力和提示词；最终必须再用 Pydantic 校验。

**5. 为什么需要判别联合类型**

假设 Agent 下一步可能是三种动作：

```python
VectorSearchAction
HumanApprovalAction
FinalReplyAction
```

普通联合类型：

```python
AgentStepDecision = VectorSearchAction | HumanApprovalAction | FinalReplyAction
```

Pydantic 可能需要逐个尝试每个模型，既慢又容易产生模糊错误。

当前代码使用：

```python
type AgentStepDecision = Annotated[
    VectorSearchAction | HumanApprovalAction | FinalReplyAction,
    Field(discriminator="action_type"),
]
```

每个模型都有唯一的 Literal：

```python
class VectorSearchAction:
    action_type: Literal["vector_search"] = "vector_search"

class HumanApprovalAction:
    action_type: Literal["human_approval"] = "human_approval"

class FinalReplyAction:
    action_type: Literal["final_reply"] = "final_reply"
```

Pydantic 先读取：

```json
{"action_type": "vector_search", ...}
```

然后直接选择 `VectorSearchAction` 分支，而不是逐个尝试所有模型。

可以理解为：

```text
action_type = vector_search   -> VectorSearchAction
action_type = human_approval  -> HumanApprovalAction
action_type = final_reply     -> FinalReplyAction
```

这不是简单的字符串判断，Pydantic 还会把生成的 Schema 标记为：

```python
{
    "discriminator": {
        "propertyName": "action_type",
        "mapping": {
            "vector_search": "#/$defs/VectorSearchAction",
            "human_approval": "#/$defs/HumanApprovalAction",
            "final_reply": "#/$defs/FinalReplyAction",
        },
    }
}
```

**6. discriminator 的硬性要求**

第一，所有分支都必须声明同一个 discriminator 字段：

```python
action_type
```

第二，每个分支的值必须唯一：

```python
Literal["vector_search"]
Literal["human_approval"]
Literal["final_reply"]
```

不能两个分支都使用：

```python
Literal["search"]
```

否则无法判断应该选择哪个模型。

第三，输入中必须能提供 discriminator。即使类中定义了：

```python
action_type: Literal["vector_search"] = "vector_search"
```

直接构造 `VectorSearchAction` 时可以使用默认值，但通过联合类型解析时，通常仍应明确提供 `action_type`。否则 Pydantic 无法先确定分支，可能报：

```text
union_tag_not_found
```

错误值则会报：

```text
union_tag_invalid
```

**7. `TypeAdapter` 的作用**

`AgentStepDecision` 是一个类型别名，不是继承 `BaseModel` 的类：

```python
type AgentStepDecision = Annotated[
    VectorSearchAction | HumanApprovalAction | FinalReplyAction,
    Field(discriminator="action_type"),
]
```

因此不能写：

```python
AgentStepDecision.model_validate_json(...)
```

`TypeAdapter` 可以为普通类型、联合类型、列表、字典等提供统一的验证和序列化能力：

```python
AGENT_DECISION_ADAPTER: TypeAdapter[AgentStepDecision] = TypeAdapter(
    AgentStepDecision
)
```

使用：

```python
decision = AGENT_DECISION_ADAPTER.validate_json(raw_json)
```

返回真正选择了某个分支的实例：

```python
VectorSearchAction(...)
```

而不是一个普通字典。

常用方法：

```python
AGENT_DECISION_ADAPTER.validate_python(data)
AGENT_DECISION_ADAPTER.validate_json(json_text)
AGENT_DECISION_ADAPTER.dump_python(decision)
AGENT_DECISION_ADAPTER.dump_json(decision)
AGENT_DECISION_ADAPTER.json_schema()
```

它也可以处理不是 `BaseModel` 的类型：

```python
users_adapter = TypeAdapter(list[User])
users = users_adapter.validate_python(payload)
```

**8. `TypeAdapter` 为什么应该创建在模块级**

当前代码：

```python
AGENT_DECISION_ADAPTER: TypeAdapter[AgentStepDecision] = TypeAdapter(
    AgentStepDecision
)
```

每次创建 `TypeAdapter` 都可能触发结构分析和验证器编译。如果放在请求函数内部：

```python
async def endpoint(...):
    adapter = TypeAdapter(AgentStepDecision)  # 每个请求都创建
```

会增加不必要的重复工作。

推荐：

```text
模块加载时创建一次
请求中重复使用
```

**9. `dump_python` 与 `dump_json`**

验证后的对象：

```python
decision = AGENT_DECISION_ADAPTER.validate_json(raw_search)
```

导出为 Python 对象：

```python
AGENT_DECISION_ADAPTER.dump_python(decision)
```

可能得到：

```python
{
    "action_type": "vector_search",
    "query": "伊夫堡监狱",
    "top_k": 3,
    "filters": {},
}
```

导出为 JSON：

```python
AGENT_DECISION_ADAPTER.dump_json(decision)
```

得到 JSON 字节串，适合 HTTP 或消息队列发送。

**10. FastAPI 的 `response_model`**

普通接口应该声明输出契约：

```python
@app.post("/extract", response_model=ChapterExtractionResult)
async def extract(...):
    return result
```

`response_model` 会参与：

- OpenAPI 文档生成。
- 响应数据校验。
- 响应字段过滤。
- 序列化转换。

例如内部模型有敏感字段：

```python
class InternalUser(BaseModel):
    id: int
    password_hash: str
```

即使路由内部返回：

```python
{"id": 1, "password_hash": "secret"}
```

如果 `response_model` 中没有 `password_hash`，FastAPI 默认不会把它输出给客户端。

参数：

```python
response_model_exclude_none=True
```

可以排除值为 `None` 的字段。

```python
response_model_exclude_unset=True
```

可以排除调用方未显式设置的字段。

但要区分：

```python
model_dump()
```

是手动序列化。

```python
response_model=...
```

是 FastAPI 根据模型定义自动处理响应。

当前 SSE 接口返回的是：

```python
EventSourceResponse
```

它属于流式响应对象，通常不经过 `response_model` 的普通 JSON 序列化流程。因此帧数据需要像项目现在这样手动构造 JSON：

```python
"data": json.dumps({"content": token}, ensure_ascii=False)
```

**11. 常见序列化误区**

错误写法：

```python
model.dict()
model.json()
```

这是 Pydantic v1 常见写法，v2 应使用：

```python
model.model_dump()
model.model_dump_json()
```

另一个错误：

```python
json.dumps(result.model_dump())
```

如果模型含有 `datetime`、`UUID` 等 Python 对象，可能失败。更安全的是：

```python
result.model_dump(mode="json")
```

或：

```python
result.model_dump_json()
```

`by_alias=True` 也需要按需显式开启。模型中定义别名，不代表默认导出一定使用别名。

**12. 当前模型的一个注意点**

`BaseAgentAction` 配置了：

```python
frozen=True
```

它保证不能执行：

```python
action.top_k = 99
```

但 `VectorSearchAction` 中仍有：

```python
filters: dict[str, str | int]
```

`frozen=True` 不能阻止：

```python
action.filters["key"] = "value"
```

因为这里修改的是字典内部，不是替换字段绑定。同样，`FinalReplyAction.citations` 是列表，也可能被原地修改。

所以 `frozen=True` 是浅层不可变，不是深度不可变。

**本段掌握标准**

你应该能回答：

1. `model_dump()`、`model_dump(mode="json")` 和 `model_dump_json()` 有什么区别？
2. 为什么输入使用别名，不代表输出默认也使用别名？
3. `$defs` 和 `$ref` 在 JSON Schema 中是什么关系？
4. 为什么判别联合类型比普通联合类型更快、错误更清晰？
5. 为什么 `TypeAdapter` 要创建在模块级？
6. 直接构造 `VectorSearchAction` 和用联合类型解析它，在 discriminator 上有什么区别？
7. 普通接口为什么应该声明 `response_model`？
8. 为什么 SSE 接口不能直接依赖普通 `response_model` 完成流式输出？

## 用户（原始消息 1352）

1. model_dump 返回的是 python 字典，会包含 python 对象，加了 mode="json"  导出的就是 json 字符串了，pypthon 对象会进行序列化 例如  datetime 会序列化为 时间字符串  2. 因为输入输出是可以单独配置的 3. $ref 表示所用到的类型， $defs 表示字段，可能 会使用到 $refs 中的值  4.  因为pydantic 不用规格一个去尝试，可以一 o1 复杂度直接匹配到。5. 因为每次创建都需要消耗性能，并且可以复用，故而适合放在模块机。6. 不清楚 7. 这样 fastapi 可以方便的实现隐藏密码，使用别名等功能呢 8. 因为 sse 是流式输出，需要手动构造每一帧的数据

## 助手（原始消息 1366）

**批改**

1. 前半正确，后半需要纠正：

   ```python
   result.model_dump(mode="json")
   ```

   返回的仍然是 `dict`，不是 JSON 字符串。区别只是其中的 Python 对象已经转换为 JSON 兼容值：

   ```python
   {
       "created_at": "2026-10-30T10:00:00"
   }
   ```

   真正的 JSON 字符串来自：

   ```python
   result.model_dump_json()
   ```

   三者应区分为：

   ```text
   model_dump()             -> Python dict，可能包含 datetime 等对象
   model_dump(mode="json")  -> JSON 兼容 dict
   model_dump_json()        -> JSON 字符串
   ```

2. 基本正确。具体是通过：

   ```python
   validation_alias
   serialization_alias
   ```

   分别控制输入名称和输出名称。只有一个 `alias` 时，输入和输出默认使用同一个名称。

3. 理解反了。正确关系是：

   ```python
   "$defs": {
       "CharacterRelation": {
           "type": "object",
           "properties": {...}
       }
   }
   ```

   `$defs` 是“类型定义仓库”；`$ref` 是“指向某个定义的引用”：

   ```json
   {
       "relations": {
           "type": "array",
           "items": {
               "$ref": "#/$defs/CharacterRelation"
           }
       }
   }
   ```

   可以理解为：

   ```text
   $defs = 定义放在哪里
   $ref  = 这里引用了哪个定义
   ```

4. 基本正确，但要避免把整体复杂度都称为 O(1)。准确说法是：

   > 判别联合通过 `action_type` 直接查找对应模型分支，不需要逐个成员尝试解析。

   选中分支后，该模型字段的校验仍然正常执行。

5. 正确。`TypeAdapter` 会建立并缓存验证与序列化逻辑，应该在模块级复用。

6. 这一点需要重点补充：

   直接构造：

   ```python
   action = VectorSearchAction(query="伊夫堡监狱")
   ```

   这里已经明确知道要创建 `VectorSearchAction`，因此类字段默认值会生效：

   ```python
   action.action_type == "vector_search"
   ```

   通过联合类型解析：

   ```python
   AGENT_DECISION_ADAPTER.validate_json(
       '{"query":"伊夫堡监狱"}'
   )
   ```

   Pydantic 还不知道应该选择哪个模型，必须先读取：

   ```python
   action_type
   ```

   但输入中没有这个字段，因此实测报错：

   ```text
   type: union_tag_not_found
   loc: ()
   ```

   如果值无法匹配：

   ```json
   {"action_type": "unknown", "query": "伊夫堡监狱"}
   ```

   则报：

   ```text
   type: union_tag_invalid
   loc: ()
   ```

   原因是执行顺序不同：

   ```text
   直接构造：先确定类 -> 再应用字段默认值
   联合解析：先读取 discriminator -> 才能确定类
   ```

   所以即使类中定义了：

   ```python
   action_type: Literal["vector_search"] = "vector_search"
   ```

   LLM 返回 JSON 时仍然应该明确携带 `action_type`。

7. 方向正确，但不完整。`response_model` 的作用包括：

   ```text
   校验响应数据结构
   过滤模型之外的字段
   按输出模型序列化
   生成 OpenAPI 文档
   应用输出别名
   ```

   隐藏密码的正确方式是专门定义公开响应模型：

   ```python
   class UserResponse(BaseModel):
       id: int
       name: str
   ```

   即使内部返回对象包含：

   ```python
   password_hash
   ```

   只要它不在 `UserResponse` 中，就不会被输出。

   不能把包含敏感字段的模型直接作为 `response_model`，否则 `response_model` 不会自动判断哪个字段敏感。

8. 正确。SSE 是持续输出的原始流式响应，每一帧由代码自行编码，不能依赖普通 `response_model` 对整个响应做一次性 JSON 序列化。

