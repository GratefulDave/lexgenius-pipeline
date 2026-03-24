"""FDA Orange Book connector.

Downloads and parses the FDA Orange Book (Approved Drug Products with
Therapeutic Equivalence Evaluations). Provides patent/exclusivity data
for pharmaceutical mass tort analysis.
"""
from __future__ import annotations

from datetime import datetime, timezone
from io import StringIO

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

_DOWNLOAD_URL = "https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds/orange-book"



class FDAOrangeBookConnector(BaseConnector):
    """FDA Orange Book — Approved Drug Products with Therapeutic Equivalence.

    Downloads the Orange Book data and parses it for drug approval
    information, patent listings, and exclusivity data.
    """

    connector_id = "federal.fda.orange_book"
    source_tier = SourceTier.FEDERAL
    source_label = "FDA Orange Book"
    supports_incremental = True

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._rate_limiter = AsyncRateLimiter(rate=1.0, burst=2)

    async def fetch_latest(
        self,
        query: IngestionQuery,
        watermark: Watermark | None = None,
    ) -> list[NormalizedRecord]:
        terms = query.query_terms or []
        if not terms:
            logger.warning("fda_orange_book.no_query_terms")
            return []

        records: list[NormalizedRecord] = []

        async with create_http_client(timeout=60.0) as client:
            await self._rate_limiter.acquire()
            try:
                # FDA provides the Orange Book in multiple formats.
                # We fetch the products.txt file.
                resp = await client.get(
                    "https://www.fda.gov/media/88755/download",
                    follow_redirects=True,
                )
                resp.raise_for_status()
            except Exception:
                logger.warning("fda_orange_book.fetch_error", exc_info=True)
                return []

            if not resp.text.strip():
                logger.warning("fda_orange_book.empty_response")
                return []

            # Parse the tab-delimited Orange Book data
            lines = resp.text.strip().split("\n")
            if len(lines) < 2:
                return []

            for line in lines[1:]:
                fields = line.split("\t")
                if len(fields) < 8:
                    continue

                ingredient = fields[0].strip()
                strength = fields[2].strip()
                dosage_form = fields[3].strip()
                route = fields[4].strip()
                trade_name = fields[5].strip()
                applicant = fields[6].strip()
                approval_date = fields[7].strip()
                product_number = fields[1].strip()

                combined = f"{ingredient} {trade_name} {applicant}".lower()
                if not any(t.lower() in combined for t in terms):
                    continue

                published_at = parse_date(approval_date)

                if watermark and watermark.last_record_date:
                    if published_at <= watermark.last_record_date:
                        continue

                title = f"Orange Book: {trade_name or ingredient} ({strength})"
                summary_parts = [
                    f"Ingredient: {ingredient}",
                    f"Strength: {strength}" if strength else "",
                    f"Dosage form: {dosage_form}" if dosage_form else "",
                    f"Route: {route}" if route else "",
                    f"Applicant: {applicant}",
                    f"Approval date: {approval_date}" if approval_date else "",
                ]
                summary = "; ".join(p for p in summary_parts if p)

                source_url = (
                    f"https://www.accessdata.fda.gov/scripts/cder/ob/"
                    f"docs/patexcl_new.cfm?Appl_No={product_number}"
                    if product_number
                    else "https://www.accessdata.fda.gov/scripts/cder/ob/"
                )

                records.append(
                    NormalizedRecord(
                        title=title,
                        summary=summary[:500],
                        record_type=RecordType.REGULATION,
                        source_connector_id=self.connector_id,
                        source_label=self.source_label,
                        source_url=source_url,
                        published_at=published_at,
                        fingerprint=generate_fingerprint(
                            self.connector_id, source_url, title, published_at
                        ),
                        metadata={
                            "ingredient": ingredient,
                            "strength": strength,
                            "dosage_form": dosage_form,
                            "route": route,
                            "trade_name": trade_name,
                            "applicant": applicant,
                            "approval_date": approval_date,
                            "product_number": product_number,
                        },
                        raw_payload={
                            "ingredient": ingredient,
                            "strength": strength,
                            "dosage_form": dosage_form,
                            "route": route,
                            "trade_name": trade_name,
                            "applicant": applicant,
                            "approval_date": approval_date,
                            "product_number": product_number,
                        },
                    )
                )

                if len(records) >= query.max_records:
                    break

        logger.info("fda_orange_book.fetched", count=len(records))
        return records

    async def health_check(self) -> HealthStatus:
        async with create_http_client(timeout=60.0) as client:
            try:
                resp = await client.get(
                    "https://www.accessdata.fda.gov/scripts/cder/ob/",
                    follow_redirects=True,
                )
                if resp.status_code < 500:
                    return HealthStatus.HEALTHY
                return HealthStatus.DEGRADED
            except Exception:
                return HealthStatus.FAILED
