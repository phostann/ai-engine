import json
from collections.abc import AsyncGenerator
from typing import Any

from ai_engine.core.config import Settings
from ai_engine.core.http_client import ProductionHttpClient
from ai_engine.core.tokenizer import TokenBudgetGuard


class NativeLLMClient:
    """
    异步原生大模型客户端:
    1. 内部集成 TokenBudgetGuard 进行请求前预算拦截
    2. 复用底层长链接池与 Full-Jitter 重试
    3. 支持流式 SSE 逐字解包与非流式调用
    """

    def __init__(
        self,
        settings: Settings,
        http_client: ProductionHttpClient,
        token_guard: TokenBudgetGuard | None = None,
    ) -> None:
        self.settings = settings
        self.http_client = http_client
        self.token_guard = token_guard

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> AsyncGenerator[str, None]:
        """流式输出: 自动进行 Token 预算检验，按 SSE 协议逐字下发 Token"""
        target_model = model or self.settings.llm_model

        # 1. 本地前置校验拦截
        if self.token_guard:
            self.token_guard.validate_budget_or_raise(messages, max_completion_tokens=max_tokens)

        headers = {
            "Authorization": f"Bearer {self.settings.llm_api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": target_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }

        # TODO 5: 使用 self.http_client.client.stream 发送 POST 请求到 "/chat/completions"
        # 逐行读取 response.aiter_lines()
        # 过滤以 "data: " 开头的行，并处理 "[DONE]" 终止符
        # 使用 json.loads 解析每行数据，提取 delta["content"] 并 yield 抛出

        async with self.http_client.client.stream(
            "POST",
            "/chat/completions",
            json=payload,
            headers=headers,
        ) as response:
            response.raise_for_status()
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
