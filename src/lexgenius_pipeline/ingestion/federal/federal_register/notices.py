from __future__ import annotations

from datetime import datetime, timezone

import structlog

from lexgenius_pipeline.common.errors import ConnectorError, RateLimitError
from lexgenius_pipeline.common.http_client import create_http_client
from lexgenius_pipeline.common.models import IngestionQuery, NormalizedRecord, Watermark
from lexgenius_pipeline.common.rate_limiter import AsyncRateLimiter
from lexgenius_pipeline.common.types import HealthStatus, RecordType, SourceTier
from lexgenius_pipeline.ingestion.base import BaseConnector
from lexgenius_pipeline.ingestion.normalize import generate_fingerprint
from lexgenius_pipeline.settings import Settings, get_settings

logger = structlog.get_logger(__name__)

_BASE_URL = "https://www.federalregister.gov/api/v1/documents.json"


def _parse_fr_date(date_str: str) -> datetime:
    if not date_str:
        raise ValueError("Empty date string")
    for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(date_str[:10], fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    raise ValueError(f"Unrecognised Federal Register date: {date_str!r}")


class FederalRegisterConnector(BaseConnector):
    """Federal Register documents connector. No auth required."""

    connector_id = "federal.federal_register.notices"
    source_tier = SourceTier.FEDERAL
    source_label = "Federal Register"
    supports_incremental = True

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._client = create_http_client()
        self._limiter = AsyncRateLimiter(rate=10.0)

    async def fetch_latest(
        self,
        query: IngestionQuery,
        watermark: Watermark | None = None,
    ) -> list[NormalizedRecord]:
        terms = query.query_terms or []
        if not terms:
            logger.warning("federal_register.no_query_terms")
            return []

        records: list[NormalizedRecord] = []

        for term in terms:
            params: dict[str, str | int] = {
                "per_page": 10,
                "order": "newest",
                "conditions[term]": term,
            }
            await self._limiter.acquire()
            try:
                resp = await self._client.get(_BASE_URL, params=params)
            except Exception as exc:
                raise ConnectorError(str(exc), self.connector_id) from exc

            if resp.status_code == 429:
                raise RateLimitError("Rate limit exceeded", self.connector_id)
            if resp.status_code >= 500:
                raise ConnectorError(f"Server error {resp.status_code}", self.connector_id)
            resp.raise_for_status()

            data = resp.json()
            results = data.get("results", [])

            for item in results:
                title = item.get("title", "")
                abstract = item.get("abstract", "") or title
                html_url = item.get("html_url", "")
                doc_type = item.get("type", "")
                pub_date = item.get("publication_date", "")
                doc_number = item.get("document_number", "")
                agencies = item.get("agencies", [])
                agency_names = [a.get("name", "") for a in agencies if a.get("name")]

                if not pub_date:
                    continue
                try:
                    published_at = _parse_fr_date(pub_date)
                except ValueError:
                    logger.warning("federal_register.bad_date", date=pub_date)
                    continue

                if watermark and watermark.last_record_date:
                    if published_at <= watermark.last_record_date:
                        continue

                source_url = html_url or f"https://www.federalregister.gov/d/{doc_number}"

                records.append(
                    NormalizedRecord(
                        title=title,
                        summary=abstract[:500],
                        record_type=RecordType.REGULATION,
                        source_connector_id=self.connector_id,
                        source_label=self.source_label,
                        source_url=source_url,
                        published_at=published_at,
                        fingerprint=generate_fingerprint(
                            self.connector_id, source_url, title, published_at
                        ),
                        metadata={
                            "document_number": doc_number,
                            "doc_type": doc_type,
                            "agencies": agency_names,
                            "query_term": term,
                        },
                        raw_payload=item,
                    )
                )

        logger.info("federal_register.fetched", count=len(records))
        return records

    async def health_check(self) -> HealthStatus:
        try:
            resp = await self._client.get(
                _BASE_URL, params={"per_page": 1, "conditions[term]": "regulation"}
            )
            if resp.status_code < 500:
                return HealthStatus.HEALTHY
            return HealthStatus.DEGRADED
        except Exception:
            return HealthStatus.FAILED
