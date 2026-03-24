"""FDA Device 510(k) / PMA pre-market data connector.

Fetches device clearance and approval data from the OpenFDA API.
Critical for device mass torts — approval history and post-approval
studies signal safety concerns.
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

_510K_URL = "https://api.fda.gov/device/510k.json"
_PMA_URL = "https://api.fda.gov/device/pma.json"

_NO_API_KEY_LIMIT = 5  # requests/day without API key


def _parse_fda_date(value: str | None) -> datetime:
    if not value:
        return datetime.now(tz=timezone.utc)
    for fmt in ("%Y%m%d", "%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(value.strip()[:10], fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return datetime.now(tz=timezone.utc)


class FDA510KConnector(BaseConnector):
    """FDA 510(k) device clearance data via OpenFDA API.

    Fetches device premarket notification (510(k)) records and
    premarket approval (PMA) records from the OpenFDA device API.
    Supports filtering by device name or product code.
    """

    connector_id = "federal.fda.device_510k"
    source_tier = SourceTier.FEDERAL
    source_label = "FDA Device 510(k) / PMA"
    supports_incremental = True

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._rate_limiter = AsyncRateLimiter(rate=1.0, burst=1)  # OpenFDA is strict

    async def fetch_latest(
        self,
        query: IngestionQuery,
        watermark: Watermark | None = None,
    ) -> list[NormalizedRecord]:
        terms = query.query_terms or []
        if not terms:
            logger.warning("fda_device_510k.no_query_terms")
            return []

        records: list[NormalizedRecord] = []
        api_key = self._settings.fda_api_key

        async with create_http_client(timeout=30.0) as client:
            for term in terms:
                # Query 510(k) endpoint
                await self._rate_limiter.acquire()
                params: dict[str, str] = {
                    "search": f"device_name:{term}",
                    "limit": str(min(query.max_records, 50)),
                }
                if api_key:
                    params["api_key"] = api_key

                try:
                    resp = await client.get(_510K_URL, params=params)
                    if resp.status_code == 404:
                        continue
                    resp.raise_for_status()
                except Exception as exc:
                    logger.warning("federal_fda_device_510k.fetch_error", term=term, exc_info=True)
                    continue

                data = resp.json()
                results = data.get("results", [])

                for result in results:
                    if not isinstance(result, dict):
                        continue

                    device_name = result.get("device_name", "")
                    k_number = result.get("k_number", "")
                    decision_date = result.get("decision_date", "")
                    product_code = result.get("product_code", "")
                    applicant = result.get("applicant", "")
                    contact = result.get("contact", "")
                    review_panel = result.get("review_panel", "")

                    published_at = _parse_fda_date(decision_date)

                    if watermark and watermark.last_record_date:
                        if published_at <= watermark.last_record_date:
                            continue

                    title = f"FDA 510(k): {device_name or k_number}"
                    source_url = (
                        f"https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/"
                        f"cfpmn/pmn.cfm?ID={k_number}"
                        if k_number
                        else "https://www.fda.gov/medical-devices"
                    )

                    summary_parts = []
                    if applicant:
                        summary_parts.append(f"Applicant: {applicant}")
                    if product_code:
                        summary_parts.append(f"Product code: {product_code}")
                    if review_panel:
                        summary_parts.append(f"Review panel: {review_panel}")
                    summary = "; ".join(summary_parts) or title

                    records.append(
                        NormalizedRecord(
                            title=title,
                            summary=summary[:500],
                            record_type=RecordType.FILING,
                            source_connector_id=self.connector_id,
                            source_label=self.source_label,
                            source_url=source_url,
                            published_at=published_at,
                            fingerprint=generate_fingerprint(
                                self.connector_id, source_url, title, published_at
                            ),
                            metadata={
                                "k_number": k_number,
                                "device_name": device_name,
                                "applicant": applicant,
                                "product_code": product_code,
                                "decision_date": decision_date,
                                "review_panel": review_panel,
                                "data_source": "510k",
                            },
                            raw_payload=result,
                        )
                    )

                if len(records) >= query.max_records:
                    break

        logger.info("fda_device_510k.fetched", count=len(records))
        return records

    async def health_check(self) -> HealthStatus:
        async with create_http_client(timeout=30.0) as client:
            try:
                params: dict[str, str] = {"limit": "1"}
                api_key = self._settings.fda_api_key
                if api_key:
                    params["api_key"] = api_key
                resp = await client.get(_510K_URL, params=params)
                if resp.status_code < 500:
                    return HealthStatus.HEALTHY
                return HealthStatus.DEGRADED
            except Exception:
                return HealthStatus.FAILED
