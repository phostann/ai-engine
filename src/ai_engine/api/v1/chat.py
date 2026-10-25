import asyncio
import json
from collections.abc import AsyncGenerator

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from ai_engine.api.deps import HttpClientDep, TraceIdDep

router = APIRouter(prefix="/api/v1/chat", tags=["Chat"])


class ChatRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=2000, description="用户输入")
    model: str = Field(default="gpt-4o-mini", description="模型名称")


async def generate_mock_chat_stream(
    prompt: str,
    trace_id: str,
    request: Request,
) -> AsyncGenerator[dict[str, str], None]:
    """
    核心 SSE 数据帧生成器：
    必须能及时感知客户端断开（如前端用户点击停止或关闭网页）
    """
    mock_tokens = [
        f"[trace:{trace_id}] ",
        "你好！",
        "我是",
        "通过 FastAPI 与 SSE ",
        "提供实时流式打字机服务的后端引擎。",
        "收到 Prompt: ",
        f"“{prompt}”。",
        "推理完毕！",
    ]

    try:
        for idx, token in enumerate(mock_tokens):
            # TODO 3: 检查客户端是否已经断开连接（await request.is_disconnected()）
            # 如果断开，立即打印日志并 break 提前退出
            if await request.is_disconnected():
                print("🛑 [SSE] 客户端提前断开连接，已停止推流: {trace_id}")
                break

            await asyncio.sleep(0.06)

            # 发送符合 SSE 规范的字典数据
            yield {
                "event": "message",
                "id": str(idx),
                "data": json.dumps({"content": token}, ensure_ascii=False),
            }

        # 结束哨兵包
        yield {"event": "done", "data": "[DONE]"}

    except asyncio.CancelledError:
        print(f"⚠️ [SSE] 捕获协程取消信号: {trace_id}")
        raise


@router.post("/completions/stream")
async def stream_chat_completions(
    body: ChatRequest,
    request: Request,
    trace_id: TraceIdDep,
    _http_client: HttpClientDep,
) -> EventSourceResponse:
    """生产级别 SSE 流式接口"""
    # TODO 4: 返回 EventSourceResponse，传入刚才实现的生成器函数
    # 设置 ping 间隔为 15 秒（维持长链接，防止经过反向代理时被超时掐断）
    stream_generator = generate_mock_chat_stream(body.prompt, trace_id, request)
    return EventSourceResponse(stream_generator)
