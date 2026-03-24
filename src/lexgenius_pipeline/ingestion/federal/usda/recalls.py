"""USDA FSIS food safety recalls connector.

Fetches meat, poultry, and egg product recalls from USDA FSIS.
Relevant for foodborne illness and contamination class actions.
"""
from __future__ import annotations

from datetime import datetime, timezone
import re
from xml.etree import ElementTree as ET

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

_RSS_URL = "https://www.fsis.usda.gov/recalls?field_recalls_type_value%5B%5D=Recall&field_recalls_status_value%5B%5D=Active&items_per_page=50&feed=rss"


def _parse_rfc2822(date_str: str) -> datetime:
    if not date_str:
        return datetime.now(tz=timezone.utc)
    from email.utils import parsedate_to_datetime

    try:
        return parsedate_to_datetime(date_str)
    except Exception:
        return datetime.now(tz=timezone.utc)


class USDRecallsConnector(BaseConnector):
    """USDA FSIS meat, poultry, and egg product recalls via RSS.

    Covers food recalls and public health alerts from the Food Safety
    and Inspection Service.
    """

    connector_id = "federal.usda.recalls"
    source_tier = SourceTier.FEDERAL
    source_label = "USDA FSIS Recalls"
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
            logger.warning("usda_recalls.no_query_terms")
            return []

        records: list[NormalizedRecord] = []

        async with create_http_client() as client:
            await self._rate_limiter.acquire()
            try:
                resp = await client.get(_RSS_URL)
                resp.raise_for_status()
            except Exception as exc:
                logger.warning("federal_usda_recalls.fetch_error", exc_info=True)
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
                        record_type=RecordType.RECALL,
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

        logger.info("usda_recalls.fetched", count=len(records))
        return records

    async def health_check(self) -> HealthStatus:
        async with create_http_client() as client:
            try:
                resp = await client.get(
                    "https://www.fsis.usda.gov/recalls",
                    follow_redirects=True,
                )
                if resp.status_code < 500:
                    return HealthStatus.HEALTHY
                return HealthStatus.DEGRADED
            except Exception:
                return HealthStatus.FAILED
