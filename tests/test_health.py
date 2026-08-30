"""CI-safe health checks — no DB or LLM required."""

from app.core.config import Settings
from app.main import app


def test_health_route_registered() -> None:
    paths = {getattr(route, "path", None) for route in app.routes}
    assert "/health" in paths


def test_cors_origin_list_strips_whitespace_and_slashes() -> None:
    parsed = Settings(
        CORS_ORIGINS=" https://courseo-frontend.onrender.com/ , http://localhost:5173 "
    ).cors_origin_list()
    assert parsed == [
        "https://courseo-frontend.onrender.com",
        "http://localhost:5173",
    ]


def test_lax_cookie_is_the_local_default() -> None:
    assert Settings().AUTH_COOKIE_SAMESITE == "lax"
    assert Settings().cookie_misconfigured() is None


def test_samesite_none_without_secure_is_reported() -> None:
    """Browsers silently discard this combination, so say so at boot."""
    problem = Settings(
        AUTH_COOKIE_SAMESITE="none", AUTH_COOKIE_SECURE=False
    ).cookie_misconfigured()
    assert problem is not None and "AUTH_COOKIE_SECURE=true" in problem


def test_cross_site_production_shape_is_accepted() -> None:
    settings = Settings(AUTH_COOKIE_SAMESITE="none", AUTH_COOKIE_SECURE=True)
    assert settings.cookie_misconfigured() is None
