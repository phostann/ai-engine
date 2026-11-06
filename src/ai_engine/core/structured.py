"""Structured outputs engine with validation self-healing loop."""

import json
import logging

from typing import Any, Protocol
from pydantic import BaseModel, ValidationError

from ai_engine.core.exceptions import (
    ModelRefusalError,
    SelfHealingExhaustedError,
    TokenTruncationError,
)

from ai_engine.core.schema_compiler import StrictSchemaCompiler

logger = logging.getLogger(__name__)


class LLMClientProtocol(Protocol):
    """Protocol for LLM client interaction."""

    async def create_chat_completion(
        self,
        messages: list[dict[str, Any]],
        response_format: dict[str, Any] | None = None,
        temperature: float = 0.0,
    ) -> dict[str, Any]: ...


class StructuredOutputEngine:
    """Orchestrates structured output extraction and error correction."""

    def __init__(self, client: LLMClientProtocol, max_heal_attempts: int = 2):
        self.client = client
        self.max_heal_attempts = max_heal_attempts

    async def extract[T: BaseModel](
        self, schema_cls: type[T], system_prompt: str, user_prompt: str, temperature: float = 0.0
    ) -> T:
        """Extract structured data matching schema_cls with self-healing guarantees"""
        strict_format = StrictSchemaCompiler.compile(schema_cls)

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        attempts = 0
        last_errors: list[dict[str, Any]] = []

        while attempts <= self.max_heal_attempts:
            logger.info("Executing generation attempt %d/%d", attempts, self.max_heal_attempts)

            # 1. 提交推理请求
            raw_response = await self.client.create_chat_completion(
                messages=messages, response_format=strict_format, temperature=temperature
            )

            # 2. 检查协议层拒答与截断
            choice = raw_response.get("choices", [{}])[0]
            message_obj = choice.get("message", {})
            finish_reason = choice.get("finish_reason")

            # -------------------------------------------------------------
            # TODO (学员实战 2): 完成状态检查与自愈循环核心判定
            # 1. 检查 message_obj 中是否存在非空的 "refusal" 属性:
            #    若存在，抛出 ModelRefusalError(refusal_msg)
            # 2. 检查 finish_reason:
            #    若为 "length"，抛出 TokenTruncationError(message_obj.get("content", ""))
            # 3. 使用 schema_cls.model_validate_json(...) 驱动 Rust 解析:
            #    - 成功: 直接 return 解析后的实例对象
            #    - 捕获 ValidationError as err:
            #      a. 提取结构化差量错误 (使用 err.errors())
            #      b. 将上一步模型的错误输出 append 到 messages:
            #         {"role": "assistant", "content": message_obj.get("content", "")}
            #      c. 构建差量自愈修正 prompt 并 append 到 messages:
            #         {"role": "user", "content": cls._format_repair_prompt(err.errors())}
            #      d. 更新 last_errors，进入下一轮 attempts 循环
            # -------------------------------------------------------------

            # 1. 拒答判定
            if message_obj.get("refusal"):
                raise ModelRefusalError(message_obj["refusal"])

            raw_content = message_obj.get("content", "")

            # 2.截断判定
            if finish_reason == "length":
                raise TokenTruncationError(raw_content)

            # 3. Rust 内核直接校验与错误捕获
            try:
                # 直接通过 pydantic_core 执行底层二进制/SIMD反序列化
                validated_model = schema_cls.model_validate_json(raw_content)
                return validated_model
            except ValidationError as exc:
                attempts += 1
                clean_errors = self._extract_clean_errors(exc)
                last_errors = clean_errors
                logger.warning(
                    "Pydantic validation failed: %s. Initiating self-healing...", clean_errors
                )

                if attempts > self.max_heal_attempts:
                    break

                # 记录 Assistant 的原始错误输出
                messages.append({"role": "assistant", "content": raw_content})
                # 注入结构化差量修复指示（拒绝冗余 Traceback，精准投递错误字段定位）
                repair_prompt = self._format_repair_prompt(clean_errors)
                messages.append({"role": "user", "content": repair_prompt})

        # 超过最大尝试次数，熔断抛出
        raise SelfHealingExhaustedError(attempts=attempts, last_errors=last_errors)

    @staticmethod
    def _extract_clean_errors(err: ValidationError) -> list[dict[str, Any]]:
        """Extract clean, context-focused errors without full python tracebacks."""
        clean = []
        for e in err.errors():
            clean.append(
                {
                    "loc": " -> ".join(str(p) for p in e.get("loc", ())),
                    "message": e.get("msg"),
                    "type": e.get("type"),
                    "invalid_input": e.get("input"),
                }
            )
        return clean

    @staticmethod
    def _format_repair_prompt(errors: list[dict[str, Any]]) -> str:
        """Construct a minimal token-cost repair prompt."""
        formatted_issues = json.dumps(
            errors,
            indent=2,
            ensure_ascii=False,
        )

        return (
            "CRITICAL: The previous JSON output failed validation against the required schema/business rules.\n"
            "Issues detected:\n"
            f"{formatted_issues}\n"
            "Please fix the errors above and return the corrected, complete JSON object."
            "Do not output markdown code blocks or explanations, adhere strictly to the schema."
        )



