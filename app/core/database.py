import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine, AsyncAttrs
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import text

from app.core.config import settings


class Base(AsyncAttrs, DeclarativeBase):
    pass

logger = logging.getLogger("uvicorn")

engine = create_async_engine(settings.DATABASE_URL)

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
