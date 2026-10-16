import asyncio

from ai_engine.core.config import get_settings
from ai_engine.core.context import llm_session_scope
from ai_engine.services.stream_service import check_model_health, stream_llm_tokens


async def async_main() -> None:
    # settings = get_settings()
    # print(f"🚀 [{settings.app_env.upper()}] {settings.app_name} 启动成功！")
    # print(f"🤖 当前模型: {settings.llm_model} | 接口地址: {settings.llm_base_url}")
    # print(f"🔑 密钥状态: {settings.masked_api_key}")
    settings = get_settings()
    print(f"🚀 [{settings.app_env.upper()}] {settings.app_name} 启动")

    # 1. 使用 async with 自动管理连接池生命周期
    async with llm_session_scope(settings.llm_model) as client:
        # 2. 调用带 @async_timer 和 @async_retry 装饰器的函数
        await check_model_health(client)

        # 3. 场景 A：完整消费异步生成器流（使用 async for）
        print("\n--- 场景 A：完整流式输出 ---")
        print("🤖 AI 回复：", end="", flush=True)

        async for token in stream_llm_tokens(client, "什么是异步生成器？"):
            # end="" 和 flush=True 在终端实现打字机效果
            print(token, end="", flush=True)

        # 4. 长江 B：模拟前端用户听到第 4 个词时点击了 “停止生成” 按钮
        print("\n--- 场景 B：模拟用户中途点击【停止生成】 ---")
        print("🤖 AI 回复：", end="", flush=True)
        stream = stream_llm_tokens(client, "演示一下中途打断流式输出")
        try:
            count = 0
            async for token in stream:
                print(token, end="", flush=True)
                count += 1
                if count >= 4:
                    print(" [👆用户点击了停止按钮]", end="", flush=True)
                    break
        finally:
            # 显式关闭异步生成器，立即触发生成器内部的 finally 结算逻辑
            await stream.aclose()


def main() -> None:
    # 使用 asyncio.run 启动顶层事件循环
    asyncio.run(async_main())
