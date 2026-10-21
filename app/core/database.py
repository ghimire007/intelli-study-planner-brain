import asyncio
import logging

from app.core.config import settings
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncAttrs, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase


class Base(AsyncAttrs, DeclarativeBase):
    pass

logger = logging.getLogger("uvicorn")

engine = create_async_engine(
    settings.DATABASE_URL,
    connect_args={"prepare_threshold": None},
    )

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


CONNECT_RETRIES = 3
CONNECT_BACKOFF_SECONDS = 1.0


async def connect() -> None:
    """Check the DB is reachable, retrying CONNECT_RETRIES times after the first failure."""
    for attempt in range(CONNECT_RETRIES + 1):
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            break
        except (OperationalError, OSError) as exc:
            if attempt == CONNECT_RETRIES:
                raise
            delay = CONNECT_BACKOFF_SECONDS * 2**attempt
            logger.warning(
                "DB connect failed (%s); retry %d/%d in %.1fs",
                exc.__class__.__name__, attempt + 1, CONNECT_RETRIES, delay,
            )
            await asyncio.sleep(delay)
    logger.info("DB connected")


async def disconnect() -> None:
    await engine.dispose()
    logger.info("DB disconnected")


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
