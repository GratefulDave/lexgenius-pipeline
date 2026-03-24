"""EPA TRI (Toxics Release Inventory) connector.

Downloads and parses EPA TRI data for facility-level toxic release
quantities. Foundation for environmental exposure tort analysis.
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

# EPA TRI basic data files (CSV) — we use the latest available year
_TRI_DATA_URL = "https://www.epa.gov/toxics-release-inventory-tri-program/tri-basic-data-files-calendar-years-1987-2023"


def _parse_date(value: str | None) -> datetime:
    if not value:
        return datetime.now(tz=timezone.utc)
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y%m%d"):
        try:
            return datetime.strptime(value.strip()[:10], fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return datetime.now(tz=timezone.utc)


class EPATRIConnector(BaseConnector):
    """EPA TRI (Toxics Release Inventory) bulk data connector.

    Downloads TRI data files and parses them for facility-level
    toxic release quantities by chemical. Supports filtering by
    chemical name or facility.
    """

    connector_id = "federal.epa.tri"
    source_tier = SourceTier.FEDERAL
    source_label = "EPA TRI Toxics Release Inventory"
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
            logger.warning("epa_tri.no_query_terms")
            return []

        records: list[NormalizedRecord] = []

        # Use the EPA Envirofacts TRI REST API for targeted queries
        async with create_http_client(timeout=60.0) as client:
            for term in terms:
                await self._rate_limiter.acquire()
                try:
                    resp = await client.get(
                        "https://data.epa.gov/efservice/TRI_RELEASE_FACILITY/"
                        f"CHEMICAL_NAME/CONTAINING/{term}/json",
                    )
                    resp.raise_for_status()
                except Exception as exc:
                    logger.warning("federal_epa_tri.fetch_error", term=term, exc_info=True)
                    continue

                data = resp.json()
                releases = data if isinstance(data, list) else data.get("Results", [])
                if not isinstance(releases, list):
                    releases = []

                for release in releases:
                    if not isinstance(release, dict):
                        continue

                    fac_name = release.get("FACILITY_NAME", "")
                    chemical = release.get("CHEMICAL_NAME", "")
                    release_type = release.get("RELEASE_TYPE", "")
                    year = release.get("REPORTING_YEAR", "")
                    total_qty = release.get("TOTAL_RELEASES", "0")
                    air_qty = release.get("AIR_RELEASES", "0")
                    water_qty = release.get("WATER_RELEASES", "0")
                    land_qty = release.get("LAND_RELEASES", "0")
                    fac_city = release.get("CITY_NAME", "")
                    fac_state = release.get("STATE_ABBR", "")
                    tri_facility_id = release.get("TRI_FACILITY_ID", "")

                    published_at = _parse_date(year) if year else datetime.now(tz=timezone.utc)

                    if watermark and watermark.last_record_date:
                        if published_at <= watermark.last_record_date:
                            continue

                    title = f"EPA TRI: {chemical} — {fac_name}"
                    summary_parts = [
                        f"Chemical: {chemical}",
                        f"Facility: {fac_name}",
                        f"Year: {year}" if year else "",
                        f"Total releases: {total_qty}" if total_qty else "",
                        f"Air: {air_qty}" if air_qty and float(str(air_qty)) > 0 else "",
                        f"Water: {water_qty}" if water_qty and float(str(water_qty)) > 0 else "",
                        f"Land: {land_qty}" if land_qty and float(str(land_qty)) > 0 else "",
                    ]
                    if fac_city and fac_state:
                        summary_parts.append(f"Location: {fac_city}, {fac_state}")
                    summary = "; ".join(p for p in summary_parts if p)

                    source_url = (
                        f"https://echo.epa.gov/detailed-facility-report/{tri_facility_id}"
                        if tri_facility_id
                        else "https://www.epa.gov/toxics-release-inventory-tri-program"
                    )

                    records.append(
                        NormalizedRecord(
                            title=title,
                            summary=summary[:500],
                            record_type=RecordType.RESEARCH,
                            source_connector_id=self.connector_id,
                            source_label=self.source_label,
                            source_url=source_url,
                            published_at=published_at,
                            fingerprint=generate_fingerprint(
                                self.connector_id, source_url, title, published_at
                            ),
                            metadata={
                                "tri_facility_id": tri_facility_id,
                                "chemical_name": chemical,
                                "reporting_year": year,
                                "total_releases": str(total_qty),
                                "air_releases": str(air_qty),
                                "water_releases": str(water_qty),
                                "land_releases": str(land_qty),
                                "state": fac_state,
                                "city": fac_city,
                            },
                            raw_payload=release,
                        )
                    )

                if len(records) >= query.max_records:
                    break

        logger.info("epa_tri.fetched", count=len(records))
        return records

    async def health_check(self) -> HealthStatus:
        async with create_http_client(timeout=30.0) as client:
            try:
                resp = await client.get(
                    "https://www.epa.gov/toxics-release-inventory-tri-program",
                    follow_redirects=True,
                )
                if resp.status_code < 500:
                    return HealthStatus.HEALTHY
                return HealthStatus.DEGRADED
            except Exception:
                return HealthStatus.FAILED
