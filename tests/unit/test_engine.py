from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from lexgenius_pipeline.db.engine import create_engine, create_session_factory
from lexgenius_pipeline.settings import Settings


def _sqlite_settings(**kwargs) -> Settings:
    defaults = dict(db_backend="sqlite", db_path=":memory:")
    defaults.update(kwargs)
    return Settings(**defaults)


class TestCreateEngine:
    def test_returns_async_engine(self):
        engine = create_engine(_sqlite_settings())
        assert isinstance(engine, AsyncEngine)

    def test_sqlite_url_from_path(self):
        settings = _sqlite_settings(db_path="test.db")
        engine = create_engine(settings)
        assert "sqlite+aiosqlite" in str(engine.url)
        assert "test.db" in str(engine.url)

    def test_explicit_db_url_takes_precedence(self):
        settings = Settings(
            db_backend="sqlite",
            db_url="sqlite+aiosqlite:///explicit.db",
        )
        engine = create_engine(settings)
        assert "explicit.db" in str(engine.url)

    def test_postgresql_requires_db_url(self):
        settings = Settings(db_backend="postgresql", db_url="")
        with pytest.raises(ValueError, match="LGP_DB_URL"):
            create_engine(settings)


class TestCreateSessionFactory:
    def test_returns_session_on_context(self):
        engine = create_engine(_sqlite_settings())
        factory = create_session_factory(engine)
        sess = factory()
        assert isinstance(sess, AsyncSession)
