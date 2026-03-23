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

_BASE_URL = "https://dailymed.nlm.nih.gov/dailymed/services/v2/spls.json"


def _parse_dailymed_date(date_str: str) -> datetime:
    """Parse ISO date string (YYYY-MM-DD or YYYYMMDD) to UTC datetime."""
    date_str = date_str.replace("-", "")
    return datetime.strptime(date_str, "%Y%m%d").replace(tzinfo=timezone.utc)


class DailyMedConnector(BaseConnector):
    """DailyMed drug label (SPL) connector."""

    connector_id = "federal.fda.dailymed"
    source_tier = SourceTier.FEDERAL
    source_label = "DailyMed"
    supports_incremental = True

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._client = create_http_client()
        self._limiter = AsyncRateLimiter(rate=2.0)

    async def fetch_latest(
        self,
        query: IngestionQuery,
        watermark: Watermark | None = None,
    ) -> list[NormalizedRecord]:
        terms = query.query_terms or []
        if not terms:
            logger.warning("dailymed.no_query_terms")
            return []

        records: list[NormalizedRecord] = []

        for term in terms:
            params: dict[str, str | int] = {
                "query": term,
                "pagesize": 10,
            }
            await self._limiter.acquire()
            try:
                resp = await self._client.get(_BASE_URL, params=params)
            except Exception as exc:
                raise ConnectorError(str(exc), self.connector_id) from exc

            if resp.status_code == 404:
                continue
            if resp.status_code == 429:
                raise RateLimitError("Rate limit exceeded", self.connector_id)
            if resp.status_code >= 500:
                raise ConnectorError(
                    f"Server error {resp.status_code}", self.connector_id
                )
            resp.raise_for_status()

            data = resp.json()
            items = data.get("data", [])

            for item in items:
                setid = item.get("setid", "")
                title = item.get("title", "")
                published_date_raw = item.get("published_date", "")

                if not setid or not published_date_raw:
                    continue

                try:
                    published_at = _parse_dailymed_date(published_date_raw)
                except ValueError:
                    logger.warning("dailymed.bad_date", date=published_date_raw)
                    continue

                if watermark and watermark.last_record_date:
                    if published_at <= watermark.last_record_date:
                        continue

                source_url = (
                    f"https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid={setid}"
                )

                records.append(
                    NormalizedRecord(
                        title=title or f"Drug Label {setid}",
                        summary=f"Drug label (SPL) for {title or setid}",
                        record_type=RecordType.REGULATION,
                        source_connector_id=self.connector_id,
                        source_label=self.source_label,
                        source_url=source_url,
                        published_at=published_at,
                        fingerprint=generate_fingerprint(
                            self.connector_id,
                            source_url,
                            title or f"Drug Label {setid}",
                            published_at,
                        ),
                        metadata={
                            "setid": setid,
                            "query_term": term,
                        },
                        raw_payload=item,
                    )
                )

        logger.info("dailymed.fetched", count=len(records))
        return records

    async def health_check(self) -> HealthStatus:
        try:
            resp = await self._client.get(_BASE_URL, params={"query": "aspirin", "pagesize": 1})
            if resp.status_code < 500:
                return HealthStatus.HEALTHY
            return HealthStatus.DEGRADED
        except Exception:
            return HealthStatus.FAILED
