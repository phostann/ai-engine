import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass

# 全链路协程安全的 trace_id 变量（对标 Spring MDC / ThreadLocal，但单线程协程安全）
_trace_id_var: ContextVar[str] = ContextVar("trace_id", default="system")


@dataclass
class MockLLMClient:
    """模拟一个持有底层网络连接池的大模型客户端"""

    model_name: str
    is_connected: bool = False


@asynccontextmanager
async def llm_session_scope(model_name: str) -> AsyncIterator[MockLLMClient]:
    """异步上下文管理器：确保大模型连接池与计费会话在退出时 100% 释放"""
    print(f"🔌 [Context] 正在初始化 {model_name} 异步连接池...")
    await asyncio.sleep(0.1)  # 模拟建立连接握手
    client = MockLLMClient(model_name=model_name, is_connected=True)

    try:
        # 将创建好的资源交给外部 async with 块使用，函数在此处暂停挂起
        yield client
    except Exception as exc:
        # 如果外部代码块发生未捕获异常，可以在此统一记录错误日志或回滚事务
        print(f"🚨 [Context] 会话执行期间捕获到异常: {exc}")
        raise
    finally:
        # 无论外部正常结束、return、或者抛出异常，都会回到这里执行清理
        client.is_connected = False
        await asyncio.sleep(0.05)
        print(f"🔒 [Context] {model_name} 连接池已安全关闭释放")
