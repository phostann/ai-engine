import httpx
import pytest
from httpx import ASGITransport

from ai_engine.main import app


@pytest.mark.asyncio
async def test_health_check_endpoint() -> None:
    """使用 ASGITransport 在内存中启动应用进行测试"""
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_sse_streaming_chat_endpoint() -> None:
    """验证 SSE 流式输出是否符合 text/event-stream 规范并成功吐出 Token"""
    # 显式执行 lifespan 确保 app.state.http_client 初始化
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            payload = {"prompt": "测试流式生成", "model": "gpt-4o-mini"}
            headers = {"X-Trace-Id": "test-trace-12345"}

            # 发送流式请求
            async with client.stream(
                "POST", "/api/v1/chat/completions/stream", json=payload, headers=headers
            ) as response:
                assert response.status_code == 200
                assert "text/event-stream" in response.headers["content-type"]

                received_events = []
                async for line in response.aiter_lines():
                    if line.startswith("data:"):
                        received_events.append(line)

                # 验证收到了多个数据块且包含结束标记
                assert len(received_events) >= 3
                assert any("[DONE]" in evt for evt in received_events)
                assert any("test-trace-12345" in evt for evt in received_events)
