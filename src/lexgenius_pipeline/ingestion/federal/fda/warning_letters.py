"""FDA Warning Letters connector.

Fetches FDA warning letters from the FDA RSS feed.
Warning letters reveal manufacturing/promotional issues that may
lead to product liability claims.
"""
from __future__ import annotations

from datetime import datetime, timezone
import re
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

_RSS_URL = "https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds/warning-letters"


def _parse_rfc2822(date_str: str) -> datetime:
    if not date_str:
        return datetime.now(tz=timezone.utc)
    from email.utils import parsedate_to_datetime

    try:
        return parsedate_to_datetime(date_str)
    except Exception:
        return datetime.now(tz=timezone.utc)


class FDAWarningLettersConnector(BaseConnector):
    """FDA Warning Letters via RSS.

    Covers warning letters for marketing violations, manufacturing
    deficiencies, GMP violations, and clinical trial irregularities.
    """

    connector_id = "federal.fda.warning_letters"
    source_tier = SourceTier.FEDERAL
    source_label = "FDA Warning Letters"
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
            logger.warning("fda_warning_letters.no_query_terms")
            return []

        records: list[NormalizedRecord] = []

        async with create_http_client() as client:
            await self._rate_limiter.acquire()
            try:
                resp = await client.get(_RSS_URL)
                resp.raise_for_status()
            except Exception as exc:
                logger.warning("federal_fda_warning_letters.fetch_error", exc_info=True)
                return []

            try:
                root = ET.fromstring(resp.text)
            except ET.ParseError as exc:
                logger.warning("rss_parse_error", exc_info=True)
                return []

            for item in root.iter("item"):
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
                if not any(t.lower() in combined for t in terms):
                    continue

                if watermark and watermark.last_record_date:
                    if published_at <= watermark.last_record_date:
                        continue

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

        logger.info("fda_warning_letters.fetched", count=len(records))
        return records

    async def health_check(self) -> HealthStatus:
        async with create_http_client() as client:
            try:
                resp = await client.get(_RSS_URL)
                resp.raise_for_status()
                return HealthStatus.HEALTHY
            except Exception:
                return HealthStatus.FAILED
