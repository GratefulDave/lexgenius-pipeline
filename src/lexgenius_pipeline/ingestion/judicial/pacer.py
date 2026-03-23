from __future__ import annotations

from lexgenius_pipeline.common.models import IngestionQuery, NormalizedRecord, Watermark
from lexgenius_pipeline.common.types import HealthStatus, SourceTier
from lexgenius_pipeline.ingestion.base import BaseConnector
from lexgenius_pipeline.settings import Settings, get_settings


class PACERConnector(BaseConnector):
    """PACER federal court docket connector (stub — requires login credentials).

    PACER (Public Access to Court Electronic Records) requires authenticated
    sessions. This stub returns empty results until credentials are configured
    and a login flow is implemented.
    """

    connector_id = "judicial.pacer.rss"
    source_tier = SourceTier.JUDICIAL
    source_label = "PACER Federal Courts"
    supports_incremental = False

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    async def fetch_latest(
        self,
        query: IngestionQuery,
        watermark: Watermark | None = None,
    ) -> list[NormalizedRecord]:
        return []

    async def health_check(self) -> HealthStatus:
        # PACER requires credentials — report DEGRADED until auth is implemented
        return HealthStatus.DEGRADED
