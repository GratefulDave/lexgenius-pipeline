from __future__ import annotations

import re
from datetime import datetime, timezone

import structlog
from bs4 import BeautifulSoup

from lexgenius_pipeline.common.errors import ConnectorError
from lexgenius_pipeline.common.http_client import create_http_client
from lexgenius_pipeline.common.models import IngestionQuery, NormalizedRecord, Watermark
from lexgenius_pipeline.common.rate_limiter import AsyncRateLimiter
from lexgenius_pipeline.common.types import HealthStatus, RecordType, SourceTier
from lexgenius_pipeline.ingestion.base import BaseConnector
from lexgenius_pipeline.ingestion.normalize import generate_fingerprint
from lexgenius_pipeline.settings import Settings, get_settings

logger = structlog.get_logger(__name__)

# WARNING: Scraping Indeed may violate their robots.txt and Terms of Service.
# Consider migrating to the Indeed Publisher API or Indeed Apply API for
# production use. This connector is provided for prototyping purposes only.
_SEARCH_URLS = [
    "https://www.indeed.com/jobs?q=%22mass+tort%22+attorney",
    "https://www.indeed.com/jobs?q=%22product+liability%22+attorney",
]


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

                soup = BeautifulSoup(resp.text, "html.parser")
                published_at = datetime.now(tz=timezone.utc)

                # Find job cards by heading elements with job title classes
                for heading in soup.find_all(
                    ["h2", "a"],
                    class_=re.compile(r"jobTitle|job-title|title"),
                ):
                    title = heading.get_text(strip=True)
                    if not title:
                        continue

                    # Extract link
                    link_el = heading if heading.name == "a" else heading.find("a", href=True)
                    link = ""
                    if link_el and link_el.get("href"):
                        link = link_el["href"]
                        if not link.startswith("http"):
                            link = f"https://www.indeed.com{link}"
                    source_url = link or search_url

                    # Find company and location from nearby elements
                    card = heading.find_parent()
                    company = ""
                    location = ""
                    date_text = ""

                    if card:
                        company_el = card.find(
                            "span", class_=re.compile(r"company|companyName")
                        )
                        if company_el:
                            company = company_el.get_text(strip=True)

                        location_el = card.find(
                            "div", class_=re.compile(r"companyLocation|location")
                        )
                        if location_el:
                            location = location_el.get_text(strip=True)

                        date_el = card.find("span", class_=re.compile(r"date"))
                        if date_el:
                            date_text = date_el.get_text(strip=True)

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
