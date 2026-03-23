from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from lexgenius_pipeline.db.models.ingestion import RawRecord, SourceCheckpoint
from lexgenius_pipeline.db.repositories.checkpoint_repo import CheckpointRepository
from lexgenius_pipeline.db.repositories.record_repo import RawRecordRepository


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _raw_record(**kwargs) -> RawRecord:
    defaults = dict(
        connector_id="fda",
        record_type="recall",
        source_label="FDA Recalls",
        source_url="https://example.com/recall/1",
        fingerprint=str(uuid.uuid4()),
        title="Test Recall",
        summary="A test recall record",
        published_at=_now(),
    )
    defaults.update(kwargs)
    return RawRecord(**defaults)


def _checkpoint(**kwargs) -> SourceCheckpoint:
    defaults = dict(
        scope_key="fda:recalls",
        connector_id="fda",
        last_fetched_at=_now(),
    )
    defaults.update(kwargs)
    return SourceCheckpoint(**defaults)


class TestRawRecordRepository:
    async def test_add_and_get(self, session: AsyncSession):
        repo = RawRecordRepository(session)
        record = _raw_record()
        saved = await repo.add(record)
        assert saved.id is not None

        fetched = await repo.get(saved.id)
        assert fetched is not None
        assert fetched.title == "Test Recall"

    async def test_get_missing_returns_none(self, session: AsyncSession):
        repo = RawRecordRepository(session)
        assert await repo.get("nonexistent-id") is None

    async def test_delete(self, session: AsyncSession):
        repo = RawRecordRepository(session)
        record = await repo.add(_raw_record())
        await repo.delete(record.id)
        assert await repo.get(record.id) is None

    async def test_get_by_fingerprint(self, session: AsyncSession):
        repo = RawRecordRepository(session)
        fp = "unique-fingerprint-abc"
        await repo.add(_raw_record(fingerprint=fp))

        found = await repo.get_by_fingerprint(fp)
        assert found is not None
        assert found.fingerprint == fp

    async def test_fingerprint_exists(self, session: AsyncSession):
        repo = RawRecordRepository(session)
        fp = "fp-exists-test"
        assert not await repo.fingerprint_exists(fp)
        await repo.add(_raw_record(fingerprint=fp))
        assert await repo.fingerprint_exists(fp)

    async def test_list_by_connector(self, session: AsyncSession):
        repo = RawRecordRepository(session)
        await repo.add(_raw_record(connector_id="fda", fingerprint="fp-1"))
        await repo.add(_raw_record(connector_id="fda", fingerprint="fp-2"))
        await repo.add(_raw_record(connector_id="sec", fingerprint="fp-3"))

        results = await repo.list_by_connector("fda")
        assert len(results) == 2
        assert all(r.connector_id == "fda" for r in results)

    async def test_list_by_type(self, session: AsyncSession):
        repo = RawRecordRepository(session)
        await repo.add(_raw_record(record_type="recall", fingerprint="fp-r1"))
        await repo.add(_raw_record(record_type="filing", fingerprint="fp-f1"))

        recalls = await repo.list_by_type("recall")
        assert len(recalls) == 1
        assert recalls[0].record_type == "recall"


class TestCheckpointRepository:
    async def test_add_and_get(self, session: AsyncSession):
        repo = CheckpointRepository(session)
        cp = await repo.add(_checkpoint())
        assert cp.id is not None

        fetched = await repo.get(cp.id)
        assert fetched is not None
        assert fetched.scope_key == "fda:recalls"

    async def test_get_missing_returns_none(self, session: AsyncSession):
        repo = CheckpointRepository(session)
        assert await repo.get("no-such-id") is None

    async def test_delete(self, session: AsyncSession):
        repo = CheckpointRepository(session)
        cp = await repo.add(_checkpoint())
        await repo.delete(cp.id)
        assert await repo.get(cp.id) is None

    async def test_get_by_scope(self, session: AsyncSession):
        repo = CheckpointRepository(session)
        await repo.add(_checkpoint(scope_key="fda:recalls", connector_id="fda"))

        found = await repo.get_by_scope("fda:recalls", "fda")
        assert found is not None
        assert found.connector_id == "fda"

    async def test_get_by_scope_missing(self, session: AsyncSession):
        repo = CheckpointRepository(session)
        result = await repo.get_by_scope("missing", "missing")
        assert result is None

    async def test_upsert_creates_new(self, session: AsyncSession):
        repo = CheckpointRepository(session)
        cp = _checkpoint(scope_key="epa:data", connector_id="epa")
        saved = await repo.upsert(cp)
        assert saved.id is not None

    async def test_upsert_updates_existing(self, session: AsyncSession):
        repo = CheckpointRepository(session)
        original = await repo.add(_checkpoint(scope_key="sec:filings", connector_id="sec"))
        original_id = original.id

        new_time = _now()
        updated = await repo.upsert(
            SourceCheckpoint(
                scope_key="sec:filings",
                connector_id="sec",
                last_fetched_at=new_time,
                last_record_date=new_time,
            )
        )
        assert updated.id == original_id
        assert updated.last_fetched_at == new_time
        assert updated.last_record_date == new_time
