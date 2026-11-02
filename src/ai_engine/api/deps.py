import uuid
from collections.abc import AsyncIterable
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status

from ai_engine.core.context import _trace_id_var
from ai_engine.services.llm_client import NativeLLMClient


async def get_request_trace_id(
    x_trace_id: Annotated[str | None, Header(alias="X-Trace-ID")] = None,
) -> AsyncIterable[str]:
    """
    利用 yield 依赖，为每个请求注入独立 trace_id 并设置 ContextVar，
    请求结束后自动清理，杜绝协程串号
    """

    # TODO 2: 将 trace_id 绑定到 ContextVar (_trace_id_var) 中
    # 使用 yield 将 trace_id 抛出给路由函数
    # 在 finally 中使用 _trace_id_var.reset(token) 安全重置
    trace_id = x_trace_id or f"req-{uuid.uuid4().hex[:8]}"
    token = _trace_id_var.set(trace_id)
    try:
        yield trace_id
    finally:
        _trace_id_var.reset(token)


async def get_llm_client(request: Request) -> NativeLLMClient:
    """从 app.state 获取已经装配好的 NativeLLMClient 单例"""
    client: NativeLLMClient | None = getattr(request.app.state, "llm_client", None)
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="NativeLLMClient 尚未在 lifespan 中初始化",
        )
    return client


# 组合类型别名（现代 Python 声明风格）
TraceIdDep = Annotated[str, Depends(get_request_trace_id, use_cache=True)]
LLMClientDep = Annotated[NativeLLMClient, Depends(get_llm_client, use_cache=True)]
