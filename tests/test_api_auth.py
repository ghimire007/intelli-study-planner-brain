"""Every route that touches a student's data must reject an anonymous caller.

This is the regression guard for the hole this work closed: chat had no auth at
all, so anyone holding a session UUID could read somebody else's conversation.
No database is needed — authentication fails on the missing cookie first.
"""
import uuid

import httpx
import pytest
from app.main import app

pytestmark = pytest.mark.smoke

SESSION_ID = uuid.uuid4()
CREDENTIAL_ID = uuid.uuid4()

PROTECTED = [
    ("GET", "/api/v1/auth/me"),
    ("POST", "/api/v1/chat"),
    ("POST", f"/api/v1/chat/{SESSION_ID}"),
    ("GET", f"/api/v1/chat/{SESSION_ID}"),
    ("GET", "/api/v1/keys"),
    ("GET", "/api/v1/keys/providers"),
    ("POST", "/api/v1/keys"),
    ("PATCH", f"/api/v1/keys/{CREDENTIAL_ID}"),
    ("DELETE", f"/api/v1/keys/{CREDENTIAL_ID}"),
    ("POST", f"/api/v1/keys/{CREDENTIAL_ID}/verify"),
]


@pytest.fixture
async def client():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.parametrize(("method", "path"), PROTECTED, ids=[f"{m} {p}" for m, p in PROTECTED])
async def test_requires_a_signed_in_student(client, method, path) -> None:
    response = await client.request(method, path, json={"message": "hi"})
    assert response.status_code == 401, response.text


async def test_health_stays_open(client) -> None:
    assert (await client.get("/health")).status_code == 200


def test_no_route_can_hand_back_a_stored_key() -> None:
    """There is deliberately no read-a-key endpoint. Keep it that way."""
    key_routes = [
        (sorted(r.methods), r.path)
        for r in app.routes
        if getattr(r, "path", "").startswith("/api/v1/keys")
    ]
    # A GET on a single credential would be the shape that leaks one.
    assert not [
        path for methods, path in key_routes if "GET" in methods and "{credential_id}" in path
    ]


# ── how you sign in from /docs ────────────────────────────────────────────────


def test_protected_routes_are_padlocked_in_the_openapi_schema() -> None:
    """Without this, /docs gives no hint that these endpoints need a session."""
    schema = app.openapi()
    secured = {
        path
        for path, ops in schema["paths"].items()
        for op in ops.values()
        if op.get("security")
    }
    assert "/api/v1/keys" in secured
    assert "/api/v1/chat" in secured
    assert "/api/v1/auth/me" in secured
    # Signing in must not itself require being signed in.
    assert "/api/v1/auth/login" not in secured
    assert "/api/v1/auth/register" not in secured
    assert "/api/v1/auth/forgot-password" not in secured
    assert "/api/v1/auth/reset-password" not in secured


def test_the_cookie_is_the_only_documented_way_in() -> None:
    schemes = app.openapi()["components"]["securitySchemes"]
    assert schemes["Session cookie"]["in"] == "cookie"
    assert list(schemes) == ["Session cookie"]
