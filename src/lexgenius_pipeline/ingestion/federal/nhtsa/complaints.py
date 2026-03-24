"""NHTSA vehicle complaints connector.

Fetches consumer safety complaints from the NHTSA complaints API (ORE system).
Complaint spikes often precede recalls and are an early signal for litigation.
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

_BASE_URL = "https://api.nhtsa.gov/complaints/complaintsByVehicle"


def _parse_date(value: str | None) -> datetime:
    if not value:
        return datetime.now(tz=timezone.utc)
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(value.strip()[:19], fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return datetime.now(tz=timezone.utc)


class NHTSAComplaintsConnector(BaseConnector):
    """NHTSA consumer safety complaints via REST API.

    Fetches Vehicle Owner Questionnaire (VOQ/ORE) complaints from NHTSA,
    filtered by make/model. Complaint volume spikes are early litigation signals.
    """

    connector_id = "federal.nhtsa.complaints"
    source_tier = SourceTier.FEDERAL
    source_label = "NHTSA Safety Complaints"
    supports_incremental = True

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._rate_limiter = AsyncRateLimiter(rate=5.0, burst=5)

    async def fetch_latest(
        self,
        query: IngestionQuery,
        watermark: Watermark | None = None,
    ) -> list[NormalizedRecord]:
        terms = query.query_terms or []
        if not terms:
            logger.warning("nhtsa_complaints.no_query_terms")
            return []

        records: list[NormalizedRecord] = []

        async with create_http_client() as client:
            for term in terms:
                await self._rate_limiter.acquire()
                try:
                    resp = await client.get(
                        _BASE_URL,
                        params={"make": term, "modelYear": "", "model": "", "format": "json"},
                    )
                    resp.raise_for_status()
                except Exception as exc:
                    logger.warning("federal_nhtsa_complaints.fetch_error", term=term, exc_info=True)
                    continue

                data = resp.json()
                results = data.get("Results", []) if isinstance(data, dict) else []

                for complaint in results:
                    if not isinstance(complaint, dict):
                        continue

                    component = complaint.get("components", "")
                    summary_text = complaint.get("summary", "")
                    complaint_date = complaint.get("dateOfIncident", "") or complaint.get(
                        "dateComplaintFiled", ""
                    )

                    if not component and not summary_text:
                        continue

                    published_at = _parse_date(complaint_date)

                    if watermark and watermark.last_record_date:
                        if published_at <= watermark.last_record_date:
                            continue

                    title = f"NHTSA Complaint: {component}" if component else "NHTSA Safety Complaint"
                    complaint_id = complaint.get("cmplID", "")
                    manufacturer = complaint.get("manufacturer", "")
                    product_make = complaint.get("make", "")
                    product_model = complaint.get("model", "")
                    model_year = complaint.get("modelYear", "")
                    crashes = complaint.get("crashes", "0")
                    fires = complaint.get("fires", "0")
                    injuries = complaint.get("injuries", "0")
                    deaths = complaint.get("deaths", "0")

                    source_url = (
                        f"https://www.nhtsa.gov/complaints/#/detail/{complaint_id}"
                        if complaint_id
                        else "https://www.nhtsa.gov/complaints"
                    )

                    summary_parts = [summary_text[:400]] if summary_text else []
                    if crashes and int(crashes) > 0:
                        summary_parts.append(f"Crashes: {crashes}")
                    if fires and int(fires) > 0:
                        summary_parts.append(f"Fires: {fires}")
                    if injuries and int(injuries) > 0:
                        summary_parts.append(f"Injuries: {injuries}")
                    if deaths and int(deaths) > 0:
                        summary_parts.append(f"Deaths: {deaths}")
                    summary = "; ".join(summary_parts) or title

                    records.append(
                        NormalizedRecord(
                            title=title,
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
                                "complaint_id": complaint_id,
                                "manufacturer": manufacturer,
                                "make": product_make,
                                "model": product_model,
                                "model_year": model_year,
                                "components": component,
                                "crashes": crashes,
                                "fires": fires,
                                "injuries": injuries,
                                "deaths": deaths,
                            },
                            raw_payload=complaint,
                        )
                    )

                    if len(records) >= query.max_records:
                        break

        logger.info("nhtsa_complaints.fetched", count=len(records))
        return records

    async def health_check(self) -> HealthStatus:
        async with create_http_client() as client:
            try:
                resp = await client.get(
                    "https://api.nhtsa.gov/complaints/complaintsByVehicle",
                    params={"make": "Toyota", "format": "json"},
                )
                resp.raise_for_status()
                return HealthStatus.HEALTHY
            except Exception:
                return HealthStatus.FAILED
