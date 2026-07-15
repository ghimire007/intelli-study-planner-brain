"""LangGraph's Postgres checkpointer — owns conversation/thread state.

This is deliberately separate from app/core/database.py's SQLAlchemy engine:
- database.py / Alembic still own our own domain tables (chat_session, chat_message,
  handbook, ...) — anything we query or migrate by hand.
- This module owns only the four checkpoint_* tables LangGraph manages itself
  (created/migrated by checkpointer.setup(), not Alembic). See ADR note in
  app/agents/graph.py for why the two are kept apart.
"""
import logging

from psycopg_pool import AsyncConnectionPool
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from app.core.config import settings

logger = logging.getLogger("uvicorn")

_pool: AsyncConnectionPool | None = None
_saver: AsyncPostgresSaver | None = None


def _to_psycopg_dsn(sqlalchemy_url: str) -> str:
    """SQLAlchemy uses 'postgresql+psycopg_async://...'; psycopg wants a plain 'postgresql://...'."""
    return sqlalchemy_url.replace("postgresql+psycopg_async://", "postgresql://", 1)


async def connect_checkpointer() -> None:
    global _pool, _saver
    _pool = AsyncConnectionPool(
        conninfo=_to_psycopg_dsn(settings.DATABASE_URL),
        open=False,
        # Small and explicit: the Supabase pgbouncer pooler (port 6543) caps
        # concurrent connections tightly — psycopg_pool's default min_size=4
        # silently over-requests against it, leaving dead connections in the
        # pool that later calls hang waiting on.
        min_size=1,
        max_size=5,
        # prepare_threshold=None disables server-side prepared statements —
        # required because DATABASE_URL points at Supabase's pgbouncer
        # transaction-mode pooler (port 6543), which doesn't preserve prepared
        # statements across the physical connections it multiplexes.
        kwargs={"autocommit": True, "prepare_threshold": None},
    )
    await _pool.open(wait=True, timeout=15)
    _saver = AsyncPostgresSaver(conn=_pool)
    await _saver.setup()  # idempotent — creates/migrates checkpoint_* tables on first run
    logger.info("LangGraph checkpointer connected (checkpoint_* tables ready)")


async def disconnect_checkpointer() -> None:
    global _pool, _saver
    if _pool is not None:
        await _pool.close()
    _pool = None
    _saver = None
    logger.info("LangGraph checkpointer disconnected")


def get_checkpointer() -> AsyncPostgresSaver:
    if _saver is None:
        raise RuntimeError("Checkpointer not initialised — connect_checkpointer() must run at startup")
    return _saver
