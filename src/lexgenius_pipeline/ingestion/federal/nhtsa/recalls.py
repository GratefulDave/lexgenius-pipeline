"""NHTSA vehicle recalls connector.

Fetches vehicle and equipment recall data from the NHTSA recalls API.
Essential for automotive product liability and mass tort intelligence.
"""
from __future__ import annotations

from datetime import datetime, timezone

import structlog

from lexgenius_pipeline.common.date_utils import parse_date
from lexgenius_pipeline.common.errors import ConnectorError
from lexgenius_pipeline.common.http_client import create_http_client
from lexgenius_pipeline.common.models import IngestionQuery, NormalizedRecord, Watermark
from lexgenius_pipeline.common.rate_limiter import AsyncRateLimiter
from lexgenius_pipeline.common.types import HealthStatus, RecordType, SourceTier
from lexgenius_pipeline.ingestion.base import BaseConnector
from lexgenius_pipeline.ingestion.normalize import generate_fingerprint
from lexgenius_pipeline.settings import Settings, get_settings

logger = structlog.get_logger(__name__)

_BASE_URL = "https://api.nhtsa.gov/recalls/recallsByVehicle"



class NHTSARecallsConnector(BaseConnector):
    """NHTSA vehicle and equipment recalls via REST API.

    Fetches recall records from the NHTSA API, filtering by make/model
    or component. Supports incremental fetching via watermark dates.
    """

    connector_id = "federal.nhtsa.recalls"
    source_tier = SourceTier.FEDERAL
    source_label = "NHTSA Vehicle Recalls"
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
            logger.warning("nhtsa_recalls.no_query_terms")
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
                    logger.warning("federal_nhtsa_recalls.fetch_error", term=term, exc_info=True)
                    continue

                data = resp.json()
                results = data.get("Results", []) if isinstance(data, dict) else []

                for recall in results:
                    if not isinstance(recall, dict):
                        continue

                    title = recall.get("Component", "") or recall.get("Subject", "")
                    if not title:
                        continue

                    recall_date = recall.get("ReportReceivedDate", "")
                    published_at = parse_date(recall_date)

                    if watermark and watermark.last_record_date:
                        if published_at <= watermark.last_record_date:
                            continue

                    manufacturer = recall.get("Manufacturer", "")
                    defect = recall.get("Defect", "")
                    remedy = recall.get("Remedy", "")
                    consequence = recall.get("Consequence", "")
                    nhtsa_id = recall.get("NHTSACampaignNumber", "")
                    mfr_id = recall.get("MfrCampaignNumber", "")
                    recall_url = recall.get("NHTSALink", "")
                    if not recall_url:
                        recall_url = (
                            f"https://www.nhtsa.gov/recalls"
                            f"?nhtsaId={nhtsa_id}&mfrId={mfr_id}"
                        )

                    summary_parts = []
                    if defect:
                        summary_parts.append(f"Defect: {defect[:300]}")
                    if consequence:
                        summary_parts.append(f"Consequence: {consequence[:200]}")
                    if remedy:
                        summary_parts.append(f"Remedy: {remedy[:200]}")
                    summary = "; ".join(summary_parts) or title

                    records.append(
                        NormalizedRecord(
                            title=f"NHTSA Recall: {title}",
                            summary=summary[:500],
                            record_type=RecordType.RECALL,
                            source_connector_id=self.connector_id,
                            source_label=self.source_label,
                            source_url=recall_url,
                            published_at=published_at,
                            fingerprint=generate_fingerprint(
                                self.connector_id, recall_url, title, published_at
                            ),
                            metadata={
                                "nhtsa_campaign_number": nhtsa_id,
                                "mfr_campaign_number": mfr_id,
                                "manufacturer": manufacturer,
                                "component": recall.get("Component", ""),
                                "affected_units": recall.get("PotentialNumberofUnitsAffected", ""),
                            },
                            raw_payload=recall,
                        )
                    )

                    if len(records) >= query.max_records:
                        break

                if len(records) >= query.max_records:
                    break

        logger.info("nhtsa_recalls.fetched", count=len(records))
        return records

    async def health_check(self) -> HealthStatus:
        async with create_http_client() as client:
            try:
                resp = await client.get(
                    "https://api.nhtsa.gov/recalls/recallsByVehicle",
                    params={"make": "Toyota", "format": "json"},
                )
                resp.raise_for_status()
                return HealthStatus.HEALTHY
            except Exception:
                return HealthStatus.FAILED
