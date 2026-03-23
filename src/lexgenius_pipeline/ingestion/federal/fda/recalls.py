from __future__ import annotations

from datetime import datetime, timezone

import structlog

from lexgenius_pipeline.common.errors import ConnectorError, RateLimitError
from lexgenius_pipeline.common.http_client import create_http_client
from lexgenius_pipeline.common.models import IngestionQuery, NormalizedRecord, Watermark
from lexgenius_pipeline.common.rate_limiter import AsyncRateLimiter
from lexgenius_pipeline.common.types import HealthStatus, RecordType, SourceTier
from lexgenius_pipeline.ingestion.base import BaseConnector
from lexgenius_pipeline.ingestion.normalize import generate_fingerprint
from lexgenius_pipeline.settings import Settings, get_settings

logger = structlog.get_logger(__name__)

_BASE_URL = "https://api.fda.gov/drug/enforcement.json"


def _parse_fda_date(date_str: str) -> datetime:
    """Parse YYYYMMDD or YYYY-MM-DD date string to UTC datetime."""
    date_str = date_str.replace("-", "")
    return datetime.strptime(date_str, "%Y%m%d").replace(tzinfo=timezone.utc)


class RecallsConnector(BaseConnector):
    """FDA drug recall / enforcement actions connector."""

    connector_id = "federal.fda.recalls"
    source_tier = SourceTier.FEDERAL
    source_label = "FDA Recalls"
    supports_incremental = True

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._client = create_http_client()
        self._limiter = AsyncRateLimiter(rate=4.0)

    async def fetch_latest(
        self,
        query: IngestionQuery,
        watermark: Watermark | None = None,
    ) -> list[NormalizedRecord]:
        terms = query.query_terms or []
        if not terms:
            logger.warning("recalls.no_query_terms")
            return []

        search = " AND ".join(
            f'product_description:"{t}"' for t in terms
        )
        params: dict[str, str | int] = {
            "search": search,
            "limit": 100,
            "sort": "report_date:desc",
        }
        if self._settings.fda_api_key:
            params["api_key"] = self._settings.fda_api_key

        await self._limiter.acquire()
        try:
            resp = await self._client.get(_BASE_URL, params=params)
        except Exception as exc:
            raise ConnectorError(str(exc), self.connector_id) from exc

        if resp.status_code == 404:
            return []
        if resp.status_code == 429:
            raise RateLimitError("Rate limit exceeded", self.connector_id)
        if resp.status_code >= 500:
            raise ConnectorError(
                f"Server error {resp.status_code}", self.connector_id
            )
        resp.raise_for_status()

        data = resp.json()
        results = data.get("results", [])
        records: list[NormalizedRecord] = []

        for item in results:
            recall_number = item.get("recall_number", "")
            report_date_raw = item.get("report_date", "")
            if not report_date_raw:
                continue

            try:
                published_at = _parse_fda_date(report_date_raw)
            except ValueError:
                logger.warning("recalls.bad_date", date=report_date_raw)
                continue

            if watermark and watermark.last_record_date:
                if published_at <= watermark.last_record_date:
                    continue

            product_description = item.get("product_description", "")
            reason = item.get("reason_for_recall", "")
            classification = item.get("classification", "")

            title = f"Recall {recall_number}: {product_description[:100]}"
            source_url = (
                f"https://api.fda.gov/drug/enforcement.json"
                f"?search=recall_number:{recall_number}"
            )

            records.append(
                NormalizedRecord(
                    title=title,
                    summary=reason[:500] if reason else f"FDA recall {recall_number}",
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
                        "classification": classification,
                        "reason_for_recall": reason,
                        "product_description": product_description,
                    },
                    raw_payload=item,
                )
            )

        logger.info("recalls.fetched", count=len(records))
        return records

    async def health_check(self) -> HealthStatus:
        params: dict[str, str | int] = {
            "search": "status:Ongoing",
            "limit": 1,
        }
        if self._settings.fda_api_key:
            params["api_key"] = self._settings.fda_api_key
        try:
            resp = await self._client.get(_BASE_URL, params=params)
            if resp.status_code < 500:
                return HealthStatus.HEALTHY
            return HealthStatus.DEGRADED
        except Exception:
            return HealthStatus.FAILED
