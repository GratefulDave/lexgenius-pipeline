from __future__ import annotations

import re
from datetime import datetime, timezone

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

_BASE_URL = "https://www.aboutlawsuits.com"
_HTML_TAG_RE = re.compile(r"<[^>]+>")
# Match article blocks: <article ...> or <h2 class="entry-title"><a href="...">...</a></h2>
_ARTICLE_RE = re.compile(
    r'<h[23][^>]*class="[^"]*entry-title[^"]*"[^>]*>\s*'
    r'<a[^>]*href="([^"]+)"[^>]*>([^<]+)</a>',
    re.IGNORECASE,
)
_DATE_RE = re.compile(
    r'<time[^>]*datetime="([^"]+)"[^>]*>',
    re.IGNORECASE,
)
_EXCERPT_RE = re.compile(
    r'<div[^>]*class="[^"]*entry-(?:summary|content|excerpt)[^"]*"[^>]*>(.*?)</div>',
    re.IGNORECASE | re.DOTALL,
)


def _strip_html(text: str) -> str:
    return _HTML_TAG_RE.sub("", text).strip()


def _parse_iso_date(date_str: str) -> datetime:
    try:
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc).replace(tzinfo=timezone.utc)
    except Exception:
        return datetime.now(tz=timezone.utc)


class AboutLawsuitsConnector(BaseConnector):
    """AboutLawsuits.com mass tort news scraper."""

    connector_id = "commercial.aboutlawsuits"
    source_tier = SourceTier.COMMERCIAL
    source_label = "AboutLawsuits.com"
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

        async with create_http_client() as client:
            await self._rate_limiter.acquire()
            try:
                resp = await client.get(_BASE_URL)
            except Exception as exc:
                raise ConnectorError(str(exc), self.connector_id) from exc

            if resp.status_code >= 400:
                raise ConnectorError(f"HTTP {resp.status_code}", self.connector_id)

            html = resp.text

            # Extract article links and titles
            articles = _ARTICLE_RE.findall(html)
            dates = _DATE_RE.findall(html)
            excerpts = _EXCERPT_RE.findall(html)

            terms_lower = [t.lower() for t in (query.query_terms or [])]

            for i, (link, title) in enumerate(articles):
                title = title.strip()
                link = link.strip()
                if not link.startswith("http"):
                    link = f"{_BASE_URL}{link}"

                if not title or not link:
                    continue

                # Filter by query terms if provided
                if terms_lower:
                    if not any(term in title.lower() for term in terms_lower):
                        continue

                published_at = (
                    _parse_iso_date(dates[i]) if i < len(dates) else datetime.now(tz=timezone.utc)
                )
                if watermark and watermark.last_record_date:
                    if published_at <= watermark.last_record_date:
                        continue

                summary = _strip_html(excerpts[i])[:500] if i < len(excerpts) else title

                records.append(
                    NormalizedRecord(
                        title=title,
                        summary=summary,
                        record_type=RecordType.NEWS,
                        source_connector_id=self.connector_id,
                        source_label=self.source_label,
                        source_url=link,
                        published_at=published_at,
                        fingerprint=generate_fingerprint(
                            self.connector_id, link, title, published_at
                        ),
                        metadata={"category": "mass_tort_news"},
                        raw_payload={"title": title, "link": link},
                    )
                )

        logger.info("aboutlawsuits.fetched", count=len(records))
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
