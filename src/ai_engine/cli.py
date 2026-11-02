import uvicorn

from ai_engine.core.config import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "ai_engine.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        log_level="debug" if settings.debug else "info",
    )


if __name__ == "__main__":
    main()
