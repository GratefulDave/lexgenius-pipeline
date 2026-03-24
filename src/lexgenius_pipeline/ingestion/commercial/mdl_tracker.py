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

_BASE_URL = "https://multidistrictlitigation.com"
_CASE_COUNT_RE = re.compile(r"(\d[\d,]+)\s*(?:cases?|actions?|plaintiffs?)", re.IGNORECASE)
_MDL_NUMBER_RE = re.compile(r"MDL[- ]?(?:No\.?\s*)?(\d+)", re.IGNORECASE)


def _parse_iso_date(date_str: str) -> datetime:
    try:
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc).replace(tzinfo=timezone.utc)
    except Exception:
        logger.warning("mdl_tracker.unparseable_date", date_str=date_str)
        return datetime.now(tz=timezone.utc)


class MDLTrackerConnector(BaseConnector):
    """MultiDistrictLitigation.com MDL listings scraper."""

    connector_id = "commercial.mdl_tracker"
    source_tier = SourceTier.COMMERCIAL
    source_label = "MDL Tracker"
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

            soup = BeautifulSoup(resp.text, "html.parser")
            terms_lower = [t.lower() for t in (query.query_terms or [])]

            for heading in soup.find_all(["h2", "h3", "h4"]):
                link_el = heading.find("a", href=True)
                if not link_el:
                    continue

                title = link_el.get_text(strip=True)
                link = link_el["href"]
                if not link.startswith("http"):
                    link = f"{_BASE_URL}{link}"

                if not title or not link:
                    continue

                if terms_lower:
                    if not any(term in title.lower() for term in terms_lower):
                        continue

                # Find date from next sibling context
                time_el = heading.find_next("time", attrs={"datetime": True})

                published_at = (
                    _parse_iso_date(time_el["datetime"])
                    if time_el
                    else datetime.now(tz=timezone.utc)
                )
                if watermark and watermark.last_record_date:
                    if published_at <= watermark.last_record_date:
                        continue

                # Find excerpt from next sibling div
                excerpt_el = heading.find_next(
                    "div",
                    class_=re.compile(r"entry-content|excerpt|summary"),
                )
                excerpt_text = excerpt_el.get_text(strip=True) if excerpt_el else ""
                summary = excerpt_text[:500] if excerpt_text else title

                # Extract MDL metadata
                mdl_match = _MDL_NUMBER_RE.search(f"{title} {excerpt_text}")
                case_count_match = _CASE_COUNT_RE.search(excerpt_text) if excerpt_text else None

                metadata: dict[str, str] = {"category": "mdl_listing"}
                if mdl_match:
                    metadata["mdl_number"] = mdl_match.group(1)
                if case_count_match:
                    metadata["case_count"] = case_count_match.group(1)

                records.append(
                    NormalizedRecord(
                        title=title,
                        summary=summary,
                        record_type=RecordType.FILING,
                        source_connector_id=self.connector_id,
                        source_label=self.source_label,
                        source_url=link,
                        published_at=published_at,
                        fingerprint=generate_fingerprint(
                            self.connector_id, link, title, published_at
                        ),
                        metadata=metadata,
                        raw_payload={"title": title, "link": link},
                    )
                )

        logger.info("mdl_tracker.fetched", count=len(records))
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
