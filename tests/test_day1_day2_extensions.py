import asyncio

import pytest

from ai_engine.core.lifecycle_ext import (
    DynamicMCPClusterManager,
    _trace_id_var,
    request_trace_scope,
    shielded_token_stream,
)


@pytest.mark.asyncio
async def test_contextvar_isolation_across_concurrent_tasks() -> None:
    """验证高并发下 ContextVar 在不同协程间的 100% 隔离性（绝不发生 ThreadLocal 串号）"""
    observed_traces: dict[str, str] = {}

    async def handle_user_request(user_id: str, custom_tid: str, sleep_sec: float) -> None:
        async with request_trace_scope(custom_tid):
            await asyncio.sleep(sleep_sec)
            # 唤醒后读取当前协程上下文中的 trace_id
            observed_traces[user_id] = _trace_id_var.get()

    await asyncio.gather(
        handle_user_request("user_1", "trace-AAA", 0.03),
        handle_user_request("user_2", "trace-BBB", 0.01),
        handle_user_request("user_3", "trace-CCC", 0.02),
    )

    assert observed_traces["user_1"] == "trace-AAA"
    assert observed_traces["user_2"] == "trace-BBB"
    assert observed_traces["user_3"] == "trace-CCC"
    # 退出作用域后恢复默认值
    assert _trace_id_var.get() == "system"


@pytest.mark.asyncio
async def test_async_exit_stack_rollback_on_partial_failure() -> None:
    """验证当第 3 个 MCP 服务连接失败时，前 2 个已打开的服务会被自动安全关闭"""
    manager = DynamicMCPClusterManager(
        server_names=["github-mcp", "postgres-mcp", "broken-mcp"],
        fail_server="broken-mcp",
    )

    with pytest.raises(ConnectionError, match="broken-mcp"):
        async with manager:
            pass

    # 验证前面已经建立成功的两个连接在异常回滚后均已被安全关闭 (is_open == False)
    assert manager.active_connections["github-mcp"].is_open is False
    assert manager.active_connections["postgres-mcp"].is_open is False


@pytest.mark.asyncio
async def test_shielded_billing_survives_task_cancellation() -> None:
    """验证当流式推理协程被外部强制 Cancel 时，asyncio.shield 依然能保住数据库的异步计费落库"""
    billing_ledger: list[int] = []

    async def consume_stream() -> None:
        async with request_trace_scope("cancel-test"):
            async for _ in shielded_token_stream(["A", "B", "C", "D", "E"], billing_ledger):
                pass

    task = asyncio.create_task(consume_stream())
    # 等待流吐出大约 2 个 Token 后，模拟客户端突然断开触发 Task 强行取消
    await asyncio.sleep(0.05)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    # 验证即使任务被 Cancel，已生成的 Token 依然成功完成了异步数据库落库！
    assert len(billing_ledger) == 1
    assert billing_ledger[0] >= 1
