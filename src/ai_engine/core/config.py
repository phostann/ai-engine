from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """全局强类型配置中心"""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=False, extra="ignore"
    )

    # 基础服务配置
    app_name: str = "AI-Engine"
    app_env: Literal["development", "staging", "production"] = "development"
    debug: bool = False

    # 大模型基础配置（Field(...) 表示必填，若配置文件未配置，则启动报错）
    llm_api_key: str = Field(..., description="大模型 API 密钥")
    llm_base_url: str = Field(default="https://api.openai.com/v1", description="大模型接口地址")
    llm_model: str = Field(default="gpt-4o-mini", description="模型名称")

    @property
    def masked_api_key(self) -> str:
        """脱敏 API Key"""
        if len(self.llm_api_key) <= 8:
            return "***"

        return f"{self.llm_api_key[:4]}...{self.llm_api_key[-4:]}"


@lru_cache
def get_settings() -> Settings:
    """使用 @lru_cache 实现单例模式，避免每次读取都重复读取磁盘 .env 文件"""
    return Settings()
