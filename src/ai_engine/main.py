from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ai_engine.api.v1.chat import router as chat_router
from ai_engine.core.config import get_settings
from ai_engine.core.http_client import ProductionHttpClient


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """
    ASGI Lifespan 协议：应用生命周期钩子
    负责全局连接池的单例初始化与停机清理
    """
    settings = get_settings()
    print(f"🚀 [{settings.app_env.upper()}] 正在启动 {settings.app_name}...")

    # TODO 1: 实例化 ProductionHttpClient，使用 async with 管理并挂载到 app.state.http_client
    # 在 yield 前完成连接池初始化，在 yield 后安全退出连接池
    async with ProductionHttpClient(base_url=settings.llm_base_url) as client:
        app.state.http_client = client
        print("✅ 全局 HTTP 客户端连接池已挂载就绪")
        yield
        print("🛑 正在释放全局连接池资源...")

    print("👋 服务已安全关闭")


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
