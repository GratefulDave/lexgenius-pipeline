from __future__ import annotations

import re
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

_BASE_URL = "https://www.ncsc.org"
_COURT_STATS_URL = f"{_BASE_URL}/__data/assets/pdf_file/"
_TOPICS_URL = f"{_BASE_URL}/topics/court-statistics"

# Pattern for extracting report links and titles from NCSC pages
_LINK_RE = re.compile(
    r'<a\s+[^>]*href=["\']([^"\']*(?:\.pdf|court-statistics)[^"\']*)["\'][^>]*>(.*?)</a>',
    re.DOTALL | re.IGNORECASE,
)
_TAG_STRIP = re.compile(r"<[^>]+>")


def _parse_ncsc_date(date_str: str | None) -> datetime:
    """Parse dates from NCSC pages."""
    if not date_str:
        return datetime.now(tz=timezone.utc)
    cleaned = date_str.strip()
    for fmt in (
        "%B %d, %Y",
        "%b %d, %Y",
        "%m/%d/%Y",
        "%Y-%m-%d",
        "%B %Y",
        "%Y",
    ):
        try:
            return datetime.strptime(cleaned, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    # Try to extract just a year
    year_match = re.search(r"(20\d{2})", cleaned)
    if year_match:
        return datetime(int(year_match.group(1)), 1, 1, tzinfo=timezone.utc)
    return datetime.now(tz=timezone.utc)


def _extract_reports_from_html(html: str) -> list[dict[str, Any]]:
    """Extract statistical report entries from NCSC HTML page."""
    reports: list[dict[str, Any]] = []
    seen_urls: set[str] = set()

    for match in _LINK_RE.finditer(html):
        href = match.group(1).strip()
        link_text = _TAG_STRIP.sub(" ", match.group(2)).strip()

        if not link_text or len(link_text) < 5:
            continue

        if href.startswith("/"):
            href = f"{_BASE_URL}{href}"

        if href in seen_urls:
            continue
        seen_urls.add(href)

        start = max(0, match.start() - 200)
        end = min(len(html), match.end() + 200)
        context = _TAG_STRIP.sub(" ", html[start:end]).strip()

        date_match = re.search(
            r"(\w+\s+\d{1,2},?\s+\d{4}|\d{1,2}/\d{1,2}/\d{4}|20\d{2})",
            context,
        )
        date_str = date_match.group(1) if date_match else ""

        reports.append(
            {
                "title": link_text,
                "url": href,
                "date": date_str,
                "context": context[:300],
            }
        )

    return reports


class NCSCStatisticsConnector(BaseConnector):
    """National Center for State Courts statistics connector.

    Scrapes ncsc.org Court Statistics Project for civil case filing
    statistics by state, trend data on tort filings, and published
    research reports.
    """

    connector_id = "judicial.ncsc.statistics"
    source_tier = SourceTier.JUDICIAL
    source_label = "NCSC Court Statistics"
    supports_incremental = True

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._rate_limiter = AsyncRateLimiter(rate=0.5, burst=2)

    async def fetch_latest(
        self,
        query: IngestionQuery,
        watermark: Watermark | None = None,
    ) -> list[NormalizedRecord]:
        records: list[NormalizedRecord] = []
        query_terms = query.query_terms or []

        async with create_http_client(timeout=60.0) as client:
            await self._rate_limiter.acquire()
            try:
                resp = await client.get(_TOPICS_URL)
                resp.raise_for_status()
            except Exception as exc:
                raise ConnectorError(str(exc), self.connector_id) from exc

            html = resp.text
            reports = _extract_reports_from_html(html)

            for report in reports:
                title = report.get("title", "")
                url = report.get("url", "")
                date_str = report.get("date", "")
                context = report.get("context", "")

                if not title:
                    continue

                if query_terms:
                    combined = f"{title} {context}".lower()
                    if not any(term.lower() in combined for term in query_terms):
                        continue

                published_at = _parse_ncsc_date(date_str)

                if watermark and watermark.last_record_date:
                    if published_at <= watermark.last_record_date:
                        continue

                source_url = url or _TOPICS_URL

                records.append(
                    NormalizedRecord(
                        title=title,
                        summary=context[:500] if context else title,
                        record_type=RecordType.RESEARCH,
                        source_connector_id=self.connector_id,
                        source_label=self.source_label,
                        source_url=source_url,
                        published_at=published_at,
                        fingerprint=generate_fingerprint(
                            self.connector_id,
                            source_url,
                            title,
                            published_at,
                        ),
                        metadata={
                            "report_type": "court_statistics",
                            "publication_date": date_str,
                            "is_pdf": url.lower().endswith(".pdf") if url else False,
                        },
                        raw_payload=report,
                    )
                )

        logger.info("ncsc.statistics.fetched", count=len(records))
        return records

    async def health_check(self) -> HealthStatus:
        async with create_http_client() as client:
            try:
                resp = await client.get(_BASE_URL)
                if resp.status_code < 500:
                    return HealthStatus.HEALTHY
                return HealthStatus.DEGRADED
            except Exception:
                return HealthStatus.FAILED
