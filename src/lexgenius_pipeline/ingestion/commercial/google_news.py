from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus

import structlog

from lexgenius_pipeline.common.errors import ConnectorError
from lexgenius_pipeline.common.http_client import create_http_client
from lexgenius_pipeline.common.models import IngestionQuery, NormalizedRecord, Watermark
from lexgenius_pipeline.common.types import HealthStatus, RecordType, SourceTier
from lexgenius_pipeline.ingestion.base import BaseConnector
from lexgenius_pipeline.ingestion.normalize import generate_fingerprint
from lexgenius_pipeline.settings import Settings, get_settings

logger = structlog.get_logger(__name__)

_BASE_URL = "https://news.google.com/rss/search"
_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(text: str) -> str:
    return _HTML_TAG_RE.sub("", text).strip()


def _parse_pub_date(date_str: str) -> datetime:
    try:
        return parsedate_to_datetime(date_str).astimezone(timezone.utc).replace(tzinfo=timezone.utc)
    except Exception:
        return datetime.now(tz=timezone.utc)


class GoogleNewsConnector(BaseConnector):
    """Google News RSS connector for news articles."""

    connector_id = "commercial.google_news"
    source_tier = SourceTier.COMMERCIAL
    source_label = "Google News"
    supports_incremental = True

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._client = create_http_client()

    async def fetch_latest(
        self,
        query: IngestionQuery,
        watermark: Watermark | None = None,
    ) -> list[NormalizedRecord]:
        terms = query.query_terms or []
        if not terms:
            logger.warning("google_news.no_query_terms")
            return []

        search_term = " ".join(terms)
        url = f"{_BASE_URL}?q={quote_plus(search_term)}"

        try:
            resp = await self._client.get(url)
        except Exception as exc:
            raise ConnectorError(str(exc), self.connector_id) from exc

        if resp.status_code >= 400:
            raise ConnectorError(f"HTTP {resp.status_code}", self.connector_id)

        try:
            root = ET.fromstring(resp.text)
        except ET.ParseError as exc:
            raise ConnectorError(f"XML parse error: {exc}", self.connector_id) from exc

        ns = {"": ""}
        channel = root.find("channel")
        if channel is None:
            return []

        records: list[NormalizedRecord] = []
        for item in channel.findall("item"):
            title = (item.findtext("title") or "").strip()
            description = _strip_html(item.findtext("description") or "")
            link = (item.findtext("link") or "").strip()
            pub_date_raw = item.findtext("pubDate") or ""
            source_el = item.find("source")
            source_name = source_el.text if source_el is not None else "Google News"

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
                    source_connector_id=self.connector_id,
                    source_label=self.source_label,
                    source_url=link,
                    published_at=published_at,
                    fingerprint=generate_fingerprint(
                        self.connector_id, link, title, published_at
                    ),
                    metadata={"source": source_name},
                    raw_payload={"title": title, "description": description, "link": link},
                )
            )

        logger.info("google_news.fetched", count=len(records))
        return records

    async def health_check(self) -> HealthStatus:
        try:
            resp = await self._client.get(f"{_BASE_URL}?q=news")
            if resp.status_code < 500:
                return HealthStatus.HEALTHY
            return HealthStatus.DEGRADED
        except Exception:
            return HealthStatus.FAILED
