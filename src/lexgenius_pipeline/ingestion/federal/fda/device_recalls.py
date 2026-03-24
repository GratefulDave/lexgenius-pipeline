"""FDA Device Recalls connector.

Fetches medical device recall data from the OpenFDA device enforcement API.
"""
from __future__ import annotations

from datetime import datetime, timezone

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

_ENFORCEMENT_URL = "https://api.fda.gov/device/enforcement.json"


def _parse_fda_date(value: str | None) -> datetime:
    if not value:
        return datetime.now(tz=timezone.utc)
    for fmt in ("%Y%m%d", "%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(value.strip()[:10], fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return datetime.now(tz=timezone.utc)


class FDARecallsDeviceConnector(BaseConnector):
    """FDA Medical Device Recalls via OpenFDA API.

    Fetches device enforcement/recall records from the OpenFDA
    device enforcement endpoint. Supports filtering by product or
    recall reason.
    """

    connector_id = "federal.fda.device_recalls"
    source_tier = SourceTier.FEDERAL
    source_label = "FDA Device Recalls"
    supports_incremental = True

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._rate_limiter = AsyncRateLimiter(rate=1.0, burst=1)

    async def fetch_latest(
        self,
        query: IngestionQuery,
        watermark: Watermark | None = None,
    ) -> list[NormalizedRecord]:
        terms = query.query_terms or []
        if not terms:
            logger.warning("fda_device_recalls.no_query_terms")
            return []

        records: list[NormalizedRecord] = []
        api_key = self._settings.fda_api_key

        async with create_http_client(timeout=30.0) as client:
            for term in terms:
                await self._rate_limiter.acquire()
                params: dict[str, str] = {
                    "search": f"product_description:{term}",
                    "limit": str(min(query.max_records, 50)),
                    "sort": "recall_initiation_date:desc",
                }
                if api_key:
                    params["api_key"] = api_key

                try:
                    resp = await client.get(_ENFORCEMENT_URL, params=params)
                    if resp.status_code == 404:
                        continue
                    resp.raise_for_status()
                except Exception as exc:
                    logger.warning("federal_fda_device_recalls.fetch_error", term=term, exc_info=True)
                    continue

                data = resp.json()
                results = data.get("results", [])

                for result in results:
                    if not isinstance(result, dict):
                        continue

                    product = result.get("product_description", "")
                    recall_reason = result.get("reason_for_recall", "")
                    recall_date = result.get("recall_initiation_date", "")
                    recall_number = result.get("recall_number", "")
                    classification = result.get("classification", "")
                    firm = result.get("recalling_firm", "")
                    country = result.get("country", "")
                    distribution = result.get("distribution_pattern", "")
                    product_code = result.get("product_code", "")
                    product_type = result.get("product_type", "")
                    event_id = result.get("event_id", "")

                    published_at = _parse_fda_date(recall_date)

                    if watermark and watermark.last_record_date:
                        if published_at <= watermark.last_record_date:
                            continue

                    title = f"FDA Device Recall: {product or recall_number}"
                    source_url = (
                        f"https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/"
                        f"cfRes/res.cfm?id={event_id}"
                        if event_id
                        else "https://www.fda.gov/medical-devices/medical-device-recalls"
                    )

                    summary_parts = []
                    if recall_reason:
                        summary_parts.append(f"Reason: {recall_reason[:300]}")
                    if classification:
                        summary_parts.append(f"Classification: {classification}")
                    if firm:
                        summary_parts.append(f"Recalling firm: {firm}")
                    if distribution:
                        summary_parts.append(f"Distribution: {distribution}")
                    summary = "; ".join(summary_parts) or title

                    records.append(
                        NormalizedRecord(
                            title=title,
                            summary=summary[:500],
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
                                "event_id": event_id,
                                "product_description": product,
                                "classification": classification,
                                "recalling_firm": firm,
                                "country": country,
                                "distribution_pattern": distribution,
                                "product_code": product_code,
                                "product_type": product_type,
                            },
                            raw_payload=result,
                        )
                    )

                if len(records) >= query.max_records:
                    break

        logger.info("fda_device_recalls.fetched", count=len(records))
        return records

    async def health_check(self) -> HealthStatus:
        async with create_http_client(timeout=30.0) as client:
            try:
                params: dict[str, str] = {"limit": "1"}
                api_key = self._settings.fda_api_key
                if api_key:
                    params["api_key"] = api_key
                resp = await client.get(_ENFORCEMENT_URL, params=params)
                if resp.status_code < 500:
                    return HealthStatus.HEALTHY
                return HealthStatus.DEGRADED
            except Exception:
                return HealthStatus.FAILED
