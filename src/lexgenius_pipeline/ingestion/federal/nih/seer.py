"""NIH SEER (Surveillance, Epidemiology, and End Results) connector.

Fetches cancer incidence and survival data from the SEER program API.
Provides epidemiological data supporting pharmaceutical and environmental
mass tort causation analysis.
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

_SEER_API_URL = "https://api.seer.cancer.gov/rest"


def _parse_date(value: str | None) -> datetime:
    if not value:
        return datetime.now(tz=timezone.utc)
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y%m%d"):
        try:
            return datetime.strptime(value.strip()[:10], fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return datetime.now(tz=timezone.utc)


class NIHSEERConnector(BaseConnector):
    """NIH SEER cancer incidence and survival data.

    Accesses SEER program data for cancer statistics, incidence rates,
    and survival data. Requires registration for API access.
    """

    connector_id = "federal.nih.seer"
    source_tier = SourceTier.FEDERAL
    source_label = "NIH SEER Cancer Registry"
    supports_incremental = True

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
            logger.warning("nih_seer.no_query_terms")
            return []

        records: list[NormalizedRecord] = []

        async with create_http_client(timeout=30.0) as client:
            for term in terms:
                await self._rate_limiter.acquire()
                try:
                    # SEER API requires authentication; we use a public
                    # endpoint for rate/statistics data when available.
                    resp = await client.get(
                        "https://seer.cancer.gov/statfacts/html/",
                        follow_redirects=True,
                    )
                    resp.raise_for_status()
                except Exception as exc:
                    logger.warning("federal_nih_seer.fetch_error", term=term, exc_info=True)
                    continue

                # Parse the SEER stat facts page for cancer type links
                from html.parser import HTMLParser

                class SEERParser(HTMLParser):
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
                                self.links.append({
                                    "text": text,
                                    "href": self._current_href,
                                })
                            self._in_a = False
                            self._current_href = ""

                parser = SEERParser()
                try:
                    parser.feed(resp.text)
                except Exception:
                    logger.warning("nih_seer.parse_error")
                    continue

                for link in parser.links:
                    text = link["text"]
                    href = link["href"]
                    if not href.startswith("http"):
                        href = f"https://seer.cancer.gov{href}" if href.startswith("/") else f"https://seer.cancer.gov/{href}"

                    combined = text.lower()
                    if not any(t.lower() in combined for t in terms):
                        continue

                    title = f"SEER Cancer Statistics: {text}"
                    published_at = datetime.now(tz=timezone.utc)

                    if watermark and watermark.last_record_date:
                        if published_at <= watermark.last_record_date:
                            continue

                    records.append(
                        NormalizedRecord(
                            title=title,
                            summary=f"NIH SEER cancer registry data: {text}",
                            record_type=RecordType.RESEARCH,
                            source_connector_id=self.connector_id,
                            source_label=self.source_label,
                            source_url=href,
                            citation_url=href,
                            published_at=published_at,
                            fingerprint=generate_fingerprint(
                                self.connector_id, href, title, published_at
                            ),
                            metadata={
                                "cancer_type": text,
                                "query_terms_matched": [
                                    t for t in terms if t.lower() in combined
                                ],
                            },
                            raw_payload={"title": text, "url": href},
                        )
                    )

                if len(records) >= query.max_records:
                    break

        logger.info("nih_seer.fetched", count=len(records))
        return records

    async def health_check(self) -> HealthStatus:
        async with create_http_client(timeout=30.0) as client:
            try:
                resp = await client.get(
                    "https://seer.cancer.gov/",
                    follow_redirects=True,
                )
                if resp.status_code < 500:
                    return HealthStatus.HEALTHY
                return HealthStatus.DEGRADED
            except Exception:
                return HealthStatus.FAILED
