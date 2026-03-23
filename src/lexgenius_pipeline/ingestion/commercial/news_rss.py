from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

import structlog

from lexgenius_pipeline.common.errors import ConnectorError
from lexgenius_pipeline.common.http_client import create_http_client
from lexgenius_pipeline.common.models import IngestionQuery, NormalizedRecord, Watermark
from lexgenius_pipeline.common.types import HealthStatus, RecordType, SourceTier
from lexgenius_pipeline.ingestion.base import BaseConnector
from lexgenius_pipeline.ingestion.normalize import generate_fingerprint
from lexgenius_pipeline.settings import Settings, get_settings

logger = structlog.get_logger(__name__)

_HTML_TAG_RE = re.compile(r"<[^>]+>")

RSS_FEED_REGISTRY: list[dict[str, str]] = [
    {
        "url": "https://feeds.reuters.com/reuters/businessNews",
        "source_id": "reuters",
        "source_label": "Reuters Business",
        "category": "business",
    },
    {
        "url": "https://feeds.apnews.com/rss/apf-business",
        "source_id": "ap_news",
        "source_label": "AP News Business",
        "category": "business",
    },
    {
        "url": "https://rss.nytimes.com/services/xml/rss/nyt/Business.xml",
        "source_id": "nyt",
        "source_label": "NYT Business",
        "category": "business",
    },
    {
        "url": "https://feeds.a.dj.com/rss/WSJcomUSBusiness.xml",
        "source_id": "wsj",
        "source_label": "WSJ US Business",
        "category": "business",
    },
    {
        "url": "http://rss.cnn.com/rss/money_latest.rss",
        "source_id": "cnn",
        "source_label": "CNN Money",
        "category": "business",
    },
]


def _strip_html(text: str) -> str:
    return _HTML_TAG_RE.sub("", text).strip()


def _parse_pub_date(date_str: str) -> datetime:
    try:
        return parsedate_to_datetime(date_str).astimezone(timezone.utc).replace(tzinfo=timezone.utc)
    except Exception:
        return datetime.now(tz=timezone.utc)


def _parse_rss_feed(
    content: str,
    feed: dict[str, str],
    watermark: Watermark | None,
    connector_id: str,
) -> list[NormalizedRecord]:
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return []

    # Handle both RSS and Atom feeds
    channel = root.find("channel")
    items = channel.findall("item") if channel is not None else []

    # Atom fallback
    if not items:
        atom_ns = "{http://www.w3.org/2005/Atom}"
        items = root.findall(f"{atom_ns}entry")

    records: list[NormalizedRecord] = []
    for item in items:
        title_el = item.find("title") or item.find("{http://www.w3.org/2005/Atom}title")
        link_el = item.find("link") or item.find("{http://www.w3.org/2005/Atom}link")
        desc_el = item.find("description") or item.find("{http://www.w3.org/2005/Atom}summary")
        date_el = item.find("pubDate") or item.find("{http://www.w3.org/2005/Atom}published")

        title = (title_el.text or "").strip() if title_el is not None else ""
        link = ""
        if link_el is not None:
            link = link_el.get("href") or link_el.text or ""
        link = link.strip()
        description = _strip_html((desc_el.text or "") if desc_el is not None else "")
        pub_date_raw = (date_el.text or "") if date_el is not None else ""

        if not title or not link:
            continue

        published_at = _parse_pub_date(pub_date_raw)
        if watermark and watermark.last_record_date:
            if published_at <= watermark.last_record_date:
                continue

        records.append(
            NormalizedRecord(
                title=title,
                summary=description[:500] if description else title,
                record_type=RecordType.NEWS,
                source_connector_id=connector_id,
                source_label=feed["source_label"],
                source_url=link,
                published_at=published_at,
                fingerprint=generate_fingerprint(connector_id, link, title, published_at),
                metadata={
                    "source_id": feed["source_id"],
                    "category": feed["category"],
                },
                raw_payload={"title": title, "link": link},
            )
        )
    return records


class NewsRSSConnector(BaseConnector):
    """Multi-source news RSS aggregator connector."""

    connector_id = "commercial.news_rss"
    source_tier = SourceTier.COMMERCIAL
    source_label = "News RSS Feeds"
    supports_incremental = True

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._client = create_http_client()

    async def fetch_latest(
        self,
        query: IngestionQuery,
        watermark: Watermark | None = None,
    ) -> list[NormalizedRecord]:
        records: list[NormalizedRecord] = []

        for feed in RSS_FEED_REGISTRY:
            try:
                resp = await self._client.get(feed["url"])
            except Exception as exc:
                logger.warning(
                    "news_rss.feed_error",
                    source_id=feed["source_id"],
                    error=str(exc),
                )
                continue

            if resp.status_code >= 400:
                logger.warning(
                    "news_rss.feed_http_error",
                    source_id=feed["source_id"],
                    status=resp.status_code,
                )
                continue

            feed_records = _parse_rss_feed(resp.text, feed, watermark, self.connector_id)
            records.extend(feed_records)
            logger.info(
                "news_rss.feed_fetched",
                source_id=feed["source_id"],
                count=len(feed_records),
            )

        logger.info("news_rss.total_fetched", count=len(records))
        return records

    async def health_check(self) -> HealthStatus:
        # Try the first feed as a health indicator
        try:
            resp = await self._client.get(RSS_FEED_REGISTRY[0]["url"])
            if resp.status_code < 500:
                return HealthStatus.HEALTHY
            return HealthStatus.DEGRADED
        except Exception:
            return HealthStatus.FAILED
