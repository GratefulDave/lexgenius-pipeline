from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import structlog

from lexgenius_pipeline.common.errors import ConnectorError
from lexgenius_pipeline.common.http_client import create_http_client
from lexgenius_pipeline.common.models import IngestionQuery, NormalizedRecord, Watermark
from lexgenius_pipeline.common.rate_limiter import AsyncRateLimiter
from lexgenius_pipeline.common.types import HealthStatus, RecordType, SourceTier
from lexgenius_pipeline.ingestion.base import BaseConnector
from lexgenius_pipeline.ingestion.normalize import generate_fingerprint
from lexgenius_pipeline.settings import Settings, get_settings

logger = structlog.get_logger(__name__)

_RECALLS_URL = "https://www.saferproducts.gov/RestWebServices/Recall"


def _parse_recall_date(value: str | None) -> datetime:
    if not value:
        return datetime.now(tz=timezone.utc)
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(value.strip()[:19], fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return datetime.now(tz=timezone.utc)


class CPSCRecallsConnector(BaseConnector):
    connector_id = "federal.cpsc.recalls"
    source_tier = SourceTier.FEDERAL
    source_label = "CPSC SaferProducts Recalls"
    supports_incremental = True

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._rate_limiter = AsyncRateLimiter(rate=1.0, burst=2)

    async def fetch_latest(
        self,
        query: IngestionQuery,
        watermark: Watermark | None = None,
    ) -> list[NormalizedRecord]:
        terms = query.query_terms or []
        if not terms:
            logger.warning("cpsc_recalls.no_query_terms")
            return []

        records: list[NormalizedRecord] = []

        async with create_http_client() as client:
            for term in terms:
                await self._rate_limiter.acquire()
                try:
                    resp = await client.get(
                        _RECALLS_URL,
                        params={"ProductName": term, "format": "json"},
                    )
                    resp.raise_for_status()
                except Exception as exc:
                    raise ConnectorError(str(exc), self.connector_id) from exc

                recalls: list[dict[str, Any]] = resp.json() if resp.content else []
                for recall in recalls:
                    record = self._parse_recall(recall)
                    if record:
                        records.append(record)

        logger.info("cpsc_recalls.fetched", count=len(records))
        return records

    def _parse_recall(self, recall: dict[str, Any]) -> NormalizedRecord | None:
        recall_number: str = str(recall.get("RecallNumber", "")).strip()
        title: str = (recall.get("Title") or recall.get("Name", "")).strip()
        if not title:
            title = f"CPSC Recall {recall_number}" if recall_number else "CPSC Recall"

        description: str = (recall.get("Description") or "").strip()
        recall_date: str = recall.get("RecallDate", "")
        source_url: str = (recall.get("URL") or "").strip()
        if not source_url:
            source_url = (
                f"https://www.cpsc.gov/Recalls/{recall_number}" if recall_number else ""
            )

        hazards: list[str] = [
            h.get("Name", "") for h in (recall.get("Hazards") or []) if h.get("Name")
        ]
        injuries: list[str] = [
            i.get("Name", "") for i in (recall.get("Injuries") or []) if i.get("Name")
        ]
        manufacturers: list[str] = [
            m.get("Name", "") for m in (recall.get("Manufacturers") or []) if m.get("Name")
        ]

        summary_parts: list[str] = []
        if description:
            summary_parts.append(description[:300])
        if hazards:
            summary_parts.append("Hazards: " + ", ".join(hazards))
        if injuries:
            summary_parts.append("Injuries: " + ", ".join(injuries))
        summary = "; ".join(summary_parts) or title

        published_at = _parse_recall_date(recall_date)

        if not source_url:
            source_url = f"https://www.saferproducts.gov/recall/{recall_number}"

        return NormalizedRecord(
            title=title,
            summary=summary,
            record_type=RecordType.RECALL,
            source_connector_id=self.connector_id,
            source_label=self.source_label,
            source_url=source_url,
            published_at=published_at,
            fingerprint=generate_fingerprint(
                self.connector_id, source_url, title, published_at
            ),
            metadata={
                "recall_number": recall_number,
                "hazards": hazards,
                "injuries": injuries,
                "manufacturers": manufacturers,
            },
            raw_payload=recall,
        )

    async def health_check(self) -> HealthStatus:
        async with create_http_client() as client:
            try:
                resp = await client.get(
                    _RECALLS_URL,
                    params={"ProductName": "toy", "format": "json"},
                )
                resp.raise_for_status()
                return HealthStatus.HEALTHY
            except Exception:
                return HealthStatus.FAILED
