"""FJC (Federal Judicial Center) Integrated Database connector.

Downloads and parses the FJC IDB civil case data for macro trend
analysis and market sizing of federal litigation patterns.
"""
from __future__ import annotations

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

_FJC_IDB_URL = "https://www.fjc.gov/research/idb"


def _parse_date(value: str | None) -> datetime:
    if not value:
        return datetime.now(tz=timezone.utc)
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y%m%d"):
        try:
            return datetime.strptime(value.strip()[:10], fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return datetime.now(tz=timezone.utc)


class FJCIDBConnector(BaseConnector):
    """FJC Integrated Database civil case statistics.

    Accesses the FJC IDB for civil case opening/termination data,
    settlement patterns, time-to-trial, and MDL statistics.
    This is a bulk download source with quarterly updates.
    """

    connector_id = "federal.fjc.idb"
    source_tier = SourceTier.FEDERAL
    source_label = "FJC Integrated Database"
    supports_incremental = True

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._rate_limiter = AsyncRateLimiter(rate=0.5, burst=1)

    async def fetch_latest(
        self,
        query: IngestionQuery,
        watermark: Watermark | None = None,
    ) -> list[NormalizedRecord]:
        terms = query.query_terms or []
        if not terms:
            logger.warning("fjc_idb.no_query_terms")
            return []

        records: list[NormalizedRecord] = []

        async with create_http_client(timeout=60.0) as client:
            await self._rate_limiter.acquire()
            try:
                # Fetch the IDB download page for available datasets
                resp = await client.get(
                    f"{_FJC_IDB_URL}",
                    follow_redirects=True,
                )
                resp.raise_for_status()
            except Exception:
                logger.warning("fjc_idb.fetch_error", exc_info=True)
                return []

            # Parse available data files from the page
            from html.parser import HTMLParser

            class FileParser(HTMLParser):
                def __init__(self) -> None:
                    super().__init__()
                    self.links: list[dict[str, str]] = []
                    self._current_data: list[str] = []
                    self._in_a = False
                    self._current_href = ""

                def handle_starttag(self, tag: str, attrs: list[tuple[str, str]]) -> None:
                    if tag == "a":
                        self._in_a = True
                        self._current_data = []
                        for attr, val in attrs:
                            if attr == "href":
                                self._current_href = val

                def handle_data(self, data: str) -> None:
                    if self._in_a:
                        self._current_data.append(data)

                def handle_endtag(self, tag: str) -> None:
                    if tag == "a" and self._in_a:
                        text = "".join(self._current_data).strip()
                        if text and self._current_href:
                            self.links.append({
                                "text": text,
                                "href": self._current_href,
                            })
                        self._in_a = False
                        self._current_href = ""

            parser = FileParser()
            try:
                parser.feed(resp.text)
            except Exception:
                logger.warning("fjc_idb.parse_error")
                return []

            for link in parser.links:
                text = link["text"]
                href = link["href"]
                if not href.startswith("http"):
                    href = f"{_FJC_IDB_URL}/{href}" if href.startswith("/") else f"{_FJC_IDB_URL}/{href}"

                combined = text.lower()
                if not any(t.lower() in combined for t in terms):
                    continue

                # Only include links that look like data files
                if not any(ext in href.lower() for ext in (".csv", ".zip", ".xls", ".xlsx", ".txt")):
                    continue

                title = f"FJC IDB: {text}"
                published_at = datetime.now(tz=timezone.utc)

                if watermark and watermark.last_record_date:
                    if published_at <= watermark.last_record_date:
                        continue

                records.append(
                    NormalizedRecord(
                        title=title,
                        summary=f"FJC Integrated Database dataset: {text}",
                        record_type=RecordType.RESEARCH,
                        source_connector_id=self.connector_id,
                        source_label=self.source_label,
                        source_url=href,
                        citation_url=_FJC_IDB_URL,
                        published_at=published_at,
                        fingerprint=generate_fingerprint(
                            self.connector_id, href, title, published_at
                        ),
                        metadata={
                            "dataset_name": text,
                            "query_terms_matched": [
                                t for t in terms if t.lower() in combined
                            ],
                        },
                        raw_payload={"title": text, "url": href},
                    )
                )

                if len(records) >= query.max_records:
                    break

        logger.info("fjc_idb.fetched", count=len(records))
        return records

    async def health_check(self) -> HealthStatus:
        async with create_http_client(timeout=30.0) as client:
            try:
                resp = await client.get(_FJC_IDB_URL, follow_redirects=True)
                if resp.status_code < 500:
                    return HealthStatus.HEALTHY
                return HealthStatus.DEGRADED
            except Exception:
                return HealthStatus.FAILED
