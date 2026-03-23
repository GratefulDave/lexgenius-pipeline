from __future__ import annotations

from abc import ABC, abstractmethod

from lexgenius_pipeline.common.models import IngestionQuery, NormalizedRecord, Watermark
from lexgenius_pipeline.common.types import HealthStatus, SourceTier


class BaseConnector(ABC):
    """Abstract base for all data source connectors."""

    connector_id: str          # e.g. "federal.fda.faers"
    source_tier: SourceTier
    source_label: str          # human-readable, e.g. "FDA FAERS"
    supports_incremental: bool = True

    @abstractmethod
    async def fetch_latest(
        self,
        query: IngestionQuery,
        watermark: Watermark | None = None,
    ) -> list[NormalizedRecord]:
        """Fetch new records, optionally resuming from *watermark*."""

    @abstractmethod
    async def health_check(self) -> HealthStatus:
        """Return the health status of this connector's data source."""

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self.connector_id}>"
