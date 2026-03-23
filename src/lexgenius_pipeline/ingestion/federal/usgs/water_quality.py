from __future__ import annotations

from datetime import datetime, timedelta, timezone

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

_BASE_URL = "https://waterservices.usgs.gov/nwis/dv/"
_DEFAULT_LOOKBACK_DAYS = 7


def _date_str(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d")


class USGSWaterQualityConnector(BaseConnector):
    """USGS daily water quality values connector. Query terms are site numbers."""

    connector_id = "federal.usgs.water_quality"
    source_tier = SourceTier.FEDERAL
    source_label = "USGS Water Quality"
    supports_incremental = True

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._client = create_http_client()
        self._limiter = AsyncRateLimiter(rate=4.0)

    async def fetch_latest(
        self,
        query: IngestionQuery,
        watermark: Watermark | None = None,
    ) -> list[NormalizedRecord]:
        site_numbers = query.query_terms or []
        if not site_numbers:
            logger.warning("usgs.water_quality.no_site_numbers")
            return []

        now = datetime.now(timezone.utc)
        if watermark and watermark.last_record_date:
            start_dt = watermark.last_record_date
        elif query.date_from:
            start_dt = query.date_from
        else:
            start_dt = now - timedelta(days=_DEFAULT_LOOKBACK_DAYS)

        end_dt = query.date_to or now
        sites_param = ",".join(site_numbers)

        params: dict[str, str] = {
            "format": "json",
            "sites": sites_param,
            "startDT": _date_str(start_dt),
            "endDT": _date_str(end_dt),
        }

        await self._limiter.acquire()
        try:
            resp = await self._client.get(_BASE_URL, params=params)
        except Exception as exc:
            raise ConnectorError(str(exc), self.connector_id) from exc

        if resp.status_code == 404:
            return []
        if resp.status_code == 429:
            raise RateLimitError("Rate limit exceeded", self.connector_id)
        if resp.status_code >= 500:
            raise ConnectorError(f"Server error {resp.status_code}", self.connector_id)
        resp.raise_for_status()

        data = resp.json()
        time_series_list = (
            data.get("value", {}).get("timeSeries", [])
        )
        records: list[NormalizedRecord] = []

        for ts in time_series_list:
            site_info = ts.get("sourceInfo", {})
            site_no = site_info.get("siteCode", [{}])[0].get("value", "")
            site_name = site_info.get("siteName", site_no)
            variable = ts.get("variable", {})
            var_code = variable.get("variableCode", [{}])[0].get("value", "")
            var_name = variable.get("variableName", var_code)
            unit = variable.get("unit", {}).get("unitCode", "")

            values = ts.get("values", [{}])[0].get("value", [])

            for entry in values:
                date_raw = entry.get("dateTime", "")
                value = entry.get("value", "")
                if not date_raw or value in ("", None):
                    continue

                try:
                    published_at = datetime.fromisoformat(
                        date_raw.replace("Z", "+00:00")
                    ).replace(tzinfo=timezone.utc)
                except ValueError:
                    logger.warning("usgs.bad_date", date=date_raw)
                    continue

                source_url = (
                    f"https://waterdata.usgs.gov/monitoring-location/{site_no}/"
                )
                title = f"USGS {site_name}: {var_name} = {value} {unit}"
                summary = f"Site {site_no} — {var_name}: {value} {unit} on {date_raw[:10]}"

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
                            "site_no": site_no,
                            "site_name": site_name,
                            "variable_code": var_code,
                            "variable_name": var_name,
                            "value": value,
                            "unit": unit,
                        },
                        raw_payload=entry,
                    )
                )

        logger.info("usgs.water_quality.fetched", count=len(records))
        return records

    async def health_check(self) -> HealthStatus:
        now = datetime.now(timezone.utc)
        params = {
            "format": "json",
            "sites": "01646500",  # Potomac River at Little Falls — reliable test site
            "startDT": _date_str(now - timedelta(days=1)),
            "endDT": _date_str(now),
        }
        try:
            resp = await self._client.get(_BASE_URL, params=params)
            if resp.status_code < 500:
                return HealthStatus.HEALTHY
            return HealthStatus.DEGRADED
        except Exception:
            return HealthStatus.FAILED
