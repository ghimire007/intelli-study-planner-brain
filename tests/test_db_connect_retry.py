"""DB connect retries transient failures without needing a real database."""

from unittest.mock import MagicMock

import pytest
from app.core import database
from sqlalchemy.exc import OperationalError


class _FakeEngine:
    def __init__(self, failures: int) -> None:
        self.failures = failures
        self.attempts = 0

    def connect(self):
        self.attempts += 1
        if self.attempts <= self.failures:
            raise OperationalError("SELECT 1", {}, Exception("refused"))
        conn = MagicMock()
        conn.__aenter__ = MagicMock(return_value=_done(conn))
        conn.__aexit__ = MagicMock(return_value=_done(None))
        conn.execute = MagicMock(return_value=_done(None))
        return conn


def _done(value):
    async def coro():
        return value

    return coro()


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    delays: list[float] = []

    async def fake_sleep(delay: float) -> None:
        delays.append(delay)

    monkeypatch.setattr(database.asyncio, "sleep", fake_sleep)
    return delays


async def test_connect_succeeds_after_three_failures(monkeypatch, no_sleep) -> None:
    fake = _FakeEngine(failures=3)
    monkeypatch.setattr(database, "engine", fake)
    await database.connect()
    assert fake.attempts == 4
    assert no_sleep == [1.0, 2.0, 4.0]


async def test_connect_raises_after_exhausting_retries(monkeypatch) -> None:
    fake = _FakeEngine(failures=99)
    monkeypatch.setattr(database, "engine", fake)
    with pytest.raises(OperationalError):
        await database.connect()
    assert fake.attempts == database.CONNECT_RETRIES + 1
