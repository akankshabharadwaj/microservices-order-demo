"""Async SQLAlchemy engine and session management."""

import asyncio
from collections.abc import AsyncGenerator
import logging

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from .config import get_database_url

logger = logging.getLogger(__name__)
_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = create_async_engine(
            get_database_url(),
            pool_pre_ping=True,
            connect_args={"timeout": 5.0},
        )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _session_factory


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with get_session_factory()() as session:
        yield session


async def init_db() -> None:
    from .models import Base

    retry_delay = 1.0
    while True:
        try:
            async with get_engine().begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            return
        except (SQLAlchemyError, TimeoutError, OSError) as exc:
            logger.warning(
                "Database initialization failed (%s); retrying in %.1f seconds",
                type(exc).__name__,
                retry_delay,
            )
            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, 15.0)


async def close_db() -> None:
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None
