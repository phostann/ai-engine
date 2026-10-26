from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ai_engine.api.v1.chat import router as chat_router
from ai_engine.core.config import get_settings
from ai_engine.core.http_client import ProductionHttpClient
from ai_engine.core.logger import logger, setup_logging
from ai_engine.core.tokenizer import TokenBudgetGuard
from ai_engine.services.llm_client import NativeLLMClient


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """
    ASGI Lifespan 协议：应用生命周期钩子
    负责全局连接池的单例初始化与停机清理
    """
    settings = get_settings()
    setup_logging(debug=settings.debug)
    logger.info(f"正在初始化网关底层设施: 环境={settings.app_env.upper()}...")

    # 初始化 Token 计算守卫与 HTTP 连接池
    token_guard = TokenBudgetGuard(max_context_limit=128000)

    # TODO 1: 实例化 ProductionHttpClient，使用 async with 管理并挂载到 app.state.http_client
    # 在 yield 前完成连接池初始化，在 yield 后安全退出连接池
    async with ProductionHttpClient(base_url=settings.llm_base_url) as http_client:
        llm_client = NativeLLMClient(
            settings=settings, http_client=http_client, token_guard=token_guard
        )
        app.state.llm_client = llm_client
        logger.info("全局 NativeLLMClient 引擎挂载就绪")
        yield
        logger.info("正在释放网关全局连接池资源...")

    logger.info("👋 服务已安全关闭")


app = FastAPI(
    title="AI Engine Core Gateway",
    version="0.1.0",
    lifespan=lifespan,
)

# 配置跨域中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(chat_router)
