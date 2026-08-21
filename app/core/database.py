import logging

from app.core.config import settings
from sqlalchemy import text
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


async def connect() -> None:
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    logger.info("DB connected")


async def disconnect() -> None:
    await engine.dispose()
    logger.info("DB disconnected")


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
