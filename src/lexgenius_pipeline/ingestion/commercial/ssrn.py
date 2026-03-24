from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import structlog

from lexgenius_pipeline.common.errors import ConnectorError
from lexgenius_pipeline.common.http_client import create_http_client
from lexgenius_pipeline.common.models import IngestionQuery, NormalizedRecord, Watermark
from lexgenius_pipeline.common.types import HealthStatus, RecordType, SourceTier
from lexgenius_pipeline.ingestion.base import BaseConnector
from lexgenius_pipeline.ingestion.normalize import generate_fingerprint
from lexgenius_pipeline.settings import Settings, get_settings

logger = structlog.get_logger(__name__)

# SSRN Legal Studies eJournal RSS
_FEED_URL = "https://papers.ssrn.com/sol3/Jeljour_results.cfm?form_name=journalBrowse&journal_id=855&Network=no&lim=false&npage=1&SortOrder=ab_approval_date&stype=rss"
_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(text: str) -> str:
    return _HTML_TAG_RE.sub("", text).strip()


def _parse_pub_date(date_str: str) -> datetime:
    try:
        return parsedate_to_datetime(date_str).astimezone(timezone.utc).replace(tzinfo=timezone.utc)
    except Exception:
        # Try ISO 8601 as fallback
        try:
            dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            return dt.astimezone(timezone.utc).replace(tzinfo=timezone.utc)
        except Exception:
            logger.warning("ssrn.unparseable_date", date_str=date_str)
            return datetime.now(tz=timezone.utc)


class SSRNConnector(BaseConnector):
    """SSRN pre-publication legal scholarship RSS connector."""

    connector_id = "commercial.ssrn"
    source_tier = SourceTier.COMMERCIAL
    source_label = "SSRN Legal Scholarship"
    supports_incremental = True

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    async def fetch_latest(
        self,
        query: IngestionQuery,
        watermark: Watermark | None = None,
    ) -> list[NormalizedRecord]:
        async with create_http_client() as client:
            try:
                resp = await client.get(_FEED_URL)
            except Exception as exc:
                raise ConnectorError(str(exc), self.connector_id) from exc

            if resp.status_code >= 400:
                raise ConnectorError(f"HTTP {resp.status_code}", self.connector_id)

            try:
                root = ET.fromstring(resp.text)
            except ET.ParseError as exc:
                raise ConnectorError(f"XML parse error: {exc}", self.connector_id) from exc

            channel = root.find("channel")
            if channel is None:
                return []

            # Filter by query terms if provided
            terms_lower = [t.lower() for t in (query.query_terms or [])]

            records: list[NormalizedRecord] = []
            for item in channel.findall("item"):
                title = (item.findtext("title") or "").strip()
                link = (item.findtext("link") or "").strip()
                description = _strip_html(item.findtext("description") or "")
                pub_date_raw = item.findtext("pubDate") or ""
                author = (item.findtext("{http://purl.org/dc/elements/1.1/}creator") or "").strip()

                if not title or not link:
                    continue

                # If query terms provided, filter to relevant papers
                if terms_lower:
                    combined = f"{title} {description}".lower()
                    if not any(term in combined for term in terms_lower):
                        continue

                published_at = _parse_pub_date(pub_date_raw)
                if watermark and watermark.last_record_date:
                    if published_at <= watermark.last_record_date:
                        continue

                records.append(
                    NormalizedRecord(
                        title=title,
                        summary=description[:500] if description else title,
                        record_type=RecordType.RESEARCH,
                        source_connector_id=self.connector_id,
                        source_label=self.source_label,
                        source_url=link,
                        published_at=published_at,
                        fingerprint=generate_fingerprint(self.connector_id, link, title, published_at),
                        metadata={"author": author, "category": "legal_scholarship"},
                        raw_payload={"title": title, "link": link, "description": description},
                    )
                )

        logger.info("ssrn.fetched", count=len(records))
        return records

    async def health_check(self) -> HealthStatus:
        async with create_http_client() as client:
            try:
                resp = await client.get(_FEED_URL)
                if resp.status_code < 500:
                    return HealthStatus.HEALTHY
                return HealthStatus.DEGRADED
            except Exception:
                return HealthStatus.FAILED
