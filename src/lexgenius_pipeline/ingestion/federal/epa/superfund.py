"""EPA Superfund / National Priorities List connector.

Fetches Superfund site data from the EPA Envirofacts REST API.
Superfund sites are a key signal for environmental mass torts.
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


def _parse_date(value: str | None) -> datetime:
    if not value:
        return datetime.now(tz=timezone.utc)
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y%m%d"):
        try:
            return datetime.strptime(value.strip()[:10], fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return datetime.now(tz=timezone.utc)


class EPASuperfundConnector(BaseConnector):
    """EPA Superfund / National Priorities List data connector.

    Fetches NPL (National Priorities List) site data from EPA
    Envirofacts REST API. These sites represent the most serious
    contaminated sites and are key signals for environmental torts.
    """

    connector_id = "federal.epa.superfund"
    source_tier = SourceTier.FEDERAL
    source_label = "EPA Superfund / NPL Sites"
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
            logger.warning("epa_superfund.no_query_terms")
            return []

        records: list[NormalizedRecord] = []

        async with create_http_client(timeout=30.0) as client:
            for term in terms:
                await self._rate_limiter.acquire()
                try:
                    resp = await client.get(
                        "https://enviro.epa.gov/enviro/efservice/NPL/SITE_NAME/CONTAINING/"
                        f"{term}/json",
                    )
                    resp.raise_for_status()
                except Exception as exc:
                    logger.warning("federal_epa_superfund.fetch_error", term=term, exc_info=True)
                    continue

                data = resp.json()
                sites = data if isinstance(data, list) else data.get("Results", [])
                if not isinstance(sites, list):
                    sites = []

                for site in sites:
                    if not isinstance(site, dict):
                        continue

                    site_name = site.get("SITE_NAME", site.get("SiteName", ""))
                    epa_id = site.get("SITE_ID", site.get("SiteID", ""))
                    city = site.get("SITE_CITY_NAME", site.get("City", ""))
                    state = site.get("SITE_STATE", site.get("State", ""))
                    npl_status = site.get("NPL_STATUS", site.get("NPLStatus", ""))
                    region = site.get("REGION", site.get("Region", ""))
                    zip_code = site.get("SITE_ZIP", site.get("ZipCode", ""))
                    final_date = site.get("DATE_FINAL_NPL", site.get("FinalNPLDate", ""))

                    if not site_name:
                        continue

                    published_at = _parse_date(final_date)

                    if watermark and watermark.last_record_date:
                        if published_at <= watermark.last_record_date:
                            continue

                    title = f"EPA Superfund Site: {site_name}"
                    summary_parts = [
                        f"Site: {site_name}",
                        f"EPA ID: {epa_id}" if epa_id else "",
                        f"Location: {city}, {state} {zip_code}" if city else "",
                        f"NPL status: {npl_status}" if npl_status else "",
                        f"Region: {region}" if region else "",
                    ]
                    if final_date:
                        summary_parts.append(f"Final NPL date: {final_date}")
                    summary = "; ".join(p for p in summary_parts if p)

                    source_url = (
                        f"https://www.epa.gov/superfund/national-priorities-list-npl-sites-state"
                        f"#{state}"
                        if state
                        else "https://www.epa.gov/superfund/national-priorities-list-npl-sites-state"
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
                                "epa_site_id": epa_id,
                                "site_name": site_name,
                                "city": city,
                                "state": state,
                                "zip": zip_code,
                                "npl_status": npl_status,
                                "region": region,
                                "final_npl_date": final_date,
                                "query_term": term,
                            },
                            raw_payload=site,
                        )
                    )

                if len(records) >= query.max_records:
                    break

        logger.info("epa_superfund.fetched", count=len(records))
        return records

    async def health_check(self) -> HealthStatus:
        async with create_http_client(timeout=30.0) as client:
            try:
                resp = await client.get(
                    "https://enviro.epa.gov/enviro/efservice/NPL/json",
                    params={"rows": "1"},
                )
                if resp.status_code < 500:
                    return HealthStatus.HEALTHY
                return HealthStatus.DEGRADED
            except Exception:
                return HealthStatus.FAILED
