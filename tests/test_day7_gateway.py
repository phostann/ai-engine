import json

import httpx
import pytest
from httpx import ASGITransport

from ai_engine.main import app


@pytest.mark.asyncio
async def test_gateway_streaming_success() -> None:
    """测试场景 1：端到端流式推流成功消费"""
    mock_chunks = [
        {"choices": [{"delta": {"content": "全栈 "}}]},
        {"choices": [{"delta": {"content": "架构师 "}}]},
        {"choices": [{"delta": {"content": "网关"}}]},
    ]

    def mock_sse(req: httpx.Request) -> httpx.Response:
        sse_lines = [f"data: {json.dumps(c)}\n\n" for c in mock_chunks]
        sse_lines.append("data: [DONE]\n\n")
        return httpx.Response(200, content="".join(sse_lines).encode("utf-8"))
        # raise httpx.ReadTimeout("连接超时")

    async with app.router.lifespan_context(app):
        # 挂载 MockTransport 拦截底层的真实 HTTP 请求
        app.state.llm_client.http_client.client._transport = httpx.MockTransport(mock_sse)

        async with httpx.AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/v1/chat/completions/stream",
                json={"prompt": "如何设计高并发系统？"},
                headers={"X-Trace-Id": "trace-day7-001"},
            )

            assert resp.status_code == 200
            assert "text/event-stream" in resp.headers["Content-Type"]

            lines = [line for line in resp.text.split("\r\n") if line.startswith("data: ")]

            assert len(lines) >= 4  # 3 个数据包 + 1 个 [DONE]
            assert any("[DONE]" in line for line in lines)
