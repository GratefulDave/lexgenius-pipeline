from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lexgenius_pipeline.common.models import IngestionQuery, NormalizedRecord, RunMetrics
from lexgenius_pipeline.db.models.ingestion import IngestionRun
from lexgenius_pipeline.db.repositories import RawRecordRepository
from lexgenius_pipeline.ingestion.base import BaseConnector
from lexgenius_pipeline.ingestion.metrics import ConnectorMetrics, MetricsCollector
from lexgenius_pipeline.ingestion.normalize import normalize_to_orm
from lexgenius_pipeline.ingestion.registry import ConnectorRegistry
from lexgenius_pipeline.ingestion.watermarks import get_watermark, update_watermark


class IngestionRunner:
    def __init__(
        self,
        registry: ConnectorRegistry,
        session_factory: async_sessionmaker[AsyncSession],
        max_concurrent: int = 5,
    ) -> None:
        self._registry = registry
        self._session_factory = session_factory
        self._max_concurrent = max_concurrent

    async def run_all(self, query: IngestionQuery) -> RunMetrics:
        connectors = self._registry.list_all()
        if query.connector_ids:
            connectors = [c for c in connectors if c.connector_id in query.connector_ids]

        semaphore = asyncio.Semaphore(self._max_concurrent)
        results: list[ConnectorMetrics] = []
        lock = asyncio.Lock()

        async def _run_one(connector: BaseConnector) -> None:
            async with semaphore:
                cm = await self.run_connector(connector, query)
                async with lock:
                    results.append(cm)

        async with asyncio.TaskGroup() as tg:
            for connector in connectors:
                tg.create_task(_run_one(connector))

        return RunMetrics(
            records_fetched=sum(m.records_fetched for m in results),
            records_written=sum(m.records_written for m in results),
            duplicates_skipped=sum(m.duplicates_skipped for m in results),
            errors=sum(m.errors for m in results),
            duration_ms=sum(m.duration_ms for m in results),
        )

    async def run_connector(
        self, connector: BaseConnector, query: IngestionQuery
    ) -> ConnectorMetrics:
        collector = MetricsCollector()
        collector.start(connector.connector_id)
        now = datetime.now(timezone.utc)

        async with self._session_factory() as session:
            async with session.begin():
                run = IngestionRun(
                    connector_id=connector.connector_id,
                    status="running",
                    started_at=now,
                )
                session.add(run)
                await session.flush()

                try:
                    watermark = await get_watermark(
                        session, connector.connector_id, connector.connector_id
                    )
                    records = await connector.fetch_latest(query, watermark)
                    collector.record_fetch(connector.connector_id, len(records))

                    await self._persist_records(session, records, connector.connector_id, collector)

                    if records:
                        last_date = max(r.published_at for r in records)
                        await update_watermark(
                            session, connector.connector_id, connector.connector_id, last_date
                        )

                    m = collector.get(connector.connector_id)
                    assert m is not None
                    run.status = "completed"
                    run.completed_at = datetime.now(timezone.utc)
                    run.records_fetched = m.records_fetched
                    run.records_written = m.records_written
                    run.duplicates_skipped = m.duplicates_skipped
                    run.errors = m.errors

                except Exception:
                    collector.record_error(connector.connector_id)
                    run.status = "failed"
                    run.completed_at = datetime.now(timezone.utc)
                    m = collector.get(connector.connector_id)
                    run.errors = m.errors if m else 1

        collector.finish(connector.connector_id)
        result = collector.get(connector.connector_id)
        assert result is not None
        return result

    async def _persist_records(
        self,
        session: AsyncSession,
        records: list[NormalizedRecord],
        connector_id: str,
        metrics: MetricsCollector,
    ) -> int:
        repo = RawRecordRepository(session)
        written = 0
        for record in records:
            if await repo.fingerprint_exists(record.fingerprint):
                metrics.record_duplicate(connector_id)
            else:
                await repo.add(normalize_to_orm(record))
                metrics.record_write(connector_id, 1)
                written += 1
        return written
