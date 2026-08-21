"""CI-safe health checks — no DB or LLM required."""

from app.main import app


def test_health_route_registered() -> None:
    paths = {getattr(route, "path", None) for route in app.routes}
    assert "/health" in paths
