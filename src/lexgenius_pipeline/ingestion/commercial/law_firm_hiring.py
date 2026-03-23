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

_SEARCH_URLS = [
    "https://www.indeed.com/jobs?q=%22mass+tort%22+attorney",
    "https://www.indeed.com/jobs?q=%22product+liability%22+attorney",
]
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_JOB_TITLE_RE = re.compile(
    r'<(?:h2|a)[^>]*class="[^"]*(?:jobTitle|job-title|title)[^"]*"[^>]*>(?:<[^>]*>)*([^<]+)',
    re.IGNORECASE,
)
_JOB_LINK_RE = re.compile(
    r'<a[^>]*href="(/rc/[^"]+|/viewjob[^"]+|/pagead/[^"]+)"[^>]*>',
    re.IGNORECASE,
)
_COMPANY_RE = re.compile(
    r'<span[^>]*class="[^"]*(?:company|companyName)[^"]*"[^>]*>([^<]+)</span>',
    re.IGNORECASE,
)
_LOCATION_RE = re.compile(
    r'<div[^>]*class="[^"]*(?:companyLocation|location)[^"]*"[^>]*>([^<]+)</div>',
    re.IGNORECASE,
)
_DATE_RE = re.compile(
    r'<span[^>]*class="[^"]*date[^"]*"[^>]*>([^<]+)</span>',
    re.IGNORECASE,
)


def _strip_html(text: str) -> str:
    return _HTML_TAG_RE.sub("", text).strip()


class LawFirmHiringConnector(BaseConnector):
    connector_id = "commercial.law_firm_hiring"
    source_tier = SourceTier.COMMERCIAL
    source_label = "Law Firm Mass Tort Hiring"
    supports_incremental = True

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._rate_limiter = AsyncRateLimiter(rate=0.3, burst=1)

    async def fetch_latest(
        self,
        query: IngestionQuery,
        watermark: Watermark | None = None,
    ) -> list[NormalizedRecord]:
        records: list[NormalizedRecord] = []

        async with create_http_client() as client:
            for search_url in _SEARCH_URLS:
                await self._rate_limiter.acquire()
                try:
                    resp = await client.get(search_url)
                except Exception as exc:
                    logger.warning(
                        "law_firm_hiring.request_error",
                        url=search_url,
                        error=str(exc),
                    )
                    continue

                if resp.status_code >= 400:
                    logger.warning(
                        "law_firm_hiring.http_error",
                        url=search_url,
                        status=resp.status_code,
                    )
                    continue

                html = resp.text
                titles = _JOB_TITLE_RE.findall(html)
                links = _JOB_LINK_RE.findall(html)
                companies = _COMPANY_RE.findall(html)
                locations = _LOCATION_RE.findall(html)
                dates = _DATE_RE.findall(html)

                published_at = datetime.now(tz=timezone.utc)

                for i, title in enumerate(titles):
                    title = _strip_html(title).strip()
                    if not title:
                        continue

                    link = links[i] if i < len(links) else ""
                    if link and not link.startswith("http"):
                        link = f"https://www.indeed.com{link}"
                    source_url = link or search_url

                    company = companies[i].strip() if i < len(companies) else ""
                    location = locations[i].strip() if i < len(locations) else ""
                    date_text = dates[i].strip() if i < len(dates) else ""

                    summary = f"{title} at {company}" if company else title
                    if location:
                        summary += f" ({location})"

                    records.append(
                        NormalizedRecord(
                            title=title,
                            summary=summary,
                            record_type=RecordType.NEWS,
                            source_connector_id=self.connector_id,
                            source_label=self.source_label,
                            source_url=source_url,
                            published_at=published_at,
                            fingerprint=generate_fingerprint(
                                self.connector_id, source_url, title, published_at
                            ),
                            metadata={
                                "company": company,
                                "location": location,
                                "posted": date_text,
                                "category": "mass_tort_hiring",
                            },
                            raw_payload={"title": title, "company": company, "link": link},
                        )
                    )

        logger.info("law_firm_hiring.fetched", count=len(records))
        return records

    async def health_check(self) -> HealthStatus:
        async with create_http_client() as client:
            try:
                resp = await client.get(_SEARCH_URLS[0])
                if resp.status_code < 500:
                    return HealthStatus.HEALTHY
                return HealthStatus.DEGRADED
            except Exception:
                return HealthStatus.FAILED
