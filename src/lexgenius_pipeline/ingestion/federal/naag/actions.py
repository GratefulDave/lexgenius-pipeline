"""NAAG (National Association of Attorneys General) connector.

Scrapes NAAG website for multistate settlements and AG enforcement
actions. AG settlements often set templates for private class actions.
"""
from __future__ import annotations

from datetime import datetime, timezone
import re
from html.parser import HTMLParser

import structlog

from lexgenius_pipeline.common.date_utils import UNKNOWN_DATE, parse_date
from lexgenius_pipeline.common.errors import ConnectorError
from lexgenius_pipeline.common.http_client import create_http_client
from lexgenius_pipeline.common.models import IngestionQuery, NormalizedRecord, Watermark
from lexgenius_pipeline.common.rate_limiter import AsyncRateLimiter
from lexgenius_pipeline.common.types import HealthStatus, RecordType, SourceTier
from lexgenius_pipeline.ingestion.base import BaseConnector
from lexgenius_pipeline.ingestion.normalize import generate_fingerprint
from lexgenius_pipeline.settings import Settings, get_settings

logger = structlog.get_logger(__name__)

_BASE_URL = "https://www.naag.org"



class _NAAGParser(HTMLParser):
    """Minimal HTML parser to extract links and text from NAAG pages."""

    def __init__(self) -> None:
        super().__init__()
        self.links: list[dict[str, str]] = []
        self._current_data: list[str] = []
        self._in_a = False
        self._current_href = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str]]) -> None:
        if tag == "a":
            self._in_a = True
            self._current_data = []
            for attr, val in attrs:
                if attr == "href":
                    self._current_href = val

    def handle_data(self, data: str) -> None:
        if self._in_a:
            self._current_data.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._in_a:
            text = "".join(self._current_data).strip()
            if text and self._current_href:
                self.links.append({"text": text, "href": self._current_href})
            self._in_a = False
            self._current_href = ""


class NAAGActionsConnector(BaseConnector):
    """NAAG multistate settlements and AG enforcement actions.

    Scrapes NAAG press releases and settlement announcements for
    multistate enforcement actions relevant to mass tort patterns.

    NOTE: NAAG is the National Association of Attorneys General, a
    *state-level* AG organization.  It is classified under the federal
    connector tree because its multistate settlements frequently parallel
    federal enforcement and are consumed alongside federal signals.
    """

    connector_id = "federal.naag.actions"
    # Classified as FEDERAL for pipeline purposes; see docstring above.
    source_tier = SourceTier.FEDERAL
    source_label = "NAAG Settlements & Actions"
    supports_incremental = False

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._rate_limiter = AsyncRateLimiter(rate=2.0, burst=3)

    async def fetch_latest(
        self,
        query: IngestionQuery,
        watermark: Watermark | None = None,
    ) -> list[NormalizedRecord]:
        terms = query.query_terms or []
        if not terms:
            logger.warning("naag_actions.no_query_terms")
            return []

        records: list[NormalizedRecord] = []

        async with create_http_client(timeout=30.0) as client:
            await self._rate_limiter.acquire()
            try:
                resp = await client.get(
                    f"{_BASE_URL}/news/",
                    follow_redirects=True,
                )
                resp.raise_for_status()
            except Exception as exc:
                raise ConnectorError(
                    f"Failed to fetch from naag_actions: {exc}",
                    connector_id=self.connector_id,
                ) from exc

            parser = _NAAGParser()
            try:
                parser.feed(resp.text)
            except Exception:
                logger.warning("naag_actions.parse_error")
                return []

            for link in parser.links:
                text = link["text"]
                href = link["href"]
                if not href.startswith("http"):
                    href = f"{_BASE_URL}{href}" if href.startswith("/") else f"{_BASE_URL}/{href}"

                combined = text.lower()
                if not any(t.lower() in combined for t in terms):
                    continue

                title = f"NAAG: {text}"
                published_at = UNKNOWN_DATE

                if watermark and watermark.last_record_date:
                    if published_at <= watermark.last_record_date:
                        continue

                records.append(
                    NormalizedRecord(
                        title=title,
                        summary=f"NAAG action: {text}",
                        record_type=RecordType.ENFORCEMENT,
                        source_connector_id=self.connector_id,
                        source_label=self.source_label,
                        source_url=href,
                        published_at=published_at,
                        fingerprint=generate_fingerprint(
                            self.connector_id, href, title, published_at
                        ),
                        metadata={
                            "query_terms_matched": [
                                t for t in terms if t.lower() in combined
                            ],
                        },
                        raw_payload={"title": text, "url": href},
                    )
                )

                if len(records) >= query.max_records:
                    break

        logger.info("naag_actions.fetched", count=len(records))
        return records

    async def health_check(self) -> HealthStatus:
        async with create_http_client(timeout=30.0) as client:
            try:
                resp = await client.get(_BASE_URL, follow_redirects=True)
                if resp.status_code < 500:
                    return HealthStatus.HEALTHY
                return HealthStatus.DEGRADED
            except Exception:
                return HealthStatus.FAILED
