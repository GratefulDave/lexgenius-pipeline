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

_SEARCH_URL = "https://efts.sec.gov/LATEST/search-index"
_FILING_FORMS = "10-K,10-Q,8-K"


def _parse_sec_date(date_str: str) -> datetime:
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(date_str[:10], fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    raise ValueError(f"Unrecognised SEC date: {date_str!r}")


class SECEdgarConnector(BaseConnector):
    """SEC EDGAR company filings connector (10-K, 10-Q, 8-K)."""

    connector_id = "federal.sec.edgar"
    source_tier = SourceTier.FEDERAL
    source_label = "SEC EDGAR"
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
            logger.warning("sec.edgar.no_query_terms")
            return []

        records: list[NormalizedRecord] = []

        for term in terms:
            params: dict[str, str] = {
                "q": term,
                "forms": _FILING_FORMS,
            }
            if query.date_from:
                params["dateRange"] = "custom"
                params["startdt"] = query.date_from.strftime("%Y-%m-%d")
            if query.date_to:
                params["enddt"] = query.date_to.strftime("%Y-%m-%d")

            await self._limiter.acquire()
            try:
                resp = await self._client.get(_SEARCH_URL, params=params)
            except Exception as exc:
                raise ConnectorError(str(exc), self.connector_id) from exc

            if resp.status_code == 429:
                raise RateLimitError("Rate limit exceeded", self.connector_id)
            if resp.status_code >= 500:
                raise ConnectorError(f"Server error {resp.status_code}", self.connector_id)
            resp.raise_for_status()

            data = resp.json()
            hits = data.get("hits", {}).get("hits", [])

            for hit in hits:
                src = hit.get("_source", {})
                file_date = src.get("file_date", "")
                if not file_date:
                    continue
                try:
                    published_at = _parse_sec_date(file_date)
                except ValueError:
                    logger.warning("sec.edgar.bad_date", date=file_date)
                    continue

                if watermark and watermark.last_record_date:
                    if published_at <= watermark.last_record_date:
                        continue

                form_type = src.get("form_type", "")
                company = src.get("entity_name", "") or src.get("display_names", [""])[0]
                accession = hit.get("_id", "").replace("-", "")

                source_url = (
                    f"https://www.sec.gov/cgi-bin/browse-edgar"
                    f"?action=getcompany&company={term}"
                )
                filing_url = (
                    f"https://www.sec.gov/Archives/edgar/data/{accession}"
                    if accession
                    else source_url
                )
                title = f"SEC {form_type}: {company}"
                summary = f"{form_type} filing by {company} on {file_date}"

                records.append(
                    NormalizedRecord(
                        title=title,
                        summary=summary,
                        record_type=RecordType.FILING,
                        source_connector_id=self.connector_id,
                        source_label=self.source_label,
                        source_url=source_url,
                        citation_url=filing_url,
                        published_at=published_at,
                        fingerprint=generate_fingerprint(
                            self.connector_id, filing_url, title, published_at
                        ),
                        metadata={
                            "form_type": form_type,
                            "company": company,
                            "file_date": file_date,
                            "accession_number": hit.get("_id", ""),
                            "query_term": term,
                        },
                        raw_payload=src,
                    )
                )

        logger.info("sec.edgar.fetched", count=len(records))
        return records

    async def health_check(self) -> HealthStatus:
        try:
            resp = await self._client.get(_SEARCH_URL, params={"q": "apple", "forms": "10-K"})
            if resp.status_code < 500:
                return HealthStatus.HEALTHY
            return HealthStatus.DEGRADED
        except Exception:
            return HealthStatus.FAILED
