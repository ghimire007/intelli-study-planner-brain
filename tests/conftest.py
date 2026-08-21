"""Root pytest configuration (CI-safe)."""
from __future__ import annotations

import asyncio
import sys

import pytest

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--llm",
        action="store",
        default="fake",
        choices=("fake", "gemini"),
        help="Reserved LLM backend flag for future eval suites. Default: fake.",
    )
