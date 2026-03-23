from __future__ import annotations

from sqlalchemy.pool import NullPool
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from lexgenius_pipeline.settings import Settings


def _build_url(settings: Settings) -> str:
    url = settings.db_url
    if not url:
        if settings.db_backend == "sqlite":
            return f"sqlite+aiosqlite:///{settings.db_path}"
        raise ValueError("LGP_DB_URL must be set when db_backend='postgresql'")
    # Normalise legacy postgres:// scheme to postgresql+asyncpg://
    if url.startswith("postgres://"):
        url = "postgresql+asyncpg://" + url[len("postgres://"):]
    return url


def create_engine(settings: Settings) -> AsyncEngine:
    """Return an async engine configured from *settings*."""
    url = _build_url(settings)
    if settings.db_backend == "sqlite":
        return create_async_engine(url, echo=False, connect_args={"check_same_thread": False})
    # PostgreSQL — Lambda functions are ephemeral, so persistent connection pools are
    # wasteful and can exhaust RDS connections. Use NullPool for Lambda.
    if settings.compute_backend == "lambda":
        return create_async_engine(url, echo=False, poolclass=NullPool)
    return create_async_engine(
        url,
        echo=False,
        pool_size=5,
        max_overflow=10,
        pool_pre_ping=True,
        pool_recycle=3600,
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Return a session factory bound to *engine*."""
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
