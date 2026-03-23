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

_BASE_URL = "https://api.fda.gov/device/event.json"


def _parse_fda_date(date_str: str) -> datetime:
    """Parse YYYYMMDD or YYYY-MM-DD date string to UTC datetime."""
    date_str = date_str.replace("-", "")
    return datetime.strptime(date_str, "%Y%m%d").replace(tzinfo=timezone.utc)


class MAUDEConnector(BaseConnector):
    """FDA MAUDE medical device adverse event reports connector."""

    connector_id = "federal.fda.maude"
    source_tier = SourceTier.FEDERAL
    source_label = "FDA MAUDE"
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
            logger.warning("maude.no_query_terms")
            return []

        search_parts = []
        for t in terms:
            search_parts.append(
                f'(device.generic_name:"{t}" OR device.brand_name:"{t}")'
            )
        search = " AND ".join(search_parts)

        params: dict[str, str | int] = {
            "search": search,
            "limit": 100,
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
            report_key = item.get("mdr_report_key", "")
            date_received_raw = item.get("date_received", "")
            if not date_received_raw:
                continue

            try:
                published_at = _parse_fda_date(date_received_raw)
            except ValueError:
                logger.warning("maude.bad_date", date=date_received_raw)
                continue

            if watermark and watermark.last_record_date:
                if published_at <= watermark.last_record_date:
                    continue

            devices = item.get("device") or []
            device_names = [
                d.get("generic_name") or d.get("brand_name", "")
                for d in devices
            ]
            event_type = item.get("event_type", "")

            title = f"MAUDE Report {report_key}: {', '.join(filter(None, device_names[:3]))}"
            source_url = (
                f"https://api.fda.gov/device/event.json"
                f"?search=mdr_report_key:{report_key}"
            )

            records.append(
                NormalizedRecord(
                    title=title,
                    summary=f"Device event type: {event_type}",
                    record_type=RecordType.ADVERSE_EVENT,
                    source_connector_id=self.connector_id,
                    source_label=self.source_label,
                    source_url=source_url,
                    published_at=published_at,
                    fingerprint=generate_fingerprint(
                        self.connector_id, source_url, title, published_at
                    ),
                    metadata={
                        "mdr_report_key": report_key,
                        "device_names": device_names,
                        "event_type": event_type,
                        "report_source_code": item.get("report_source_code"),
                    },
                    raw_payload=item,
                )
            )

        logger.info("maude.fetched", count=len(records))
        return records

    async def health_check(self) -> HealthStatus:
        params: dict[str, str | int] = {"search": "event_type:malfunction", "limit": 1}
        if self._settings.fda_api_key:
            params["api_key"] = self._settings.fda_api_key
        try:
            resp = await self._client.get(_BASE_URL, params=params)
            if resp.status_code < 500:
                return HealthStatus.HEALTHY
            return HealthStatus.DEGRADED
        except Exception:
            return HealthStatus.FAILED
