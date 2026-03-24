"""ATSDR (Agency for Toxic Substances and Disease Registry) connector.

Fetches health assessments and toxicological profiles from ATSDR.
Health assessments are key for establishing causation in toxic torts.
"""
from __future__ import annotations

from datetime import datetime, timezone

import structlog

from lexgenius_pipeline.common.date_utils import UNKNOWN_DATE, parse_date
from lexgenius_pipeline.common.errors import ConnectorError
from lexgenius_pipeline.common.html_utils import LinkExtractorParser
from lexgenius_pipeline.common.http_client import create_http_client
from lexgenius_pipeline.common.models import IngestionQuery, NormalizedRecord, Watermark
from lexgenius_pipeline.common.rate_limiter import AsyncRateLimiter
from lexgenius_pipeline.common.types import HealthStatus, RecordType, SourceTier
from lexgenius_pipeline.ingestion.base import BaseConnector
from lexgenius_pipeline.ingestion.normalize import generate_fingerprint
from lexgenius_pipeline.settings import Settings, get_settings

logger = structlog.get_logger(__name__)

_BASE_URL = "https://www.atsdr.cdc.gov"



class ATSDRHealthAssessmentsConnector(BaseConnector):
    """ATSDR health assessments and toxicological profiles.

    Fetches public health assessments and consultations from ATSDR.
    These documents establish exposure-health relationships critical
    for toxic tort causation arguments.
    """

    connector_id = "federal.atsdr.health_assessments"
    source_tier = SourceTier.FEDERAL
    source_label = "ATSDR Health Assessments"
    supports_incremental = False

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
            logger.warning("atsdr_health_assessments.no_query_terms")
            return []

        records: list[NormalizedRecord] = []

        async with create_http_client(timeout=30.0) as client:
            # Fetch the public health assessments listing page
            await self._rate_limiter.acquire()
            try:
                resp = await client.get(
                    "https://www.atsdr.cdc.gov/hac/pha/",
                    follow_redirects=True,
                )
                resp.raise_for_status()
            except Exception as exc:
                raise ConnectorError(
                    f"Failed to fetch from atsdr_health_assessments: {exc}",
                    connector_id=self.connector_id,
                ) from exc

            # Parse the HTML response for assessment links
            parser = LinkExtractorParser()
            try:
                parser.feed(resp.text)
            except Exception:
                logger.warning("atsdr_health_assessments.parse_error")
                return []

            for link in parser.links:
                text = link["text"]
                href = link["href"]
                if not href.startswith("http"):
                    href = f"{_BASE_URL}{href}" if href.startswith("/") else f"{_BASE_URL}/hac/pha/{href}"

                combined = text.lower()
                if not any(t.lower() in combined for t in terms):
                    continue

                title = f"ATSDR Health Assessment: {text}"
                published_at = UNKNOWN_DATE

                records.append(
                    NormalizedRecord(
                        title=title,
                        summary=f"ATSDR public health assessment: {text}",
                        record_type=RecordType.RESEARCH,
                        source_connector_id=self.connector_id,
                        source_label=self.source_label,
                        source_url=href,
                        citation_url=href,
                        published_at=published_at,
                        fingerprint=generate_fingerprint(
                            self.connector_id, href, title, published_at
                        ),
                        metadata={
                            "assessment_name": text,
                            "query_terms_matched": [
                                t for t in terms if t.lower() in combined
                            ],
                        },
                        raw_payload={"title": text, "url": href},
                    )
                )

                if len(records) >= query.max_records:
                    break

        logger.info("atsdr_health_assessments.fetched", count=len(records))
        return records

    async def health_check(self) -> HealthStatus:
        async with create_http_client(timeout=30.0) as client:
            try:
                resp = await client.get(
                    "https://www.atsdr.cdc.gov/",
                    follow_redirects=True,
                )
                if resp.status_code < 500:
                    return HealthStatus.HEALTHY
                return HealthStatus.DEGRADED
            except Exception:
                return HealthStatus.FAILED
