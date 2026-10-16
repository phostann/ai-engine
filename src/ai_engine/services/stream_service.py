import asyncio
from collections.abc import AsyncGenerator

from ai_engine.core.context import MockLLMClient
from ai_engine.core.decorators import async_retry, async_timer


@async_timer
@async_retry(max_retries=3, base_delay=0.2)
async def check_model_health(client: MockLLMClient, simulate_fail: bool = False) -> bool:
    """模拟调用前的健康检查（演示装饰器组合使用）"""
    if not client.is_connected:
        raise RuntimeError("客户端未连接！")
    if simulate_fail:
        raise ConnectionError("模拟网络抖动超时！")
    await asyncio.sleep(0.05)
    return True


async def stream_llm_tokens(client: MockLLMClient, prompt: str) -> AsyncGenerator[str]:
    """
    核心异步生成器：模拟大模型流式逐词吐出 Token
    返回类型 AsyncGenerator[YieldType, SendType]
    """
    if not client.is_connected:
        raise RuntimeError("无法在未连接的客户端上发起流式推理")

    # 模拟大模型针对 Prompt 准备输出的 Token 序列
    mock_tokens = [
        "你好！",
        "我是",
        f"[{client.model_name}]。",
        "收到你的问题：",
        f"“{prompt}”",
        "在 AI 全栈开发中，",
        "异步生成器（AsyncGenerator）",
        "是实现 SSE 流式打自己效果的基石。",
    ]

    generated_count = 0
    try:
        for token in mock_tokens:
            # 模拟大模型生成每个 Token 的推理耗时（80ms）
            await asyncio.sleep(0.08)
            generated_count += 1
            # yield 会将当前 Token 推出去，并暂停当前函数的状态，等待外部下一次拉取
            yield token
    except asyncio.CancelledError:
        # 当客户端（如前端 AbortController）主动断开流连接时触发
        print("\n🛑 [Stream] 检测到客户端主动中断生成！")
        raise
    finally:
        # 无论流是正常吐完，还是被用户中途掐断，都在这里做 Token 结算日志
        print(f"\n📊 [Stream 结算] 本次流式会话共吐出 {generated_count} 个 Token 块")
