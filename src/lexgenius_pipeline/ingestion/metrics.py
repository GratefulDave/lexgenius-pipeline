from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from lexgenius_pipeline.common.models import RunMetrics


@dataclass
class ConnectorMetrics:
    connector_id: str
    records_fetched: int = 0
    records_written: int = 0
    duplicates_skipped: int = 0
    errors: int = 0
    duration_ms: float = 0.0
    started_at: datetime | None = None
    finished_at: datetime | None = None
    _start_mono: float = field(default=0.0, repr=False)


class MetricsCollector:
    """Collects per-connector metrics during an ingestion run."""

    def __init__(self) -> None:
        self._metrics: dict[str, ConnectorMetrics] = {}

    def start(self, connector_id: str) -> None:
        self._metrics[connector_id] = ConnectorMetrics(
            connector_id=connector_id,
            started_at=datetime.now(timezone.utc),
            _start_mono=time.monotonic(),
        )

    def record_fetch(self, connector_id: str, count: int) -> None:
        self._metrics[connector_id].records_fetched += count

    def record_write(self, connector_id: str, count: int) -> None:
        self._metrics[connector_id].records_written += count

    def record_duplicate(self, connector_id: str, count: int = 1) -> None:
        self._metrics[connector_id].duplicates_skipped += count

    def record_error(self, connector_id: str) -> None:
        self._metrics[connector_id].errors += 1

    def finish(self, connector_id: str) -> None:
        m = self._metrics[connector_id]
        m.finished_at = datetime.now(timezone.utc)
        m.duration_ms = (time.monotonic() - m._start_mono) * 1000

    def get(self, connector_id: str) -> ConnectorMetrics | None:
        return self._metrics.get(connector_id)

    def summary(self) -> RunMetrics:
        return RunMetrics(
            records_fetched=sum(m.records_fetched for m in self._metrics.values()),
            records_written=sum(m.records_written for m in self._metrics.values()),
            duplicates_skipped=sum(m.duplicates_skipped for m in self._metrics.values()),
            errors=sum(m.errors for m in self._metrics.values()),
            duration_ms=sum(m.duration_ms for m in self._metrics.values()),
        )
