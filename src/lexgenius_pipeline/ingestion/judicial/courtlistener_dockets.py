from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote_plus

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

_BASE_URL = "https://www.courtlistener.com/api/rest/v4"
_DOCKETS_URL = f"{_BASE_URL}/dockets/"
_DOCKET_ENTRIES_URL = f"{_BASE_URL}/docket-entries/"
_SEARCH_URL = f"{_BASE_URL}/search/"


def _parse_cl_date(date_str: str | None) -> datetime:
    """Parse CourtListener date strings."""
    if not date_str:
        return datetime.now(tz=timezone.utc)
    try:
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc).replace(tzinfo=timezone.utc)
    except Exception:
        return datetime.now(tz=timezone.utc)


class CourtListenerDocketsConnector(BaseConnector):
    """CourtListener docket entries and metadata connector.

    Extends CourtListener coverage beyond opinions to include docket
    metadata, filing tracking, and attorney information via the
    /dockets/ and /docket-entries/ API endpoints.

    Free API: 10 req/min unauthenticated, 100/min with API key.
    """

    connector_id = "judicial.courtlistener.dockets"
    source_tier = SourceTier.JUDICIAL
    source_label = "CourtListener Dockets"
    supports_incremental = True

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._rate_limiter = AsyncRateLimiter(rate=1.5, burst=3)

    def _auth_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        if self._settings.courtlistener_api_key:
            headers["Authorization"] = f"Token {self._settings.courtlistener_api_key}"
        return headers

    async def fetch_latest(
        self,
        query: IngestionQuery,
        watermark: Watermark | None = None,
    ) -> list[NormalizedRecord]:
        terms = query.query_terms or []
        if not terms:
            logger.warning("courtlistener_dockets.no_query_terms")
            return []

        records: list[NormalizedRecord] = []
        headers = self._auth_headers()

        async with create_http_client() as client:
            search_term = " ".join(terms)
            params: dict[str, str | int] = {
                "q": search_term,
                "type": "r",
                "order_by": "dateFiled desc",
            }

            await self._rate_limiter.acquire()
            try:
                resp = await client.get(_SEARCH_URL, params=params, headers=headers)
            except Exception as exc:
                raise ConnectorError(str(exc), self.connector_id) from exc

            if resp.status_code == 404:
                return []
            if resp.status_code >= 400:
                raise ConnectorError(f"HTTP {resp.status_code}", self.connector_id)

            data = resp.json()
            results: list[dict[str, Any]] = data.get("results", [])

            for item in results:
                record = self._parse_docket_result(item, watermark)
                if record:
                    records.append(record)

                if len(records) >= (query.max_records or 1000):
                    break

        logger.info("courtlistener_dockets.fetched", count=len(records))
        return records

    def _parse_docket_result(
        self,
        item: dict[str, Any],
        watermark: Watermark | None,
    ) -> NormalizedRecord | None:
        """Parse a single docket search result into a NormalizedRecord."""
        case_name = (item.get("caseName") or item.get("case_name") or "").strip()
        if not case_name:
            return None

        docket_number = (item.get("docketNumber") or item.get("docket_number") or "").strip()
        date_filed = item.get("dateFiled") or item.get("date_filed")
        court = (item.get("court") or item.get("court_id") or "").strip()
        absolute_url = (item.get("absoluteUrl") or item.get("absolute_url") or "").strip()
        cause = (item.get("cause") or "").strip()
        nature_of_suit = (item.get("suitNature") or item.get("nature_of_suit") or "").strip()
        assigned_to_str = (item.get("assignedTo") or item.get("assigned_to_str") or "").strip()

        attorneys: list[str] = []
        attorney_data = item.get("attorney") or item.get("attorneys") or []
        if isinstance(attorney_data, list):
            for atty in attorney_data:
                if isinstance(atty, dict):
                    name = (atty.get("name") or atty.get("attorney_name") or "").strip()
                    if name:
                        attorneys.append(name)
                elif isinstance(atty, str):
                    attorneys.append(atty.strip())

        source_url = (
            f"https://www.courtlistener.com{absolute_url}"
            if absolute_url and not absolute_url.startswith("http")
            else absolute_url
            or f"https://www.courtlistener.com/search/?q={quote_plus(case_name)}&type=r"
        )

        published_at = _parse_cl_date(date_filed)

        if watermark and watermark.last_record_date:
            if published_at <= watermark.last_record_date:
                return None

        summary_parts: list[str] = []
        if docket_number:
            summary_parts.append(f"Docket: {docket_number}")
        if court:
            summary_parts.append(f"Court: {court}")
        if nature_of_suit:
            summary_parts.append(f"Nature of Suit: {nature_of_suit}")
        if cause:
            summary_parts.append(f"Cause: {cause}")
        if assigned_to_str:
            summary_parts.append(f"Judge: {assigned_to_str}")
        summary = "; ".join(summary_parts) if summary_parts else case_name

        return NormalizedRecord(
            title=case_name,
            summary=summary[:500],
            record_type=RecordType.FILING,
            source_connector_id=self.connector_id,
            source_label=self.source_label,
            source_url=source_url,
            published_at=published_at,
            fingerprint=generate_fingerprint(
                self.connector_id, source_url, case_name, published_at
            ),
            metadata={
                "docket_number": docket_number,
                "court": court,
                "cause": cause,
                "nature_of_suit": nature_of_suit,
                "assigned_to": assigned_to_str,
                "attorneys": attorneys,
                "date_filed": date_filed,
            },
            raw_payload=item,
        )

    async def health_check(self) -> HealthStatus:
        headers = self._auth_headers()
        async with create_http_client() as client:
            try:
                resp = await client.get(
                    _SEARCH_URL,
                    params={"q": "test", "type": "r"},
                    headers=headers,
                )
                if resp.status_code < 500:
                    return HealthStatus.HEALTHY
                return HealthStatus.DEGRADED
            except Exception:
                return HealthStatus.FAILED
