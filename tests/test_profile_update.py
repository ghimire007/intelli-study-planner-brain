import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import httpx
import pytest
from app.api.deps import get_current_user
from app.core.database import get_db
from app.main import app
from app.models.auth import User

pytestmark = pytest.mark.smoke


async def test_profile_save_and_email_change_guard():
    user = User(id=uuid.uuid4(), email="demo@example.com", display_name="Demo",
                degree_code="766", elective_interests=[], password_hash="unused",
                created_at=datetime.now(timezone.utc))
    db = AsyncMock()
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = lambda: db
    profile = dict(email=user.email, display_name="Demo Student", degree_code="766",
                   commencement_year=2026, campus="Wollongong", major=None,
                   elective_interests=["Cloud Computing"])
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                     base_url="http://test") as client:
            response = await client.patch("/api/v1/auth/me", json=profile)
            assert response.status_code == 200, response.text
            assert response.json()["commencement_year"] == 2026
            assert response.json()["elective_interests"] == ["Cloud Computing"]
            db.commit.assert_awaited_once()
            response = await client.get("/api/v1/auth/me")
            assert response.json()["campus"] == "Wollongong"
            response = await client.patch("/api/v1/auth/me", json={**profile, "email": "other@example.com"})
            assert response.status_code == 400
            assert user.email == "demo@example.com"
            db.commit.assert_awaited_once()
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
async def profile_client(tmp_path):
    from app.models.auth import AuthSession
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'profiles.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(User.__table__.create)
        await conn.run_sync(AuthSession.__table__.create)
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def database():
        async with sessions() as session:
            yield session

    previous = app.dependency_overrides.copy()
    app.dependency_overrides[get_db] = database
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                     base_url="https://test") as client:
            yield client, sessions
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)
        await engine.dispose()


async def register_profile(client, email="student@example.com"):
    response = await client.post("/api/v1/auth/register", json={
        "email": email, "password": " password123 ", "display_name": "Student",
    })
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.parametrize("interests", [[], ["Cloud Computing", "Security"]])
async def test_preferences_persist_and_partial_updates(profile_client, interests):
    client, sessions = profile_client
    user = await register_profile(client)
    profile = {"degree_code": "769", "commencement_year": 2026,
               "campus": "Wollongong", "major": "Computing", "elective_interests": interests}
    saved = await client.patch("/api/v1/auth/me", json=profile)
    assert saved.status_code == 200, saved.text
    assert all(saved.json()[key] == value for key, value in profile.items())
    updated = await client.patch("/api/v1/auth/me", json={"display_name": "New Name"})
    assert updated.status_code == 200
    assert updated.json()["display_name"] == "New Name"
    fetched = await client.get("/api/v1/auth/me")
    assert all(fetched.json()[key] == value for key, value in profile.items())
    # New database session, independent of the request's identity map.
    async with sessions() as db:
        stored = await db.get(User, uuid.UUID(user["id"]))
        assert stored.elective_interests == interests
        assert stored.degree_code == "769"
        assert not hasattr(stored, "current_password")
    cleared = await client.patch("/api/v1/auth/me", json={"elective_interests": [], "major": None})
    assert cleared.json()["elective_interests"] == []
    assert cleared.json()["major"] is None
    assert (await client.get("/api/v1/auth/me")).json()["elective_interests"] == []


async def test_authentication_and_account_isolation(profile_client):
    client, _ = profile_client
    assert (await client.patch("/api/v1/auth/me", json={})).status_code == 401
    first = await register_profile(client)
    first_cookies = dict(client.cookies)
    await register_profile(client, "second@example.com")
    assert (await client.patch("/api/v1/auth/me", json={"campus": "Sydney"})).status_code == 200
    attempt = await client.patch("/api/v1/auth/me", json={"id": first["id"], "campus": "Other"})
    assert attempt.status_code == 422
    client.cookies.clear()
    client.cookies.update(first_cookies)
    profile = (await client.get("/api/v1/auth/me")).json()
    assert profile["id"] == first["id"]
    assert profile["campus"] is None


async def test_email_verification_and_duplicate_email(profile_client):
    from app.services.auth_service import AuthService

    client, sessions = profile_client
    await register_profile(client, "taken@example.com")
    user = await register_profile(client)
    for password in [None, "wrong-password", "password123"]:
        payload = {"email": "new@example.com", "display_name": "Must not save"}
        if password is not None:
            payload["current_password"] = password
        response = await client.patch("/api/v1/auth/me", json=payload)
        assert response.status_code == 400
        assert (await client.get("/api/v1/auth/me")).json()["display_name"] == "Student"
    duplicate = await client.patch("/api/v1/auth/me", json={
        "email": "taken@example.com", "current_password": " password123 ",
    })
    assert duplicate.status_code == 409
    unchanged = await client.patch("/api/v1/auth/me", json={"email": " STUDENT@example.com "})
    assert unchanged.status_code == 200
    changed = await client.patch("/api/v1/auth/me", json={
        "email": " NEW@example.com ", "current_password": " password123 ",
    })
    assert changed.status_code == 200, changed.text
    assert changed.json()["email"] == "new@example.com"
    assert "current_password" not in changed.json()
    assert "password_hash" not in changed.json()
    assert (await client.get("/api/v1/auth/me")).json()["email"] == "new@example.com"
    async with sessions() as db:
        stored = await db.get(User, uuid.UUID(user["id"]))
        assert AuthService._verify_password(stored.password_hash, " password123 ")
    response = await client.post("/api/v1/auth/login", json={
        "email": "new@example.com", "password": " password123 ",
    })
    assert response.status_code == 200


@pytest.mark.parametrize("payload", [
    {"email": None}, {"email": "invalid"}, {"degree_code": None}, {"degree_code": " "},
    {"commencement_year": 1800}, {"commencement_year": "2026"}, {"campus": "x" * 33},
    {"major": "x" * 121}, {"display_name": " "}, {"elective_interests": None},
    {"elective_interests": [""]}, {"elective_interests": "Cloud"},
    {"password_hash": "replacement"},
])
async def test_invalid_profile_is_rejected(profile_client, payload):
    client, _ = profile_client
    await register_profile(client)
    response = await client.patch("/api/v1/auth/me", json=payload)
    assert response.status_code == 422, response.text
