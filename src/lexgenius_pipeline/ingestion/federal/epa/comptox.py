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

_BASE_URL = "https://api.epa.gov/comptox/chemical/search/by-casrn/{cas_rn}"
_HEALTH_CAS = "50-00-0"  # Formaldehyde — common test chemical


class CompToxConnector(BaseConnector):
    """EPA CompTox chemical hazard data connector. Query terms are CAS RNs."""

    connector_id = "federal.epa.comptox"
    source_tier = SourceTier.FEDERAL
    source_label = "EPA CompTox"
    supports_incremental = False

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._client = create_http_client()
        self._limiter = AsyncRateLimiter(rate=4.0)

    def _headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        api_key = getattr(self._settings, "comptox_api_key", "")
        if api_key:
            headers["x-api-key"] = api_key
        return headers

    async def fetch_latest(
        self,
        query: IngestionQuery,
        watermark: Watermark | None = None,
    ) -> list[NormalizedRecord]:
        cas_numbers = query.query_terms or []
        if not cas_numbers:
            logger.warning("comptox.no_cas_numbers")
            return []

        records: list[NormalizedRecord] = []
        fetched_at = datetime.now(timezone.utc)

        for cas_rn in cas_numbers:
            url = _BASE_URL.format(cas_rn=cas_rn)
            await self._limiter.acquire()
            try:
                resp = await self._client.get(url, headers=self._headers())
            except Exception as exc:
                raise ConnectorError(str(exc), self.connector_id) from exc

            if resp.status_code == 404:
                logger.info("comptox.not_found", cas_rn=cas_rn)
                continue
            if resp.status_code == 429:
                raise RateLimitError("Rate limit exceeded", self.connector_id)
            if resp.status_code >= 500:
                raise ConnectorError(f"Server error {resp.status_code}", self.connector_id)
            resp.raise_for_status()

            item = resp.json()
            # API may return a list or a single object
            if isinstance(item, list):
                item = item[0] if item else {}

            dtxsid = item.get("dtxsid", "")
            preferred_name = item.get("preferredName") or item.get("name") or cas_rn
            mol_formula = item.get("molFormula", "")

            source_url = (
                f"https://comptox.epa.gov/dashboard/chemical/details/{dtxsid}"
                if dtxsid
                else url
            )
            title = f"CompTox: {preferred_name} ({cas_rn})"
            summary = f"Chemical formula: {mol_formula}" if mol_formula else f"CAS RN: {cas_rn}"

            records.append(
                NormalizedRecord(
                    title=title,
                    summary=summary,
                    record_type=RecordType.RESEARCH,
                    source_connector_id=self.connector_id,
                    source_label=self.source_label,
                    source_url=source_url,
                    published_at=fetched_at,
                    fingerprint=generate_fingerprint(
                        self.connector_id, source_url, title, fetched_at
                    ),
                    metadata={
                        "dtxsid": dtxsid,
                        "cas_rn": cas_rn,
                        "mol_formula": mol_formula,
                        "preferred_name": preferred_name,
                    },
                    raw_payload=item,
                )
            )

        logger.info("comptox.fetched", count=len(records))
        return records

    async def health_check(self) -> HealthStatus:
        url = _BASE_URL.format(cas_rn=_HEALTH_CAS)
        try:
            resp = await self._client.get(url, headers=self._headers())
            if resp.status_code < 500:
                return HealthStatus.HEALTHY
            return HealthStatus.DEGRADED
        except Exception:
            return HealthStatus.FAILED
