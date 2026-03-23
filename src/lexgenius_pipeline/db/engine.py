from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from lexgenius_pipeline.settings import Settings


def _build_url(settings: Settings) -> str:
    if settings.db_url:
        return settings.db_url
    if settings.db_backend == "sqlite":
        return f"sqlite+aiosqlite:///{settings.db_path}"
    raise ValueError(
        "LGP_DB_URL must be set when db_backend='postgresql'"
    )


def create_engine(settings: Settings) -> AsyncEngine:
    """Return an async engine configured from *settings*."""
    url = _build_url(settings)
    connect_args = {"check_same_thread": False} if settings.db_backend == "sqlite" else {}
    return create_async_engine(url, echo=False, connect_args=connect_args)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Return a session factory bound to *engine*."""
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
