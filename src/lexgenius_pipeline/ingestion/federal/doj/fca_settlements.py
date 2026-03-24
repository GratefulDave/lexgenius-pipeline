"""DOJ False Claims Act settlements connector.

Scrapes DOJ FCA settlement data from the Justice.gov website.
FCA settlements are a key signal for qui tam litigation and
healthcare/pharmaceutical fraud patterns.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from defusedxml import ElementTree as ET

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

_RSS_URL = "https://www.justice.gov/opa/pr/rss"


def _parse_rfc2822(date_str: str) -> datetime:
    """Parse RFC 2822 date from RSS feed."""
    if not date_str:
        return datetime.now(tz=timezone.utc)
    from email.utils import parsedate_to_datetime

    try:
        return parsedate_to_datetime(date_str)
    except Exception:
        return datetime.now(tz=timezone.utc)


class DOJFCASettlementsConnector(BaseConnector):
    """DOJ False Claims Act settlements connector.

    Fetches DOJ press releases and filters for FCA-related enforcement
    actions including qui tam settlements, healthcare fraud, and
    procurement fraud recoveries.
    """

    connector_id = "federal.doj.fca_settlements"
    source_tier = SourceTier.FEDERAL
    source_label = "DOJ FCA Settlements"
    supports_incremental = True

    # Keywords indicative of FCA-related actions
    _FCA_KEYWORDS = [
        "false claims act", "fca", "qui tam", "whistleblower",
        "healthcare fraud", "medicare fraud", "medicaid fraud",
        "kickback", "anti-kickback", "akstatute", "stark",
        "false claims", "civil fraud", "relator",
    ]

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
            logger.warning("doj_fca_settlements.no_query_terms")
            return []

        records: list[NormalizedRecord] = []

        async with create_http_client() as client:
            await self._rate_limiter.acquire()
            try:
                resp = await client.get(_RSS_URL)
                resp.raise_for_status()
            except Exception:
                logger.warning("doj_fca_settlements.fetch_error", exc_info=True)
                return []

            try:
                root = ET.fromstring(resp.text)
            except ET.ParseError as exc:
                logger.warning("rss_parse_error", exc_info=True)
                return []

            items = root.iter("item")
            for item in items:
                title_el = item.find("title")
                link_el = item.find("link")
                desc_el = item.find("description")
                date_el = item.find("pubDate")

                if title_el is None or link_el is None:
                    continue

                title = (title_el.text or "").strip()
                link = (link_el.text or "").strip()
                description = (desc_el.text or "").strip()
                pub_date_str = (date_el.text or "") if date_el is not None else ""
                published_at = _parse_rfc2822(pub_date_str)

                if not title:
                    continue

                combined = f"{title} {description}".lower()

                # Filter: must contain FCA keyword AND at least one query term (if provided)
                has_fca_keyword = any(kw in combined for kw in self._FCA_KEYWORDS)
                if not has_fca_keyword:
                    continue

                if terms and not any(t.lower() in combined for t in terms):
                    continue

                if watermark and watermark.last_record_date:
                    if published_at <= watermark.last_record_date:
                        continue

                import re
                clean_desc = re.sub(r"<[^>]+>", "", description).strip()

                records.append(
                    NormalizedRecord(
                        title=title,
                        summary=clean_desc[:500] or title,
                        record_type=RecordType.ENFORCEMENT,
                        source_connector_id=self.connector_id,
                        source_label=self.source_label,
                        source_url=link,
                        published_at=published_at,
                        fingerprint=generate_fingerprint(
                            self.connector_id, link, title, published_at
                        ),
                        metadata={
                            "fca_keywords_matched": [
                                kw for kw in self._FCA_KEYWORDS if kw in combined
                            ],
                            "query_terms_matched": [
                                t for t in terms if t.lower() in combined
                            ],
                        },
                        raw_payload={
                            "title": title,
                            "link": link,
                            "description": description,
                            "pub_date": pub_date_str,
                        },
                    )
                )

                if len(records) >= query.max_records:
                    break

        logger.info("doj_fca_settlements.fetched", count=len(records))
        return records

    async def health_check(self) -> HealthStatus:
        async with create_http_client() as client:
            try:
                resp = await client.get(_RSS_URL)
                resp.raise_for_status()
                ET.fromstring(resp.text)
                return HealthStatus.HEALTHY
            except Exception:
                return HealthStatus.FAILED
