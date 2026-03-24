from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import structlog

from lexgenius_pipeline.common.date_utils import parse_date
from lexgenius_pipeline.common.errors import ConnectorError
from lexgenius_pipeline.common.http_client import create_http_client
from lexgenius_pipeline.common.models import IngestionQuery, NormalizedRecord, Watermark
from lexgenius_pipeline.common.rate_limiter import AsyncRateLimiter
from lexgenius_pipeline.common.types import HealthStatus, RecordType, SourceTier
from lexgenius_pipeline.ingestion.base import BaseConnector
from lexgenius_pipeline.ingestion.normalize import generate_fingerprint
from lexgenius_pipeline.settings import Settings, get_settings

logger = structlog.get_logger(__name__)

_ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
_ESUMMARY_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"


def parse_date(value: str) -> datetime:
    for fmt in ("%Y %b %d", "%Y %b", "%Y"):
        try:
            return datetime.strptime(value.strip(), fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return datetime.now(tz=timezone.utc)


class PubMedConnector(BaseConnector):
    connector_id = "federal.nih.pubmed"
    source_tier = SourceTier.FEDERAL
    source_label = "NIH PubMed"
    supports_incremental = True

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._rate_limiter = AsyncRateLimiter(rate=3.0, burst=3)

    async def fetch_latest(
        self,
        query: IngestionQuery,
        watermark: Watermark | None = None,
    ) -> list[NormalizedRecord]:
        terms = query.query_terms or []
        if not terms:
            logger.warning("pubmed.no_query_terms")
            return []

        search_term = " OR ".join(f"{t}[Title/Abstract]" for t in terms)

        api_key = self._settings.pubmed_api_key
        async with create_http_client() as client:
            await self._rate_limiter.acquire()
            try:
                search_params: dict[str, str | int] = {
                    "db": "pubmed",
                    "retmode": "json",
                    "term": search_term,
                    "retmax": 20,
                    "sort": "date",
                }
                if api_key:
                    search_params["api_key"] = api_key
                resp = await client.get(_ESEARCH_URL, params=search_params)
                resp.raise_for_status()
            except Exception as exc:
                raise ConnectorError(str(exc), self.connector_id) from exc

            pmids: list[str] = resp.json().get("esearchresult", {}).get("idlist", [])
            if not pmids:
                return []

            await self._rate_limiter.acquire()
            try:
                summary_params: dict[str, str] = {
                    "db": "pubmed",
                    "retmode": "json",
                    "id": ",".join(pmids),
                }
                if api_key:
                    summary_params["api_key"] = api_key
                resp2 = await client.get(_ESUMMARY_URL, params=summary_params)
                resp2.raise_for_status()
            except Exception as exc:
                raise ConnectorError(str(exc), self.connector_id) from exc

        result_data: dict[str, Any] = resp2.json().get("result", {})
        records: list[NormalizedRecord] = []

        for pmid in pmids:
            article = result_data.get(pmid)
            if not article:
                continue

            title: str = article.get("title", "").strip() or f"PubMed:{pmid}"
            journal: str = article.get("fulljournalname", "")
            author: str = article.get("lastauthor", "")
            date_str: str = article.get("epubdate") or article.get("pubdate", "")
            published_at = parse_date(date_str) if date_str else datetime.now(tz=timezone.utc)
            source_url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"

            summary_parts = []
            if journal:
                summary_parts.append(f"Journal: {journal}")
            if author:
                summary_parts.append(f"Last author: {author}")
            summary = "; ".join(summary_parts) or title

            records.append(
                NormalizedRecord(
                    title=title,
                    summary=summary,
                    record_type=RecordType.RESEARCH,
                    source_connector_id=self.connector_id,
                    source_label=self.source_label,
                    source_url=source_url,
                    published_at=published_at,
                    fingerprint=generate_fingerprint(
                        self.connector_id, source_url, title, published_at
                    ),
                    metadata={
                        "pmid": pmid,
                        "journal": journal,
                        "last_author": author,
                    },
                    raw_payload=article,
                )
            )

        logger.info("pubmed.fetched", count=len(records))
        return records

    async def health_check(self) -> HealthStatus:
        async with create_http_client() as client:
            try:
                resp = await client.get(
                    _ESEARCH_URL,
                    params={"db": "pubmed", "retmode": "json", "term": "health", "retmax": 1},
                )
                resp.raise_for_status()
                return HealthStatus.HEALTHY
            except Exception:
                return HealthStatus.FAILED
