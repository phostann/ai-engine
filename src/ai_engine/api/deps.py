import uuid
from collections.abc import AsyncIterable
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status

from ai_engine.core.context import _trace_id_var
from ai_engine.core.http_client import ProductionHttpClient


async def get_http_client(request: Request) -> ProductionHttpClient:
    """从 app.state 提取已经初始化的全局连接池单例"""
    client: ProductionHttpClient | None = getattr(request.app.state, "http_client", None)
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="全局 HTTP 客户端连接池未初始化",
        )
    return client


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


# 组合类型别名（现代 Python 声明风格）
HttpClientDep = Annotated[ProductionHttpClient, Depends(get_http_client, use_cache=True)]
TraceIdDep = Annotated[str, Depends(get_request_trace_id, use_cache=True)]
