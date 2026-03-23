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

_BASE_URL = "https://clinicaltrials.gov/api/v2/studies"


def _parse_ct_date(value: str | None) -> datetime:
    if not value:
        return datetime.now(tz=timezone.utc)
    for fmt in ("%Y-%m-%d", "%Y-%m", "%Y"):
        try:
            return datetime.strptime(value.strip(), fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return datetime.now(tz=timezone.utc)


class ClinicalTrialsConnector(BaseConnector):
    connector_id = "federal.nih.clinical_trials"
    source_tier = SourceTier.FEDERAL
    source_label = "ClinicalTrials.gov"
    supports_incremental = True

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._rate_limiter = AsyncRateLimiter(rate=2.0, burst=2)

    async def fetch_latest(
        self,
        query: IngestionQuery,
        watermark: Watermark | None = None,
    ) -> list[NormalizedRecord]:
        terms = query.query_terms or []
        if not terms:
            logger.warning("clinical_trials.no_query_terms")
            return []

        search_term = " OR ".join(terms)

        async with create_http_client() as client:
            await self._rate_limiter.acquire()
            try:
                resp = await client.get(
                    _BASE_URL,
                    params={
                        "format": "json",
                        "countTotal": "true",
                        "pageSize": 10,
                        "query.term": search_term,
                    },
                )
                resp.raise_for_status()
            except Exception as exc:
                raise ConnectorError(str(exc), self.connector_id) from exc

        studies: list[dict[str, Any]] = resp.json().get("studies", [])
        records: list[NormalizedRecord] = []

        for study in studies:
            protocol = study.get("protocolSection", {})
            id_module = protocol.get("identificationModule", {})
            status_module = protocol.get("statusModule", {})
            sponsor_module = protocol.get("sponsorCollaboratorsModule", {})

            nct_id: str = id_module.get("nctId", "")
            if not nct_id:
                continue

            title: str = id_module.get("briefTitle", "").strip() or nct_id
            overall_status: str = status_module.get("overallStatus", "")
            why_stopped: str = status_module.get("whyStopped", "")
            completion_date: str = (
                status_module.get("completionDateStruct", {}).get("date")
                or status_module.get("primaryCompletionDateStruct", {}).get("date")
                or ""
            )
            lead_sponsor: str = (
                sponsor_module.get("leadSponsor", {}).get("name", "")
            )
            source_url = f"https://clinicaltrials.gov/study/{nct_id}"

            summary_parts = []
            if overall_status:
                summary_parts.append(f"Status: {overall_status}")
            if why_stopped:
                summary_parts.append(f"Why stopped: {why_stopped}")
            if lead_sponsor:
                summary_parts.append(f"Sponsor: {lead_sponsor}")
            summary = "; ".join(summary_parts) or title

            published_at = _parse_ct_date(completion_date)

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
                        "nct_id": nct_id,
                        "overall_status": overall_status,
                        "why_stopped": why_stopped,
                        "lead_sponsor": lead_sponsor,
                        "completion_date": completion_date,
                    },
                    raw_payload=study,
                )
            )

        logger.info("clinical_trials.fetched", count=len(records))
        return records

    async def health_check(self) -> HealthStatus:
        async with create_http_client() as client:
            try:
                resp = await client.get(
                    _BASE_URL,
                    params={"format": "json", "pageSize": 1, "query.term": "health"},
                )
                resp.raise_for_status()
                return HealthStatus.HEALTHY
            except Exception:
                return HealthStatus.FAILED
