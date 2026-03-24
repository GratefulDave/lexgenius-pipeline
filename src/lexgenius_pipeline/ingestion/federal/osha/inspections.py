"""OSHA inspection and citation data connector.

Fetches inspection and citation data from the OSHA Establishment Search API.
Relevant for workplace exposure and toxic tort cases.
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

_BASE_URL = "https://www.osha.gov/ords/imis/establishment"



class OSHAInspectionsConnector(BaseConnector):
    """OSHA inspection and citation data via REST API.

    Queries OSHA's public data API for inspection records, citations,
    and penalties. Supports search by employer name or establishment.
    """

    connector_id = "federal.osha.inspections"
    source_tier = SourceTier.FEDERAL
    source_label = "OSHA Inspections & Citations"
    supports_incremental = True

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._rate_limiter = AsyncRateLimiter(rate=5.0, burst=5)

    async def fetch_latest(
        self,
        query: IngestionQuery,
        watermark: Watermark | None = None,
    ) -> list[NormalizedRecord]:
        terms = query.query_terms or []
        if not terms:
            logger.warning("osha_inspections.no_query_terms")
            return []

        records: list[NormalizedRecord] = []

        async with create_http_client() as client:
            for term in terms:
                await self._rate_limiter.acquire()
                try:
                    resp = await client.get(
                        _BASE_URL,
                        params={
                            "establishment_name": term,
                            "data_type": "establishment",
                            "format": "json",
                        },
                    )
                    resp.raise_for_status()
                except Exception as exc:
                    logger.warning("federal_osha_inspections.fetch_error", term=term, exc_info=True)
                    continue

                data = resp.json()
                establishments = data if isinstance(data, list) else data.get("data", [])

                for est in establishments:
                    if not isinstance(est, dict):
                        continue

                    est_name = est.get("establishment_name", "")
                    insp_type = est.get("inspection_type", "")
                    open_date = est.get("open_date", "")
                    close_date = est.get("close_date", "")
                    violations = est.get("violations", "0")
                    penalty = est.get("current_penalty", "0")
                    state = est.get("state", "")
                    city = est.get("city", "")
                    industry = est.get("sic_code", "")

                    published_at = parse_date(open_date)

                    if watermark and watermark.last_record_date:
                        if published_at <= watermark.last_record_date:
                            continue

                    title = f"OSHA Inspection: {est_name or term}"
                    if insp_type:
                        title += f" ({insp_type})"

                    summary_parts = []
                    if insp_type:
                        summary_parts.append(f"Inspection type: {insp_type}")
                    if violations and int(str(violations)) > 0:
                        summary_parts.append(f"Violations: {violations}")
                    if penalty and float(str(penalty)) > 0:
                        summary_parts.append(f"Penalty: ${penalty}")
                    if city and state:
                        summary_parts.append(f"Location: {city}, {state}")
                    summary = "; ".join(summary_parts) or title

                    inspection_id = est.get("inspection_number", "")
                    source_url = (
                        f"https://www.osha.gov/ords/imis/establishment.inspection_detail"
                        f"?id={inspection_id}"
                        if inspection_id
                        else "https://www.osha.gov/ogate/open-government-data"
                    )

                    records.append(
                        NormalizedRecord(
                            title=title,
                            summary=summary[:500],
                            record_type=RecordType.ENFORCEMENT,
                            source_connector_id=self.connector_id,
                            source_label=self.source_label,
                            source_url=source_url,
                            published_at=published_at,
                            fingerprint=generate_fingerprint(
                                self.connector_id, source_url, title, published_at
                            ),
                            metadata={
                                "inspection_number": inspection_id,
                                "establishment_name": est_name,
                                "inspection_type": insp_type,
                                "violations": str(violations),
                                "penalty": str(penalty),
                                "state": state,
                                "city": city,
                                "sic_code": industry,
                            },
                            raw_payload=est,
                        )
                    )

                    if len(records) >= query.max_records:
                        break

                if len(records) >= query.max_records:
                    break

        logger.info("osha_inspections.fetched", count=len(records))
        return records

    async def health_check(self) -> HealthStatus:
        async with create_http_client() as client:
            try:
                resp = await client.get(
                    _BASE_URL,
                    params={"data_type": "establishment", "format": "json"},
                )
                if resp.status_code < 500:
                    return HealthStatus.HEALTHY
                return HealthStatus.DEGRADED
            except Exception:
                return HealthStatus.FAILED
