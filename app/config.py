import secrets
from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    debug: bool = False
    use_fakeredis: bool = False

    redis_url: str = "redis://localhost:6379"
    redis_password: str = ""          # injected into redis_url if set

    cache_ttl_search: int = 600
    cache_ttl_article: int = 1800

    rate_limit_search: str = "30/minute"
    rate_limit_read: str = "60/minute"
    rate_limit_image: str = "120/minute"

    admin_path: str = ""
    admin_password_hash: str = ""
    admin_secret_key: str = secrets.token_hex(32)

    max_download_size: int = 8_388_608  # 8 MB
    request_timeout: float = 15.0

    ddg_url: str = "https://html.duckduckgo.com/html/"

    # Reddit OAuth2 (optional — enables post details + comments)
    # Register a free "script" app at https://www.reddit.com/prefs/apps
    reddit_client_id: str = ""
    reddit_client_secret: str = ""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    @property
    def effective_redis_url(self) -> str:
        """Returns redis_url as-is (password already embedded via .env)."""
        return self.redis_url


@lru_cache()
def get_settings() -> Settings:
    return Settings()
