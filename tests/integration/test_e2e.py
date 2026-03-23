from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from lexgenius_pipeline.common.models import IngestionQuery
from lexgenius_pipeline.db.base import Base
import lexgenius_pipeline.db.models  # noqa: F401 — registers ORM models
from lexgenius_pipeline.db.repositories.record_repo import RawRecordRepository
from lexgenius_pipeline.ingestion.federal.fda import RecallsConnector
from lexgenius_pipeline.ingestion.federal.federal_register import FederalRegisterConnector
from lexgenius_pipeline.ingestion.registry import ConnectorRegistry
from lexgenius_pipeline.ingestion.runner import IngestionRunner
from lexgenius_pipeline.settings import get_settings


@pytest.mark.live
async def test_ingest_e2e():
    """Full pipeline: register connectors, ingest, verify DB records, test dedup."""
    get_settings.cache_clear()
    settings = get_settings()

    # In-memory SQLite
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sf = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    # Register connectors (no special auth required for basic queries)
    registry = ConnectorRegistry()
    registry.register(FederalRegisterConnector(settings))
    registry.register(RecallsConnector(settings))

    # First ingestion
    query = IngestionQuery(query_terms=["acetaminophen"], max_records=5)
    runner = IngestionRunner(registry, sf)
    metrics = await runner.run_all(query)

    print(
        f"First run: fetched={metrics.records_fetched}, "
        f"written={metrics.records_written}, dupes={metrics.duplicates_skipped}"
    )
    assert metrics.records_fetched > 0, "Should have fetched some records"
    assert metrics.records_written > 0, "Should have written some records"

    # Verify DB
    async with sf() as session:
        repo = RawRecordRepository(session)
        recalls = await repo.list_by_connector("federal.fda.recalls")
        fed_reg = await repo.list_by_connector("federal.federal_register.notices")
        total = len(recalls) + len(fed_reg)
        print(f"DB: {len(recalls)} recalls, {len(fed_reg)} fed register = {total} total")
        assert total == metrics.records_written

    # Second run — watermark filters all already-seen records so nothing is written
    metrics2 = await runner.run_all(query)
    print(
        f"Second run: fetched={metrics2.records_fetched}, "
        f"written={metrics2.records_written}, dupes={metrics2.duplicates_skipped}"
    )
    assert metrics2.records_written == 0, "No new records on second run"
    # Connectors use watermark filtering: records seen before are excluded at
    # fetch time (fetched=0), so duplicates_skipped is 0 — both are valid dedup paths.
    assert metrics2.records_fetched == 0 or metrics2.duplicates_skipped > 0, (
        "Second run should either fetch nothing (watermark) or skip all as duplicates"
    )

    await engine.dispose()
