import asyncio

import httpx
import pytest

from ai_engine.core.concurrency import run_bounded_task_group
from ai_engine.core.http_client import ProductionHttpClient


@pytest.mark.asyncio
async def test_task_group_concurrency_and_order() -> None:
    """验证 Semaphore 限制并发为 2， 且结果保序"""
    current_active = 0
    max_active = 0

    async def mock_worker(item_id: int) -> str:
        nonlocal current_active, max_active
        current_active += 1
        max_active = max(max_active, current_active)

        # 让前面任务多睡一会儿，检验输出是否仍然保序
        await asyncio.sleep(0.03 if item_id == 1 else 0.01)
        current_active -= 1
        return f"res-{item_id}"

    results = await run_bounded_task_group(
        items=[1, 2, 3, 4],
        worker_fn=mock_worker,
        max_concurrency=2,
    )

    assert max_active == 2
    assert results == ["res-1", "res-2", "res-3", "res-4"]


@pytest.mark.asyncio
async def test_task_group_cancels_siblings_on_error() -> None:
    """验证组内一个任务的崩溃耗时，TaskGroup 会取消正在运行的兄弟任务"""

    sibling_was_cancelled = False

    async def worker(item_id: int) -> int:
        nonlocal sibling_was_cancelled
        if item_id == 1:
            await asyncio.sleep(0.01)
            raise ValueError("任务 1 发生异常！")
        try:
            await asyncio.sleep(1.0)
            return item_id
        except asyncio.CancelledError:
            sibling_was_cancelled = True
            raise

    with pytest.raises(ExceptionGroup):
        await run_bounded_task_group([1, 2], worker, max_concurrency=2)

    assert sibling_was_cancelled is True


@pytest.mark.asyncio
async def test_http_client_jitter_retry_with_mock_transport() -> None:
    """使用 MockTransport 验证客户端在前两次遇到 429 时自动重试，第三次成功"""
    attempt_count = 0

    def mock_handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempt_count
        attempt_count += 1
        if attempt_count <= 2:
            return httpx.Response(429, json={"error": "Rate limit"})
        return httpx.Response(200, json={"data": "success"})

    async with ProductionHttpClient(base_url="https://mock.ai") as client:
        # 挂载内存级 MockTransport 避免发出真实网络请求
        client.client._transport = httpx.MockTransport(mock_handler)
        resp = await client.request_with_jitter_retry(
            "POST", "/v1/chat", max_retries=3, base_delay=0.02
        )
        assert resp.status_code == 200
        assert resp.json()["data"] == "success"
        assert attempt_count == 3
