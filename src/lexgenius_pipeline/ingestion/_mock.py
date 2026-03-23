from __future__ import annotations

from datetime import datetime, timezone

from lexgenius_pipeline.common.models import IngestionQuery, NormalizedRecord, Watermark
from lexgenius_pipeline.common.types import HealthStatus, RecordType, SourceTier
from lexgenius_pipeline.ingestion.base import BaseConnector
from lexgenius_pipeline.ingestion.normalize import generate_fingerprint


class MockConnector(BaseConnector):
    """Test double for BaseConnector."""

    connector_id = "test.mock"
    source_tier = SourceTier.COMMERCIAL
    source_label = "Mock Source"
    supports_incremental = True

    def __init__(
        self,
        records: list[NormalizedRecord] | None = None,
        connector_id: str | None = None,
        ignore_watermark: bool = False,
    ) -> None:
        if connector_id is not None:
            self.connector_id = connector_id
        self._records: list[NormalizedRecord] = records or []
        self._ignore_watermark = ignore_watermark

    async def fetch_latest(
        self,
        query: IngestionQuery,
        watermark: Watermark | None = None,
    ) -> list[NormalizedRecord]:
        if self._ignore_watermark or watermark is None or watermark.last_record_date is None:
            return list(self._records)
        return [r for r in self._records if r.published_at > watermark.last_record_date]

    async def health_check(self) -> HealthStatus:
        return HealthStatus.HEALTHY


def create_mock_record(
    title: str = "Test Record",
    source_url: str = "https://example.com/test",
    connector_id: str = "test.mock",
    published_at: datetime | None = None,
) -> NormalizedRecord:
    dt = published_at or datetime(2024, 1, 1, tzinfo=timezone.utc)
    fingerprint = generate_fingerprint(connector_id, source_url, title, dt)
    return NormalizedRecord(
        title=title,
        summary="Test summary",
        record_type=RecordType.NEWS,
        source_connector_id=connector_id,
        source_label="Mock Source",
        source_url=source_url,
        published_at=dt,
        fingerprint=fingerprint,
    )
