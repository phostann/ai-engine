import json

import httpx
import pytest

from ai_engine.core.config import Settings
from ai_engine.core.http_client import ProductionHttpClient
from ai_engine.core.tokenizer import TokenBudgetGuard
from ai_engine.schemas.prompts import SystemPromptTemplate
from ai_engine.services.llm_client import NativeLLMClient


def test_token_counting_and_budget_guard() -> None:
    """验证纯文本与 ChatML 消息的 Token 计数及超限拦截"""
    guard = TokenBudgetGuard(encoding_name="o200k_base", max_context_limit=100)

    # 验证中英文字符能正确编码
    assert guard.count_text_tokens("Hello world") == 2
    assert guard.count_text_tokens("你好，世界") >= 2

    messages = [
        {"role": "system", "content": "你是一位资深全栈工程师。"},
        {"role": "user", "content": "请介绍 Python 异步并发机制。"},
    ]
    chat_tokens = guard.count_chat_tokens(messages)
    # 消息内容本身加上 ChatML 协议标记应大于纯文本之和
    assert chat_tokens > 15

    # 验证超出上下文上限拦截
    with pytest.raises(ValueError, match="上下文 Token 超限"):
        guard.validate_budget_or_raise(messages, max_completion_tokens=200)


def test_system_prompt_template_render() -> None:
    """验证结构化 Prompt 模板的渲染与变量安全注入"""
    template = SystemPromptTemplate(
        role_identity="图书拆解专家",
        objectives=["梳理全书主线情节", "抽取关键人物关系网"],
        constraints=["严禁编造未在原文出现的剧情", "语言保持口语化"],
        output_format="输出标准 Markdown 格式",
    )
    rendered = template.render()
    assert "# 角色定义" in rendered
    assert "图书拆解专家" in rendered
    assert "- 严禁编造未在原文出现的剧情" in rendered


@pytest.mark.asyncio
async def test_native_llm_client_streaming_with_mock() -> None:
    """使用 MockTransport 模拟 OpenAI 流式 SSE 响应，验证客户端流式解包"""
    mock_chunks = [
        {"choices": [{"delta": {"content": "Python "}}]},
        {"choices": [{"delta": {"content": "异步 "}}]},
        {"choices": [{"delta": {"content": "编程"}}]},
    ]

    def mock_sse_handler(request: httpx.Request) -> httpx.Response:
        sse_lines = []
        for c in mock_chunks:
            sse_lines.append(f"data: {json.dumps(c)}\n\n")
        sse_lines.append("data: [DONE]\n\n")
        sse_body = "".join(sse_lines).encode("utf-8")
        return httpx.Response(
            200,
            content=sse_body,
            headers={"Content-Type": "text/event-stream"},
        )

    settings = Settings(
        llm_api_key="sk-test",
        llm_base_url="https://mock.api.com/v1",
        llm_model="gpt-4o-mini",
    )

    async with ProductionHttpClient(base_url=settings.llm_base_url) as http_client:
        http_client.client._mounts.clear() # 避免走代理
        http_client.client._transport = httpx.MockTransport(mock_sse_handler)
        client = NativeLLMClient(settings=settings, http_client=http_client)

        received_tokens = []
        async for token in client.chat_stream([{"role": "user", "content": "Hi"}]):
            received_tokens.append(token)

        assert "".join(received_tokens) == "Python 异步 编程"
