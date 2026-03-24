"""CDC WONDER epidemiological data connector.

Fetches mortality and disease surveillance data from CDC WONDER API.
Provides ICD-10 coded mortality data, cancer incidence, and environmental
health indicators supporting toxic/pharmaceutical tort causation analysis.
"""
from __future__ import annotations

from datetime import datetime, timezone

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

_BASE_URL = "https://wonder.cdc.gov/controller/datarequest/D76"



class CDCWonderConnector(BaseConnector):
    """CDC WONDER mortality & epidemiological data connector.

    Queries CDC WONDER for mortality and disease surveillance data.
    Returns aggregated epidemiological records filtered by query terms
    matching cause-of-death or condition names.
    """

    connector_id = "federal.cdc.wonder"
    source_tier = SourceTier.FEDERAL
    source_label = "CDC WONDER Epidemiological Data"
    supports_incremental = True

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
            logger.warning("cdc_wonder.no_query_terms")
            return []

        records: list[NormalizedRecord] = []
        now = datetime.now(tz=timezone.utc)

        async with create_http_client(timeout=60.0) as client:
            for term in terms:
                await self._rate_limiter.acquire()
                try:
                    # CDC WONDER supports form-based data requests.
                    # We use the underlying API endpoint for mortality data.
                    params = {
                        "stage": "submit",
                        "request_type": "export",
                        "dataset_code": "D76",
                        "dataset_label": "Detailed Mortality",
                        "report_type": "grid",
                        "display_values": "both",
                        "show_zeros": "false",
                        "show_suppressed": "false",
                        "rows_per_page": 100,
                    }
                    resp = await client.post(_BASE_URL, data=params)
                    resp.raise_for_status()
                except Exception:
                    logger.warning(
                        "cdc_wonder.fetch_error", term=term, exc_info=True
                    )
                    continue

                if resp.status_code != 200 or not resp.text.strip():
                    continue

                # Parse the response — CDC WONDER returns tab-delimited data
                lines = resp.text.strip().split("\n")
                if len(lines) < 2:
                    continue

                headers = lines[0].split("\t")

                for line in lines[1:]:
                    fields = line.split("\t")
                    if len(fields) < 3:
                        continue

                    row: dict[str, str] = {}
                    for i, header in enumerate(headers):
                        if i < len(fields):
                            row[header.strip()] = fields[i].strip()

                    # Filter by query term match in cause-of-death or notes
                    cause = row.get("Cause of death", row.get("Underlying Cause of death", ""))
                    notes = row.get("Notes", "")
                    combined = f"{cause} {notes}".lower()

                    if term.lower() not in combined:
                        continue

                    year = row.get("Year", "")
                    deaths = row.get("Deaths", "0").replace(",", "")
                    population = row.get("Population", "0").replace(",", "")
                    crude_rate = row.get("Crude Rate", "")

                    title = f"CDC WONDER: {cause or 'Mortality Data'} ({year})"
                    summary_parts = [
                        f"Cause of death: {cause}" if cause else "",
                        f"Deaths: {deaths}",
                        f"Population: {population}",
                        f"Crude rate: {crude_rate}" if crude_rate else "",
                    ]
                    summary = "; ".join(p for p in summary_parts if p)
                    source_url = "https://wonder.cdc.gov/mortSQL.html"
                    published_at = parse_date(year)

                    if watermark and watermark.last_record_date:
                        if published_at <= watermark.last_record_date:
                            continue

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
                                "cause_of_death": cause,
                                "year": year,
                                "deaths": deaths,
                                "population": population,
                                "crude_rate": crude_rate,
                                "query_term": term,
                            },
                            raw_payload=row,
                        )
                    )

                    if len(records) >= query.max_records:
                        break

                if len(records) >= query.max_records:
                    break

        logger.info("cdc_wonder.fetched", count=len(records))
        return records

    async def health_check(self) -> HealthStatus:
        async with create_http_client(timeout=30.0) as client:
            try:
                resp = await client.get("https://wonder.cdc.gov/")
                if resp.status_code < 500:
                    return HealthStatus.HEALTHY
                return HealthStatus.DEGRADED
            except Exception:
                return HealthStatus.FAILED
