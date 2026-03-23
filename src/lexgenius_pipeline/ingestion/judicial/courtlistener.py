from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import quote_plus

import structlog

from lexgenius_pipeline.common.errors import ConnectorError
from lexgenius_pipeline.common.http_client import create_http_client
from lexgenius_pipeline.common.models import IngestionQuery, NormalizedRecord, Watermark
from lexgenius_pipeline.common.types import HealthStatus, RecordType, SourceTier
from lexgenius_pipeline.ingestion.base import BaseConnector
from lexgenius_pipeline.ingestion.normalize import generate_fingerprint
from lexgenius_pipeline.settings import Settings, get_settings

logger = structlog.get_logger(__name__)

_BASE_URL = "https://www.courtlistener.com/api/rest/v4/search/"


def _parse_cl_date(date_str: str | None) -> datetime:
    if not date_str:
        return datetime.now(tz=timezone.utc)
    try:
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc).replace(tzinfo=timezone.utc)
    except Exception:
        return datetime.now(tz=timezone.utc)


class CourtListenerConnector(BaseConnector):
    """CourtListener federal court opinions connector."""

    connector_id = "judicial.courtlistener"
    source_tier = SourceTier.JUDICIAL
    source_label = "CourtListener"
    supports_incremental = True

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._client = create_http_client()

    async def fetch_latest(
        self,
        query: IngestionQuery,
        watermark: Watermark | None = None,
    ) -> list[NormalizedRecord]:
        terms = query.query_terms or []
        if not terms:
            logger.warning("courtlistener.no_query_terms")
            return []

        search_term = " ".join(terms)
        params = {
            "q": search_term,
            "type": "o",
            "order_by": "dateFiled desc",
        }
        headers: dict[str, str] = {}
        if self._settings.courtlistener_api_key:
            headers["Authorization"] = f"Token {self._settings.courtlistener_api_key}"

        try:
            resp = await self._client.get(_BASE_URL, params=params, headers=headers)
        except Exception as exc:
            raise ConnectorError(str(exc), self.connector_id) from exc

        if resp.status_code == 404:
            return []
        if resp.status_code >= 400:
            raise ConnectorError(f"HTTP {resp.status_code}", self.connector_id)

        data = resp.json()
        results = data.get("results", [])
        records: list[NormalizedRecord] = []

        for item in results:
            case_name = (item.get("caseName") or "").strip()
            date_filed = item.get("dateFiled")
            court = (item.get("court") or item.get("court_id") or "").strip()
            absolute_url = (item.get("absoluteUrl") or "").strip()
            snippet = (item.get("snippet") or "").strip()

            if not case_name:
                continue

            source_url = (
                f"https://www.courtlistener.com{absolute_url}"
                if absolute_url and not absolute_url.startswith("http")
                else absolute_url or f"https://www.courtlistener.com/search/?q={quote_plus(case_name)}"
            )
            published_at = _parse_cl_date(date_filed)

            if watermark and watermark.last_record_date:
                if published_at <= watermark.last_record_date:
                    continue

            records.append(
                NormalizedRecord(
                    title=case_name,
                    summary=snippet[:500] if snippet else case_name,
                    record_type=RecordType.FILING,
                    source_connector_id=self.connector_id,
                    source_label=self.source_label,
                    source_url=source_url,
                    published_at=published_at,
                    fingerprint=generate_fingerprint(
                        self.connector_id, source_url, case_name, published_at
                    ),
                    metadata={"court": court, "date_filed": date_filed},
                    raw_payload=item,
                )
            )

        logger.info("courtlistener.fetched", count=len(records))
        return records

    async def health_check(self) -> HealthStatus:
        headers: dict[str, str] = {}
        if self._settings.courtlistener_api_key:
            headers["Authorization"] = f"Token {self._settings.courtlistener_api_key}"
        try:
            resp = await self._client.get(_BASE_URL, params={"q": "test", "type": "o"}, headers=headers)
            if resp.status_code < 500:
                return HealthStatus.HEALTHY
            return HealthStatus.DEGRADED
        except Exception:
            return HealthStatus.FAILED
