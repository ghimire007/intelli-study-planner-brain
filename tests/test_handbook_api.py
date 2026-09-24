import httpx
import pytest
from app.core.database import get_db
from app.main import app
from app.models.handbook import Handbook
from app.models.major import Major
from app.models.subject import Subject
from seeds.seed import SEED_DATA

pytestmark = pytest.mark.smoke


@pytest.fixture
async def client(tmp_path):
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'handbook.db'}")
    async with engine.begin() as conn:
        for model in (Handbook, Subject, Major):
            await conn.run_sync(model.__table__.create)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as session:
        session.add_all(Handbook(id=i, **entry) for i, entry in enumerate(SEED_DATA, 1))
        session.add(Subject(id=1, year=2026, code="CSCI433", title="Machine Learning Algorithms and Applications",
                            credit_points=6, url="https://courses.uow.edu.au/subjects/2026/CSCI433",
                            card="# CSCI433", data={"code": "CSCI433"}))
        await session.commit()

    async def database():
        async with sessions() as session:
            yield session

    previous = app.dependency_overrides.copy()
    app.dependency_overrides[get_db] = database
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                     base_url="http://test") as http:
            yield http
    finally:
        app.dependency_overrides = previous
        await engine.dispose()


async def test_lists_seeded_courses_including_deans_scholar_and_honours(client):
    response = await client.get("/api/v1/handbook/courses")
    assert response.status_code == 200
    courses = {(c["course"], c["campus"]): c["title"] for c in response.json()}
    assert "Dean's Scholar" in courses[("1802", "Wollongong")]
    assert "Honours" in courses[("1862", "Wollongong")]


async def test_course_handbook_falls_back_to_any_campus(client):
    response = await client.get("/api/v1/handbook/courses/1802", params={"campus": "Liverpool"})
    assert response.status_code == 200
    body = response.json()
    assert body["campus"] == "Wollongong"
    assert "average of 80%" in body["information"]


async def test_course_handbook_respects_year_ceiling(client):
    assert (await client.get("/api/v1/handbook/courses/1862", params={"year": 2025})).status_code == 404
    assert (await client.get("/api/v1/handbook/courses/1862", params={"year": 2027})).status_code == 200


async def test_unknown_course_is_404(client):
    response = await client.get("/api/v1/handbook/courses/9999")
    assert response.status_code == 404
    assert "9999" in response.json()["detail"]


async def test_course_rules_for_honours_double_degree(client):
    response = await client.get("/api/v1/handbook/courses/1862/rules")
    assert response.status_code == 200
    body = response.json()
    assert body["total_cp"] == 264
    assert body["max_100_level_cp"] == 90
    assert body["capstone_code"] == "CSIT321"
    assert "CSIT214" not in body["core_subjects"]
    assert "MAJ40172" in body["major_core"]


async def test_course_rules_unknown_course_is_404(client):
    assert (await client.get("/api/v1/handbook/courses/9999/rules")).status_code == 404


async def test_subject_lookup_is_case_insensitive(client):
    response = await client.get("/api/v1/handbook/subjects/csci433")
    assert response.status_code == 200
    assert response.json()["credit_points"] == 6
    assert (await client.get("/api/v1/handbook/majors/MAJ00000")).status_code == 404


async def test_policy_topics_cover_honours_and_deans_scholar(client):
    slugs = {t["slug"] for t in (await client.get("/api/v1/handbook/policies")).json()}
    assert {"honours", "deans_scholar"} <= slugs
    honours = (await client.get("/api/v1/handbook/policies/honours")).json()
    assert "77.5%" in honours["content"]
    assert (await client.get("/api/v1/handbook/policies/nope")).status_code == 404
