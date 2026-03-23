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

_BASE_URL = "https://api.congress.gov/v3/bill"


def _parse_congress_date(date_str: str) -> datetime:
    if not date_str:
        raise ValueError("Empty date string")
    for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(date_str[:10], fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    raise ValueError(f"Unrecognised Congress date: {date_str!r}")


class CongressConnector(BaseConnector):
    """Congress.gov bills and legislation connector."""

    connector_id = "federal.congress.legislation"
    source_tier = SourceTier.FEDERAL
    source_label = "Congress.gov"
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
            logger.warning("congress.no_query_terms")
            return []

        api_key = getattr(self._settings, "congress_api_key", "")
        if not api_key:
            logger.warning("congress.no_api_key")
            return []

        records: list[NormalizedRecord] = []

        for term in terms:
            params: dict[str, str | int] = {
                "q": term,
                "limit": 5,
                "api_key": api_key,
            }
            await self._limiter.acquire()
            try:
                resp = await self._client.get(_BASE_URL, params=params)
            except Exception as exc:
                raise ConnectorError(str(exc), self.connector_id) from exc

            if resp.status_code == 429:
                raise RateLimitError("Rate limit exceeded", self.connector_id)
            if resp.status_code >= 500:
                raise ConnectorError(f"Server error {resp.status_code}", self.connector_id)
            resp.raise_for_status()

            data = resp.json()
            bills = data.get("bills", [])

            for bill in bills:
                title = bill.get("title", "")
                bill_number = bill.get("number", "")
                bill_type = bill.get("type", "")
                latest_action = bill.get("latestAction", {})
                action_date = latest_action.get("actionDate", "")
                action_text = latest_action.get("text", "")
                bill_url = bill.get("url", "")

                if not action_date:
                    continue
                try:
                    published_at = _parse_congress_date(action_date)
                except ValueError:
                    logger.warning("congress.bad_date", date=action_date)
                    continue

                if watermark and watermark.last_record_date:
                    if published_at <= watermark.last_record_date:
                        continue

                source_url = bill_url or f"https://www.congress.gov/bill/{bill_type}/{bill_number}"
                full_title = title or f"{bill_type} {bill_number}"
                summary = action_text or f"Bill {bill_type}{bill_number}"

                records.append(
                    NormalizedRecord(
                        title=full_title,
                        summary=summary,
                        record_type=RecordType.LEGISLATION,
                        source_connector_id=self.connector_id,
                        source_label=self.source_label,
                        source_url=source_url,
                        published_at=published_at,
                        fingerprint=generate_fingerprint(
                            self.connector_id, source_url, full_title, published_at
                        ),
                        metadata={
                            "bill_number": bill_number,
                            "bill_type": bill_type,
                            "latest_action": action_text,
                            "action_date": action_date,
                            "query_term": term,
                        },
                        raw_payload=bill,
                    )
                )

        logger.info("congress.legislation.fetched", count=len(records))
        return records

    async def health_check(self) -> HealthStatus:
        api_key = getattr(self._settings, "congress_api_key", "")
        if not api_key:
            return HealthStatus.DEGRADED
        try:
            resp = await self._client.get(
                _BASE_URL, params={"limit": 1, "api_key": api_key}
            )
            if resp.status_code < 500:
                return HealthStatus.HEALTHY
            return HealthStatus.DEGRADED
        except Exception:
            return HealthStatus.FAILED
