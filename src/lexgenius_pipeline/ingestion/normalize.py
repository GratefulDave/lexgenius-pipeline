from __future__ import annotations

import hashlib
from datetime import datetime

from lexgenius_pipeline.common.models import NormalizedRecord
from lexgenius_pipeline.db.models.ingestion import RawRecord


def generate_fingerprint(
    source_connector_id: str,
    source_url: str,
    title: str,
    published_at: datetime,
) -> str:
    """SHA-256 fingerprint for deduplication."""
    raw = f"{source_connector_id}|{source_url}|{title}|{published_at.isoformat()}"
    return hashlib.sha256(raw.encode()).hexdigest()


def normalize_to_orm(record: NormalizedRecord) -> RawRecord:
    """Convert a Pydantic NormalizedRecord to a SQLAlchemy RawRecord."""
    return RawRecord(
        connector_id=record.source_connector_id,
        record_type=record.record_type.value,
        source_label=record.source_label,
        source_url=record.source_url,
        citation_url=record.citation_url,
        fingerprint=record.fingerprint,
        title=record.title,
        summary=record.summary,
        published_at=record.published_at,
        confidence=record.confidence,
        metadata_=record.metadata,
        raw_payload=record.raw_payload,
    )
