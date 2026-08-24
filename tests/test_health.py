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
