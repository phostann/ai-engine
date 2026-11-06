"""Tests for structured outputs and self-healing loop"""

import pytest
from typing import Optional
from pydantic import BaseModel, Field, field_validator

from ai_engine.core.exceptions import (
    ModelRefusalError,
    SelfHealingExhaustedError,
    TokenTruncationError,
)

from ai_engine.core.schema_compiler import StrictSchemaCompiler
from ai_engine.core.structured import StructuredOutputEngine


# -------------------------------------------------------------
# 业务数据模型定义
# -------------------------------------------------------------
class UserAddress(BaseModel):
    street: str
    postal_code: str


class UserProfile(BaseModel):
    name: str = Field(description="Full name")
    age: int = Field(ge=0, le=150)
    email: str
    address: Optional[UserAddress] = None
    tags: list[str] = Field(default_factory=list)

    @field_validator("email")
    @classmethod
    def validate_corporate_email(cls, v: str) -> str:
        """业务规则：强烈要求企业邮箱后缀。"""
        if not v.endswith("@company.com"):
            raise ValueError("Email must belong to domain @company.com")
        return v


# -------------------------------------------------------------
# 模拟 LLM 客户端
# -------------------------------------------------------------
class MockLLMClient:
    """Mock client capable of simulating truncation, refusal, and repair sequences."""

    def __init__(self, scripted_responses: list[dict]):
        self.responses = scripted_responses
        self.call_count = 0
        self.history: list[list[dict]] = []

    async def create_chat_completion(
        self, messages: list[dict], response_format: dict | None = None, temperature: float = 0.0
    ) -> dict:
        self.history.append(messages)
        if self.call_count >= len(self.responses):
            raise RuntimeError("MockLLMClient called beyond scripted responses.")
        resp = self.responses[self.call_count]
        self.call_count += 1
        return resp


# -------------------------------------------------------------
# 自动化测试套件
# -------------------------------------------------------------
def test_strict_schema_compiler():
    """验证 Pydantic Schema 转换为 OpenAI Strict Schema 的合规性。"""
    result = StrictSchemaCompiler.compile(UserProfile)

    assert result["type"] == "json_schema"
    assert result["json_schema"]["strict"] is True

    schema = result["json_schema"]["schema"]
    # 验证根对象 additionalProperties 为 False
    assert schema["additionalProperties"] is False
    # 验证 required 覆盖所有属性
    assert set(schema["required"]) == {"name", "age", "email", "address", "tags"}
    # 验证嵌套对象是否也被递归修改
    defs = schema.get("$defs", {})
    if "UserAddress" in defs:
        assert defs["UserAddress"]["additionalProperties"] is False
        assert set(defs["UserAddress"]["required"]) == {"street", "postal_code"}


@pytest.mark.asyncio
async def test_successful_extraction_on_first_attempt():
    """测试第一轮直接成功解析的标准场景"""
    valid_json = (
        '{"name": "Alice", "age": 30, "email": "alice@company.com", '
        '"address": {"street": "Main St", "postal_code": "10001"}, "tags": ["admin"]}'
    )
    client = MockLLMClient(
        [{"choices": [{"message": {"content": valid_json, "finish_reason": "stop"}}]}]
    )

    engine = StructuredOutputEngine(client=client, max_heal_attempts=2)

    profile = await engine.extract(
        schema_cls=UserProfile,
        system_prompt="Extract user.",
        user_prompt="Alice, 30yo, alice@company.com, Main St, 10001",
    )

    assert profile.name == "Alice"
    assert profile.age == 30
    assert profile.email == "alice@company.com"
    assert profile.address is not None and profile.address.postal_code == "10001"
    assert client.call_count == 1


@pytest.mark.asyncio
async def test_self_healing_on_semantic_validation_failure():
    """破坏性实验 1：第 1 次邮箱格式不合规（触发 field_validator），第 2 次自愈修正成功。"""
    invalid_json = (
        '{"name": "Bob", "age": 25, "email": "bob@gmail.com", "address": null, "tags": []}'
    )
    corrected_json = (
        '{"name": "Bob", "age": 25, "email": "bob@company.com", "address": null, "tags": []}'
    )

    client = MockLLMClient(
        [
            # 第一次返回违规邮箱
            {"choices": [{"message": {"content": invalid_json}, "finish_reason": "stop"}]},
            # 第二次自愈返回合规企业邮箱
            {"choices": [{"message": {"content": corrected_json}, "finish_reason": "stop"}]},
        ]
    )

    engine = StructuredOutputEngine(client=client, max_heal_attempts=2)
    profile = await engine.extract(
        schema_cls=UserProfile,
        system_prompt="Extract user.",
        user_prompt="Bob, 25, bob@company.com",
    )

    assert profile.email == "bob@company.com"
    assert client.call_count == 2
    # 验证修复请求是否包含了上一次失败的上下文信息
    last_prompt = client.history[-1][-1]["content"]
    assert "CRITICAL: The previous JSON output failed validation" in last_prompt
    assert "bob@gmail.com" in last_prompt


@pytest.mark.asyncio
async def test_truncation_detection_and_fast_fail():
    """破坏性实验 2：检测物理截断（finish_reason='length'），应立即熔断抛出 TokenTruncationError。"""
    truncated_json = '{"name": "Charlie", "age": 40, "email": "charlie@com'
    client = MockLLMClient(
        [{"choices": [{"message": {"content": truncated_json}, "finish_reason": "length"}]}]
    )

    engine = StructuredOutputEngine(client=client, max_heal_attempts=2)

    with pytest.raises(TokenTruncationError):
        await engine.extract(
            schema_cls=UserProfile,
            system_prompt="Extract user.",
            user_prompt="Charlie, 40, charlie@company",
        )


@pytest.mark.asyncio
async def test_model_refusal_fast_fail():
    """破坏性实验 3：安全拦截抛出 ModelRefusalError。"""
    client = MockLLMClient(
        [
            {
                "choices": [
                    {
                        "message": {"content": "", "refusal": "Cannot process copyrighted data."},
                        "finish_reason": "stop",
                    }
                ]
            }
        ]
    )

    engine = StructuredOutputEngine(client=client, max_heal_attempts=2)
    with pytest.raises(ModelRefusalError) as exc_info:
        await engine.extract(
            schema_cls=UserProfile,
            system_prompt="Extract user.",
            user_prompt="Dave, 50, dave@company.com",
        )

    assert "Cannot process copyrighted data." in str(exc_info.value)