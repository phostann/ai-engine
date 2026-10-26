import json
from collections.abc import AsyncGenerator

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from ai_engine.api.deps import LLMClientDep, TraceIdDep
from ai_engine.core.logger import logger
from ai_engine.schemas.prompts import SystemPromptTemplate

router = APIRouter(prefix="/api/v1/chat", tags=["Chat"])

DEFAULT_SYSTEM_PROMPT = SystemPromptTemplate(
    role_identity="资深全栈架构师",
    objectives=["以严谨、高内聚低耦合的工程视角解答用户提问", "给出生产可落地的架构建议与代码"],
    constraints=["严禁给出脱离工程实际的伪代码", "禁止编造不存在的三方库 API"],
    output_format="输出技术规范严谨的 Markdown 格式",
)


class GatewayChatRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=2000, description="用户输入")
    model: str = Field(default="gpt-4o-mini", description="模型名称")
    system_override: str | None = Field(default=None, description="可选覆盖系统提示词")


async def generate_gateway_chat_stream(
    request: Request,
    body: GatewayChatRequest,
    llm_client: LLMClientDep,
    trace_id: str,
) -> AsyncGenerator[dict[str, str], None]:
    """
    工业级 SSE 数据帧分发器：
    1. 动态渲染规范 System Prompt
    2. 消费 NativeLLMClient 流式 Token
    3. 支持中途断连检测与异常错误帧降级
    """
    logger.info(f"开始处理流式会话: Prompt 长度={len(body.prompt)}")

    # 1. 组装符合 ChatML 规范的消息体
    system_content = body.system_override or DEFAULT_SYSTEM_PROMPT.render()
    messages = [
        {"role": "system", "content": system_content},
        {"role": "user", "content": body.prompt},
    ]

    emitted_tokens = 0
    try:
        # TODO 2: 调用 llm_client.chat_stream(messages, model=body.model) 异步消费数据流
        async for token in llm_client.chat_stream(messages, model=body.model):
            # TODO 3: 检测客户端是否主动中断 (await request.is_disconnected())
            if await request.is_disconnected():
                logger.warning(f"客户端主动终止连接，推流提前中止 (已吐字: {emitted_tokens})")
                break

            emitted_tokens += 1
            yield {
                "event": "message",
                "id": str(emitted_tokens),
                "data": json.dumps({"content": token}, ensure_ascii=False),
            }

        # 正常结束标记帧
        yield {"event": "done", "data": "[DONE]"}

    except ValueError as val_err:
        # 命中 Day 6 的 Token 预算超限拦截
        logger.error(f"Token 预算拦截失败: {val_err}")
        yield {
            "event": "error",
            "data": json.dumps({"code": 40001, "message": str(val_err)}, ensure_ascii=False),
        }
        yield {"event": "done", "data": "[DONE]"}

    except Exception as exc:
        # TODO 4: 捕获网络超时、429 等中途未决异常，优雅下发 error 帧而非造成 HTTP 500 崩溃
        logger.exception(f"流式推流中途发生不可逆异常: {exc}")
        yield {
            "event": "error",
            "data": json.dumps(
                {"code": 50000, "message": "网关上游推理服务发生抖动，请稍后重试"},
                ensure_ascii=False,
            ),
        }
        yield {"event": "done", "data": "[DONE]"}

    finally:
        logger.info(f"流式会话生命周期闭环: 本轮累计产出 Token 片段={emitted_tokens}")


@router.post("/completions/stream")
async def stream_chat_completions(
    request: Request,
    body: GatewayChatRequest,
    llm_client: LLMClientDep,
    trace_id: TraceIdDep,
) -> EventSourceResponse:
    """网关统一入口：流式对话接口"""
    stream_generator = generate_gateway_chat_stream(request, body, llm_client, trace_id)
    return EventSourceResponse(stream_generator, ping=15)
