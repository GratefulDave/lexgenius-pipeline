from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from .types import RecordType


class NormalizedRecord(BaseModel):
    title: str
    summary: str
    record_type: RecordType
    source_connector_id: str
    source_label: str
    source_url: str
    citation_url: str | None = None
    published_at: datetime
    confidence: float = 1.0
    fingerprint: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    raw_payload: dict[str, Any] = Field(default_factory=dict)


class Watermark(BaseModel):
    scope_key: str
    connector_id: str
    last_fetched_at: datetime
    last_record_date: datetime | None = None


class IngestionQuery(BaseModel):
    connector_ids: list[str] | None = None
    query_terms: list[str] | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None
    max_records: int = 1000


class RunMetrics(BaseModel):
    records_fetched: int = 0
    records_written: int = 0
    duplicates_skipped: int = 0
    errors: int = 0
    duration_ms: float = 0.0
    peak_memory_mb: float | None = None
