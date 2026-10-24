"""运行时配置，全部通过环境变量注入（env_prefix=GATEWAY_）。

示例：
  GATEWAY_UPSTREAM_BASE_URL=https://api.openai.com/v1
  GATEWAY_UPSTREAM_API_KEY=sk-xxxx            # 服务端调用上游用的密钥
  GATEWAY_GATEWAY_API_KEYS=k1,k2              # 允许通过网关的客户端密钥
  GATEWAY_RATE_LIMIT_RPM=60                   # 每个客户端密钥每分钟请求上限
"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GATEWAY_", env_file=".env", extra="ignore")

    app_name: str = "llm-gateway"
    upstream_base_url: str = "https://api.openai.com/v1"
    upstream_api_key: str = ""
    gateway_api_keys: str = ""  # 逗号分隔，客户端访问网关时必须携带其中一个
    rate_limit_rpm: int = 60
    models_cache_ttl: int = 60  # /v1/models 响应的内存缓存秒数

    @property
    def allowed_keys(self) -> set[str]:
        return {k.strip() for k in self.gateway_api_keys.split(",") if k.strip()}


@lru_cache
def get_settings() -> Settings:
    return Settings()
