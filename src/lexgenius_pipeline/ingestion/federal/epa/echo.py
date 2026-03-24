"""EPA ECHO (Enforcement & Compliance History Online) connector.

Fetches facility-level compliance data, inspections, and enforcement
actions from the EPA ECHO REST API. Critical for environmental torts.
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

_BASE_URL = "https://echo.epa.gov/dataset/rpc"


class EPAECHOConnector(BaseConnector):
    """EPA ECHO facility compliance and enforcement data via REST API.

    Queries the ECHO API for facility compliance status, inspections,
    violations, and enforcement actions relevant to environmental torts.
    """

    connector_id = "federal.epa.echo"
    source_tier = SourceTier.FEDERAL
    source_label = "EPA ECHO Compliance Data"
    supports_incremental = True

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._rate_limiter = AsyncRateLimiter(rate=3.0, burst=5)

    async def fetch_latest(
        self,
        query: IngestionQuery,
        watermark: Watermark | None = None,
    ) -> list[NormalizedRecord]:
        terms = query.query_terms or []
        if not terms:
            logger.warning("epa_echo.no_query_terms")
            return []

        records: list[NormalizedRecord] = []

        async with create_http_client(timeout=30.0) as client:
            for term in terms:
                await self._rate_limiter.acquire()
                try:
                    # Use ECHO's JSON API endpoint for facility search
                    resp = await client.get(
                        "https://enviro.epa.gov/enviro/efservice/ECHO_FACILITY/facility_name/CONTAINING/"
                        f"{term}/json",
                    )
                    resp.raise_for_status()
                except Exception as exc:
                    logger.warning("federal_epa_echo.fetch_error", term=term, exc_info=True)
                    continue

                if resp.status_code != 200:
                    raise ConnectorError(
                        f"EPA ECHO returned HTTP {resp.status_code}",
                        connector_id=self.connector_id,
                    )

                data = resp.json()
                facilities = (
                    data
                    if isinstance(data, list)
                    else data.get("Results", [])
                    if isinstance(data, dict)
                    else []
                )

                for fac in facilities:
                    if not isinstance(fac, dict):
                        continue

                    fac_name = fac.get("FACILITY_NAME", fac.get("FacilityName", ""))
                    fac_id = fac.get("FACILITY_ID", fac.get("FacilityID", ""))
                    fac_addr = fac.get("FACILITY_ADDR", fac.get("FacilityStreet", ""))
                    fac_city = fac.get("FACILITY_CITY", fac.get("FacilityCity", ""))
                    fac_state = fac.get("FACILITY_STATE", fac.get("FacilityState", ""))
                    compliance_status = fac.get("COMPLIANCE_STATUS", fac.get("ComplianceStatus", ""))
                    tri_flag = fac.get("TRI_FLAG", fac.get("TRIReporter", ""))
                    date_str = fac.get("FAC_DERIVED_HA_CTY_DATE", "")

                    if not fac_name:
                        continue

                    published_at = parse_date(date_str)

                    if watermark and watermark.last_record_date:
                        if published_at <= watermark.last_record_date:
                            continue

                    title = f"EPA ECHO: {fac_name}"
                    summary_parts = [
                        f"Facility: {fac_name}",
                        f"Location: {fac_addr}, {fac_city}, {fac_state}"
                        if fac_city and fac_state
                        else f"Location: {fac_addr}",
                    ]
                    if compliance_status:
                        summary_parts.append(f"Compliance status: {compliance_status}")
                    if tri_flag:
                        summary_parts.append("TRI reporter: Yes")
                    summary = "; ".join(summary_parts)

                    source_url = (
                        f"https://echo.epa.gov/detailed-facility-report/{fac_id}"
                        if fac_id
                        else "https://echo.epa.gov"
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
                                "facility_id": fac_id,
                                "facility_name": fac_name,
                                "compliance_status": compliance_status,
                                "state": fac_state,
                                "city": fac_city,
                                "tri_reporter": tri_flag,
                                "query_term": term,
                            },
                            raw_payload=fac,
                        )
                    )

                if len(records) >= query.max_records:
                    break

        logger.info("epa_echo.fetched", count=len(records))
        return records

    async def health_check(self) -> HealthStatus:
        async with create_http_client(timeout=30.0) as client:
            try:
                resp = await client.get(
                    "https://enviro.epa.gov/enviro/efservice/ECHO_FACILITY/rows/0:0/json",
                    follow_redirects=True,
                )
                if resp.status_code < 500:
                    return HealthStatus.HEALTHY
                return HealthStatus.DEGRADED
            except Exception:
                return HealthStatus.FAILED
