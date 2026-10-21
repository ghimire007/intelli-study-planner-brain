"""Fixtures for the live-model accuracy suite (see test_accuracy.py)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from app.core.config import settings
from app.llm.config import LLMConfig
from app.llm.registry import Provider
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from tests.e2e import summary

BASELINE_PATH = Path(__file__).parent / "baseline.json"


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption("--e2e-runs", type=int, default=1, help="Plans generated per case (CI uses 3).")
    parser.addoption(
        "--e2e-update-baseline", action="store_true",
        help="Record the failures seen in baseline.json instead of failing on them.",
    )


def pytest_sessionfinish(session: pytest.Session) -> None:
    if summary.NEW_BASELINE:
        known = json.loads(BASELINE_PATH.read_text())
        merged = {**known, **summary.NEW_BASELINE}
        BASELINE_PATH.write_text(json.dumps({k: v for k, v in sorted(merged.items()) if v}, indent=2) + "\n")


def pytest_terminal_summary(terminalreporter) -> None:
    if summary.RUNS:
        terminalreporter.section("LLM accuracy")
        for line in summary.report():
            terminalreporter.write_line(line)


@pytest.fixture(scope="session")
def runs(request: pytest.FixtureRequest) -> int:
    return request.config.getoption("--e2e-runs")


@pytest.fixture(scope="session")
def llm_config(request: pytest.FixtureRequest) -> LLMConfig:
    if request.config.getoption("--llm") == "fake":
        pytest.skip("live-model suite: run with --llm=gemini")
    if not settings.GEMINI_API_KEY or settings.GEMINI_API_KEY == "ci-not-used":
        pytest.skip("GEMINI_API_KEY is not set")
    return LLMConfig(provider=Provider.GEMINI, model=settings.GEMINI_MODEL, api_key=settings.GEMINI_API_KEY)


@pytest.fixture
async def db(llm_config):
    # A fresh engine per test: the app's shared pool is bound to one event loop.
    engine = create_async_engine(settings.DATABASE_URL, connect_args={"prepare_threshold": None}, poolclass=NullPool)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            try:
                await session.execute(text("SELECT 1 FROM handbook LIMIT 1"))
            except Exception as exc:
                pytest.skip(f"database not reachable or not migrated and seeded ({type(exc).__name__})")
            yield session
    finally:
        await engine.dispose()
