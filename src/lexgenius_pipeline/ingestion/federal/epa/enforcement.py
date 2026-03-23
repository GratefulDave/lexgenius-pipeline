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

_BASE_URL = "https://enviro.epa.gov/enviro/efservice/CASE_ENFORCEMENTS/ROWS/0:50/JSON"
_HEALTH_URL = "https://enviro.epa.gov/enviro/efservice/CASE_ENFORCEMENTS/ROWS/0:1/JSON"


def _parse_epa_date(date_str: str) -> datetime:
    """Parse EPA date strings in various formats to UTC datetime."""
    if not date_str:
        raise ValueError("Empty date string")
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y%m%d"):
        try:
            return datetime.strptime(date_str[:10], fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    raise ValueError(f"Unrecognised date format: {date_str!r}")


class EPAEnforcementConnector(BaseConnector):
    """EPA enforcement actions connector."""

    connector_id = "federal.epa.enforcement"
    source_tier = SourceTier.FEDERAL
    source_label = "EPA Enforcement"
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
        await self._limiter.acquire()
        try:
            resp = await self._client.get(_BASE_URL)
        except Exception as exc:
            raise ConnectorError(str(exc), self.connector_id) from exc

        if resp.status_code == 429:
            raise RateLimitError("Rate limit exceeded", self.connector_id)
        if resp.status_code >= 500:
            raise ConnectorError(f"Server error {resp.status_code}", self.connector_id)
        resp.raise_for_status()

        data = resp.json()
        items = data if isinstance(data, list) else data.get("results", [])
        records: list[NormalizedRecord] = []

        for item in items:
            case_number = item.get("CASE_NUMBER", "")
            case_name = item.get("CASE_NAME", "") or f"Case {case_number}"
            date_raw = item.get("SETTLEMENT_ENTERED_DATE", "")
            penalty = item.get("FED_PENALTY_ASSESSED_AMT", "")
            enfor_type = item.get("ENFOR_TYPE", "")

            if not date_raw:
                continue
            try:
                published_at = _parse_epa_date(date_raw)
            except ValueError:
                logger.warning("epa.enforcement.bad_date", date=date_raw)
                continue

            if watermark and watermark.last_record_date:
                if published_at <= watermark.last_record_date:
                    continue

            source_url = (
                f"https://echo.epa.gov/enforcement-case-search/results"
                f"?p_case_number={case_number}"
            )
            title = f"EPA Enforcement: {case_name}"
            summary = f"Case {case_number} — {enfor_type} — Penalty: ${penalty}"

            records.append(
                NormalizedRecord(
                    title=title,
                    summary=summary,
                    record_type=RecordType.ENFORCEMENT,
                    source_connector_id=self.connector_id,
                    source_label=self.source_label,
                    source_url=source_url,
                    published_at=published_at,
                    fingerprint=generate_fingerprint(
                        self.connector_id, source_url, title, published_at
                    ),
                    metadata={
                        "case_number": case_number,
                        "enfor_type": enfor_type,
                        "penalty_assessed": penalty,
                    },
                    raw_payload=item,
                )
            )

        logger.info("epa.enforcement.fetched", count=len(records))
        return records

    async def health_check(self) -> HealthStatus:
        try:
            resp = await self._client.get(_HEALTH_URL)
            if resp.status_code < 500:
                return HealthStatus.HEALTHY
            return HealthStatus.DEGRADED
        except Exception:
            return HealthStatus.FAILED
