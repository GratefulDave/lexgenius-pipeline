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

_BASE_URL = "https://api.fda.gov/drug/event.json"


def _parse_fda_date(date_str: str) -> datetime:
    """Parse YYYYMMDD or YYYY-MM-DD date string to UTC datetime."""
    date_str = date_str.replace("-", "")
    return datetime.strptime(date_str, "%Y%m%d").replace(tzinfo=timezone.utc)


class FAERSConnector(BaseConnector):
    """FDA FAERS adverse event reports connector."""

    connector_id = "federal.fda.faers"
    source_tier = SourceTier.FEDERAL
    source_label = "FDA FAERS"
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
            logger.warning("faers.no_query_terms")
            return []

        search = " AND ".join(
            f'patient.drug.medicinalproduct:"{t}"' for t in terms
        )
        params: dict[str, str | int] = {
            "search": search,
            "limit": 100,
            "skip": 0,
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
            report_id = item.get("safetyreportid", "")
            receive_date_raw = item.get("receivedate", "")
            if not receive_date_raw:
                continue

            try:
                published_at = _parse_fda_date(receive_date_raw)
            except ValueError:
                logger.warning("faers.bad_date", date=receive_date_raw)
                continue

            if watermark and watermark.last_record_date:
                if published_at <= watermark.last_record_date:
                    continue

            patient = item.get("patient", {})
            drugs = [
                d.get("medicinalproduct", "")
                for d in (patient.get("drug") or [])
            ]
            reactions = [
                r.get("reactionmeddrapt", "")
                for r in (patient.get("reaction") or [])
            ]

            title = f"FAERS Report {report_id}: {', '.join(drugs[:3])}"
            source_url = f"https://api.fda.gov/drug/event.json?search=safetyreportid:{report_id}"

            records.append(
                NormalizedRecord(
                    title=title,
                    summary=f"Adverse event reactions: {', '.join(reactions[:5])}",
                    record_type=RecordType.ADVERSE_EVENT,
                    source_connector_id=self.connector_id,
                    source_label=self.source_label,
                    source_url=source_url,
                    published_at=published_at,
                    fingerprint=generate_fingerprint(
                        self.connector_id, source_url, title, published_at
                    ),
                    metadata={
                        "safetyreportid": report_id,
                        "drugs": drugs,
                        "reactions": reactions,
                        "serious": item.get("serious"),
                        "seriousnessdeath": item.get("seriousnessdeath"),
                        "seriousnesshospitalization": item.get(
                            "seriousnesshospitalization"
                        ),
                    },
                    raw_payload=item,
                )
            )

        logger.info("faers.fetched", count=len(records))
        return records

    async def health_check(self) -> HealthStatus:
        params: dict[str, str | int] = {"search": "serious:1", "limit": 1}
        if self._settings.fda_api_key:
            params["api_key"] = self._settings.fda_api_key
        try:
            resp = await self._client.get(_BASE_URL, params=params)
            if resp.status_code < 500:
                return HealthStatus.HEALTHY
            return HealthStatus.DEGRADED
        except Exception:
            return HealthStatus.FAILED
