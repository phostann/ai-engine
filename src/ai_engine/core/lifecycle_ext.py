import asyncio
import logging
import uuid
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass

# ==================== 1. ContextVar 全链路异步日志染色 ====================
_trace_id_var: ContextVar[str] = ContextVar("trace_id", default="system")


class TraceIdLogFilter(logging.Filter):
    """日志过滤器：自动从当前协程的 ContextVar 提取 trace_id 注入每条日志记录（对标 Spring MDC）"""

    def filter(self, record: logging.LogRecord) -> bool:
        record.trace_id = _trace_id_var.get()
        return True


def setup_traced_logger(name: str = "ai_engine") -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            "%(asctime)s | %(levelname)-5s | [trace:%(trace_id)s] %(message)s",
            datefmt="%H:%M:%S",
        )
        handler.setFormatter(formatter)
        handler.addFilter(TraceIdLogFilter())
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger


logger = setup_traced_logger()


@asynccontextmanager
async def request_trace_scope(trace_id: str | None = None) -> AsyncIterator[str]:
    """在请求入口处开启 trace_id 作用域，所有内部子协程自动继承且互不串号"""
    tid = trace_id or f"req-{uuid.uuid4().hex[:6]}"
    token = _trace_id_var.set(tid)
    try:
        yield tid
    finally:
        _trace_id_var.reset(token)


# ==================== 2. AsyncExitStack 动态多资源池托管 ====================
@dataclass
class MockMCPServerConnection:
    server_name: str
    is_open: bool = False


@asynccontextmanager
async def connect_single_mcp(
    server_name: str, fail_on_init: bool = False
) -> AsyncIterator[MockMCPServerConnection]:
    """模拟单个 MCP 工具服务的异步连接生命周期"""
    logger.info(f"正在建立 MCP 连接 -> [{server_name}]")
    await asyncio.sleep(0.02)
    if fail_on_init:
        raise ConnectionError(f"MCP 服务 [{server_name}] 握手失败！")
    conn = MockMCPServerConnection(server_name=server_name, is_open=True)
    try:
        yield conn
    finally:
        conn.is_open = False
        logger.info(f"已安全释放 MCP 连接 <- [{server_name}]")


class DynamicMCPClusterManager:
    """
    利用 AsyncExitStack 动态管理任意数量(运行时决定)的异步上下文资源
    哪怕第 N 个服务连接失败，前 N-1 个已打开的连接也会严格按 LIFO 逆序安全释放
    """

    def __init__(self, server_names: list[str], fail_server: str | None = None) -> None:
        self.server_names = server_names
        self.fail_server = fail_server
        self._stack: AsyncExitStack | None = None
        self.active_connections: dict[str, MockMCPServerConnection] = {}

    async def __aenter__(self) -> dict[str, MockMCPServerConnection]:
        self._stack = AsyncExitStack()
        await self._stack.__aenter__()
        try:
            for name in self.server_names:
                should_fail = name == self.fail_server
                # 动态压入上下文栈！等同于动态写了 N 层嵌套的 async with
                conn = await self._stack.enter_async_context(
                    connect_single_mcp(name, fail_on_init=should_fail)
                )
                self.active_connections[name] = conn
            return self.active_connections
        except Exception:
            # 如果中途某个连接初始化失败，立即触发栈回滚，关闭前面已打开的所有连接
            await self._stack.__aexit__(*(None, None, None))
            raise

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._stack is not None:
            await self._stack.__aexit__(exc_type, exc_val, exc_tb)


# ==================== 3. asyncio.shield 保护流式生成器的异步计费落库 ====================
async def save_token_billing_to_db(tokens_used: int, billing_ledger: list[int]) -> None:
    """模拟需要将已消耗 Token 异步写入数据库的计费操作"""
    await asyncio.sleep(0.05)  # 模拟异步数据库 I/O 耗时
    billing_ledger.append(tokens_used)
    logger.info(f"💰 数据库计费落库成功：扣减 {tokens_used} Tokens")


async def shielded_token_stream(
    chunks: list[str],
    billing_ledger: list[int],
) -> AsyncGenerator[str, None]:
    """即使外部任务被强制 Cancel，也能通过 asyncio.shield 保证异步计费落库不丢失"""
    consumed = 0
    try:
        for chunk in chunks:
            await asyncio.sleep(0.02)
            consumed += 1
            yield chunk
    finally:
        if consumed > 0:
            # 关键：在 finally 中执行异步 I/O 时，必须用 asyncio.shield 包裹并捕获外层取消异常
            # 否则外部 Task.cancel() 会直接打断 save_token_billing_to_db 内部的 await！
            billing_task = asyncio.create_task(save_token_billing_to_db(consumed, billing_ledger))
            try:
                await asyncio.shield(billing_task)
            except asyncio.CancelledError:
                # 即使当前协程正处于被取消状态，也等待受保护的计费任务彻底写完数据库再重新抛出
                await billing_task
                raise
