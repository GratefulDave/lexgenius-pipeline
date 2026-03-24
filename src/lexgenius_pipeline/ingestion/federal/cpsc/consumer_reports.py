"""CPSC Consumer Reports connector.

Fetches consumer product safety incident reports from the CPSC
SaferProducts.gov REST API. Complements the CPSC recalls connector
with consumer-submitted incident reports.
"""
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

_BASE_URL = "https://www.saferproducts.gov/RestWebServices/Incident"


def _parse_date(value: str | None) -> datetime:
    if not value:
        return datetime.now(tz=timezone.utc)
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(value.strip()[:19], fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return datetime.now(tz=timezone.utc)


class CPSCConsumerReportsConnector(BaseConnector):
    """CPSC Consumer Product Safety incident reports via REST API.

    Fetches consumer-submitted incident reports from SaferProducts.gov,
    complementing the recall data with real-world injury reports.
    """

    connector_id = "federal.cpsc.consumer_reports"
    source_tier = SourceTier.FEDERAL
    source_label = "CPSC Consumer Incident Reports"
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
            logger.warning("cpsc_consumer_reports.no_query_terms")
            return []

        records: list[NormalizedRecord] = []

        async with create_http_client() as client:
            for term in terms:
                await self._rate_limiter.acquire()
                try:
                    resp = await client.get(
                        _BASE_URL,
                        params={"ProductName": term, "format": "json"},
                    )
                    resp.raise_for_status()
                except Exception as exc:
                    logger.warning("federal_cpsc_consumer_reports.fetch_error", term=term, exc_info=True)
                    continue

                incidents: list[dict[str, Any]] = resp.json() if resp.content else []

                for incident in incidents:
                    if not isinstance(incident, dict):
                        continue

                    title = (incident.get("Title") or incident.get("Name", "")).strip()
                    description = (incident.get("Description") or "").strip()
                    incident_date = incident.get("Date", "")
                    incident_id = incident.get("IncidentId", "")

                    if not title:
                        title = f"CPSC Incident Report {incident_id}"

                    published_at = _parse_date(incident_date)

                    if watermark and watermark.last_record_date:
                        if published_at <= watermark.last_record_date:
                            continue

                    injuries = [
                        i.get("Name", "")
                        for i in (incident.get("Injuries") or [])
                        if i.get("Name")
                    ]
                    manufacturers = [
                        m.get("Name", "")
                        for m in (incident.get("Manufacturers") or [])
                        if m.get("Name")
                    ]
                    categories = [
                        c.get("Name", "")
                        for c in (incident.get("Categories") or [])
                        if c.get("Name")
                    ]

                    summary_parts = [description[:300]] if description else []
                    if injuries:
                        summary_parts.append("Injuries: " + ", ".join(injuries))
                    if categories:
                        summary_parts.append("Categories: " + ", ".join(categories))
                    summary = "; ".join(summary_parts) or title

                    source_url = (
                        f"https://www.saferproducts.gov/incident/{incident_id}"
                        if incident_id
                        else "https://www.saferproducts.gov"
                    )

                    records.append(
                        NormalizedRecord(
                            title=f"CPSC Incident: {title}",
                            summary=summary[:500],
                            record_type=RecordType.ADVERSE_EVENT,
                            source_connector_id=self.connector_id,
                            source_label=self.source_label,
                            source_url=source_url,
                            published_at=published_at,
                            fingerprint=generate_fingerprint(
                                self.connector_id, source_url, title, published_at
                            ),
                            metadata={
                                "incident_id": incident_id,
                                "injuries": injuries,
                                "manufacturers": manufacturers,
                                "categories": categories,
                            },
                            raw_payload=incident,
                        )
                    )

                    if len(records) >= query.max_records:
                        break

        logger.info("cpsc_consumer_reports.fetched", count=len(records))
        return records

    async def health_check(self) -> HealthStatus:
        async with create_http_client() as client:
            try:
                resp = await client.get(
                    _BASE_URL,
                    params={"ProductName": "toy", "format": "json"},
                )
                resp.raise_for_status()
                return HealthStatus.HEALTHY
            except Exception:
                return HealthStatus.FAILED
