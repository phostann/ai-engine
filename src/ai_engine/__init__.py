from ai_engine.core.config import get_settings


def main() -> None:
    settings = get_settings()
    print(f"🚀 [{settings.app_env.upper()}] {settings.app_name} 启动成功！")
    print(f"🤖 当前模型: {settings.llm_model} | 接口地址: {settings.llm_base_url}")
    print(f"🔑 密钥状态: {settings.masked_api_key}")
