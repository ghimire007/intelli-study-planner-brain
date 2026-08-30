from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    APP_PORT: int = 7777
    DATABASE_URL: str = ""
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-3.5-flash"
    AUTH_COOKIE_NAME: str = "courseo_session"
    AUTH_SESSION_DAYS: int = 30
    AUTH_COOKIE_SECURE: bool = True
    # "lax" is right when the frontend is served from the same site as the API.
    # When they are different sites — and two *.onrender.com services are, because
    # onrender.com is on the Public Suffix List — the browser drops a lax cookie on
    # every cross-site fetch, so every authenticated call 401s. Use "none" there,
    # which browsers only honour together with AUTH_COOKIE_SECURE=true.
    AUTH_COOKIE_SAMESITE: Literal["lax", "strict", "none"] = "none"
    # Comma-separated frontend origins (no trailing slash). Local Vite is included by default.
    CORS_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173"

    # ── Secrets vault (students' own LLM API keys) ────────────────────────────
    # Master key(s) that wrap each credential's data key. Format "1:<b64>,2:<b64>";
    # a bare base64 value is read as version 1. Every version that ever sealed a row
    # must stay listed here. Generate one with:
    #   python -c "import base64,os;print(base64.b64encode(os.urandom(32)).decode())"
    SECRETS_MASTER_KEYS: str = ""
    # Which of the above seals new secrets. Older versions stay listed above so
    # rows they sealed remain readable.
    SECRETS_ACTIVE_KEY_VERSION: int = 1
    # Prove a key works against its provider before storing it.
    VAULT_VERIFY_ON_WRITE: bool = True
    # Per-user hourly caps on key writes and verifies, so the endpoint can't be used
    # as a free key-validity oracle. In-process, so they are per web worker.
    VAULT_WRITE_LIMIT_PER_HOUR: int = 20
    VAULT_VERIFY_LIMIT_PER_HOUR: int = 30
    # ── Where a student's key actually lives ──────────────────────────────────
    # "local"     — sealed into llm_credential by app/core/crypto.py (no network).
    # "infisical" — held by Infisical; the row keeps only the metadata and a ref.
    # Existing rows record their own backend, so switching this only affects new keys.
    SECRET_BACKEND: Literal["local", "infisical"] = "local"
    INFISICAL_HOST: str = "https://app.infisical.com"
    INFISICAL_CLIENT_ID: str = ""
    INFISICAL_CLIENT_SECRET: str = ""
    INFISICAL_PROJECT_ID: str = ""
    INFISICAL_ENVIRONMENT: str = "dev"
    # Folders must already exist in Infisical, so "/" is the safe default.
    INFISICAL_SECRET_PATH: str = "/"
    INFISICAL_TIMEOUT_SECONDS: float = 10.0

    def infisical_configured(self) -> bool:
        return bool(
            self.INFISICAL_CLIENT_ID
            and self.INFISICAL_CLIENT_SECRET
            and self.INFISICAL_PROJECT_ID
        )

    # Fall back to the project's own GEMINI_API_KEY when a student has no usable
    # key for the provider they need, so the advisor works out of the box. Their
    # own key always wins when they have one — this is only the last rung of the
    # ladder in credential_resolver.py, and it covers Gemini alone, because that
    # is the only provider we hold a key for. Turn it off to force everyone onto
    # their own quota.
    ALLOW_SYSTEM_FALLBACK_KEY: bool = True

    def cookie_misconfigured(self) -> str | None:
        """The one cookie combination browsers silently reject, named plainly."""
        if self.AUTH_COOKIE_SAMESITE == "none" and not self.AUTH_COOKIE_SECURE:
            return (
                "AUTH_COOKIE_SAMESITE=none requires AUTH_COOKIE_SECURE=true — "
                "browsers discard a SameSite=None cookie that is not Secure, so "
                "nobody will be able to stay signed in."
            )
        return None

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
