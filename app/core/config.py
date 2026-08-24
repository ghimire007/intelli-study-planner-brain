from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    APP_PORT: int = 7777
    DATABASE_URL: str = ""
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-3.5-flash"
    AUTH_COOKIE_NAME: str = "courseo_session"
    AUTH_SESSION_DAYS: int = 30
    AUTH_COOKIE_SECURE: bool = False
    # Comma-separated frontend origins (no trailing slash). Local Vite is included by default.
    CORS_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173"

    def cors_origin_list(self) -> list[str]:
        return [
            origin.strip().rstrip("/")
            for origin in self.CORS_ORIGINS.split(",")
            if origin.strip()
        ]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
