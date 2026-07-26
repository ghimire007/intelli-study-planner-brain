"""
Global pytest configuration for the IntelliStudy Planner Brain evaluation suite.


Fixtures exposed to tests
-------------------------
- ensure_handbook_seeded : session-scoped, check if 766/2026/Wollongong handbook is seeded, seed otherwise
- db_session             : function-scoped async SQLAlchemy session (rollback transaction ensuring clean database state for each test)
- llm                    : selected LLM backend (FakeLLM default; --llm=gemini for live)
- chat_service           : ChatService wired with db_session + llm
- test_records           : load test records once each session

CLI options
-----------
--llm {fake,gemini}      : backend selector (default: fake; cost-free).
provide a custom llm to mimic gemini to avoid burning tokens

Run examples
------------
    python -m pytest tests/                       # full suite, FakeLLM
    python -m pytest tests/eval --llm=fake -v     # eval only, fake
    python -m pytest tests/eval --llm=gemini -v   # eval only, live Gemini
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import AsyncIterator

import pytest
import pytest_asyncio

# psycopg's async driver on Windows requires the selector event loop policy.
# when not configured, the default on windows is proactor
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

#suppress "Module level import not at top of file" warning

from sqlalchemy import select  # noqa: E402    

from app.core.database import AsyncSessionLocal  # noqa: E402
from app.llm.base import BaseLLM, LLMMessage, LLMResponse  # noqa: E402
from app.llm.gemini import GeminiLLM  # noqa: E402
from app.models.handbook import Handbook  # noqa: E402
from app.services.chat_service import ChatService  # noqa: E402
from seeds.seed import seed as seed_handbook  # noqa: E402


PROJECT_ROOT = Path(__file__).resolve().parent.parent
TEST_RECORDS_DIR = PROJECT_ROOT / "app" / "test_records"


# ---------------------------------------------------------------------------
# CLI options
# Adds --llm={fake,gemini} flag to toggle between mock responses and real APIs.
# Defaults to "fake" to prevent unintended API expenditures during local development.
# ---------------------------------------------------------------------------


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--llm",
        action="store",
        default="fake",
        choices=("fake", "gemini"),
        help=(
            "LLM backend for eval tests. 'fake' returns canned responses for "
            "cost-free wiring tests. 'gemini' calls the real Gemini API."
        ),
    )
    parser.addoption(
        "--n-runs",
        action="store",
        default=10,
        type=int,
        help=(
            "Iterations per profile in the Phase 4 pass-rate sweep "
            "(`test_pass_rate_threshold`). Default: 10. Lower values speed "
            "up live sweeps at the cost of statistical confidence."
        ),
    )


# ---------------------------------------------------------------------------
# Fake LLM — mock responses for cost-free wiring tests
# ---------------------------------------------------------------------------

class FakeLLM(BaseLLM):
    """
    inheriting from BaseLLM (same as GeminiLLM),
    this class implements the identical interface contract
    required by `ChatService`
    Reads the `system_prompt` to trigger two static behaviors:
    1. Transcript Parser -> Returns raw JSON metadata for course handbook lookup.
    2. Study Planner     -> Returns an empty, structured Markdown table skeleton.
    
    """

    @property
    def model_name(self) -> str:
        return "fake-model"

    @property
    def provider_name(self) -> str:
        return "gemini"

    async def chat(
        self,
        system_prompt: str,
        messages: list[LLMMessage],
    ) -> LLMResponse:
        if "Extract the following three fields" in system_prompt:
            content = '{"degree_code": "766", "year": 2026, "campus": "Wollongong"}'
        else:
            content = (
                "**Audit:**\n"
                "- Core: [], count: 0, CP: 0\n"
                "- Core Selection: None, CP: 0\n"
                "- Major Core (None): [], CP: 0\n"
                "- Electives: [], CP: 0\n"
                "- Unspecified CP: 0\n"
                "- **Total CP received: 0**\n\n"
                "**Study Plan:**\n\n"
                "| Year | Session | Subject Code | Subject Name | CP | Notes |\n"
                "|------|---------|-------------|-------------|-----|-------|\n"
                "\n"
                "- Completed: 0 CP\n"
                "- Remaining in plan: 144 CP\n"
                "- **Total: 144 CP**\n"
            )

        return LLMResponse(
            content=content,
            parts=[{"type": "text", "text": content}],
            tokens_in=0,
            tokens_out=0,
            cached_tokens=0,
            cost_usd=0.0,
            model=self.model_name,
            provider=self.provider_name,
        )


# ---------------------------------------------------------------------------
# Session-scoped fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def llm_backend(request: pytest.FixtureRequest) -> str:
    return request.config.getoption("--llm")


@pytest.fixture
def require_live_llm(llm_backend: str) -> None:
    """
    Skip the test when running with `--llm=fake`. Used by Phase 4 to gate
    statistical-stability sweeps behind a real Gemini backend — the canned
    FakeLLM response is intentionally invalid (0-CP plan), so running the
    pass-rate evaluator against it would always score 0% and produce no
    meaningful signal.
    """
    if llm_backend == "fake":
        pytest.skip("requires --llm=gemini (real LLM) for meaningful evaluation")


@pytest_asyncio.fixture
async def ensure_handbook_seeded() -> None:
    """
    Idempotent seed: inserts 766/2026/Wollongong only if missing.

    """
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Handbook).where(
                Handbook.course == "766",
                Handbook.year == 2026,
                Handbook.campus == "Wollongong",
            )
        )
        if result.scalar_one_or_none() is not None:
            return
    await seed_handbook()


# ---------------------------------------------------------------------------
# Test-record loader
# ---------------------------------------------------------------------------

def discover_test_records() -> list[tuple[str, str]]:
    """
    Return `[(stem, content), ...]` for every `.md` in `app/test_records/`,
    sorted by filename. 
    """
    if not TEST_RECORDS_DIR.is_dir():
        raise RuntimeError(f"Test records directory not found: {TEST_RECORDS_DIR}")
    records = [
        (path.stem, path.read_text(encoding="utf-8"))
        for path in sorted(TEST_RECORDS_DIR.glob("*.md"))
    ]
    if not records:
        raise RuntimeError(f"No .md records found under {TEST_RECORDS_DIR}")
    return records


@pytest.fixture(scope="session")
def test_records() -> list[tuple[str, str]]:
    return discover_test_records()


# ---------------------------------------------------------------------------
# Per-test fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def db_session() -> AsyncIterator:
    async with AsyncSessionLocal() as session:
        yield session


@pytest.fixture
def llm(llm_backend: str) -> BaseLLM:
    return GeminiLLM() if llm_backend == "gemini" else FakeLLM()


@pytest_asyncio.fixture
async def chat_service(
    db_session,
    llm: BaseLLM,
    ensure_handbook_seeded,
) -> ChatService:
    """
    The unit-under-test: a fully wired `ChatService` reachable without going
    through FastAPI / HTTP. Phase 1 callers only exercise `start_session`; the
    same fixture serves `continue_session` and `get_history` in later phases.
    """
    return ChatService(db=db_session, llm=llm)
