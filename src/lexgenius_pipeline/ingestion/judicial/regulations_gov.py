from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import quote_plus

import structlog

from lexgenius_pipeline.common.errors import ConnectorError
from lexgenius_pipeline.common.http_client import create_http_client
from lexgenius_pipeline.common.models import IngestionQuery, NormalizedRecord, Watermark
from lexgenius_pipeline.common.types import HealthStatus, RecordType, SourceTier
from lexgenius_pipeline.ingestion.base import BaseConnector
from lexgenius_pipeline.ingestion.normalize import generate_fingerprint
from lexgenius_pipeline.settings import Settings, get_settings

logger = structlog.get_logger(__name__)

_BASE_URL = "https://api.regulations.gov/v4/documents"


def _parse_reg_date(date_str: str | None) -> datetime:
    if not date_str:
        return datetime.now(tz=timezone.utc)
    try:
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc).replace(tzinfo=timezone.utc)
    except Exception:
        return datetime.now(tz=timezone.utc)


class RegulationsGovConnector(BaseConnector):
    """Regulations.gov federal rulemaking documents connector."""

    connector_id = "judicial.regulations_gov"
    source_tier = SourceTier.JUDICIAL
    source_label = "Regulations.gov"
    supports_incremental = True

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._client = create_http_client()

    async def fetch_latest(
        self,
        query: IngestionQuery,
        watermark: Watermark | None = None,
    ) -> list[NormalizedRecord]:
        terms = query.query_terms or []
        if not terms:
            logger.warning("regulations_gov.no_query_terms")
            return []

        search_term = " ".join(terms)
        params: dict[str, str | int] = {
            "filter[searchTerm]": search_term,
            "sort": "-postedDate",
            "page[size]": 10,
        }
        if self._settings.regulations_gov_api_key:
            params["api_key"] = self._settings.regulations_gov_api_key

        try:
            resp = await self._client.get(_BASE_URL, params=params)
        except Exception as exc:
            raise ConnectorError(str(exc), self.connector_id) from exc

        if resp.status_code == 404:
            return []
        if resp.status_code >= 400:
            raise ConnectorError(f"HTTP {resp.status_code}", self.connector_id)

        data = resp.json()
        items = data.get("data", [])
        records: list[NormalizedRecord] = []

        for item in items:
            attrs = item.get("attributes", {})
            title = (attrs.get("title") or "").strip()
            posted_date = attrs.get("postedDate")
            document_type = (attrs.get("documentType") or "").strip()
            object_id = (attrs.get("objectId") or item.get("id") or "").strip()

            if not title:
                continue

            source_url = (
                f"https://www.regulations.gov/document/{object_id}"
                if object_id
                else f"https://www.regulations.gov/search?filter[searchTerm]={quote_plus(title)}"
            )
            published_at = _parse_reg_date(posted_date)

            if watermark and watermark.last_record_date:
                if published_at <= watermark.last_record_date:
                    continue

            records.append(
                NormalizedRecord(
                    title=title,
                    summary=f"{document_type}: {title}" if document_type else title,
                    record_type=RecordType.REGULATION,
                    source_connector_id=self.connector_id,
                    source_label=self.source_label,
                    source_url=source_url,
                    published_at=published_at,
                    fingerprint=generate_fingerprint(
                        self.connector_id, source_url, title, published_at
                    ),
                    metadata={
                        "document_type": document_type,
                        "object_id": object_id,
                        "posted_date": posted_date,
                    },
                    raw_payload=item,
                )
            )

        logger.info("regulations_gov.fetched", count=len(records))
        return records

    async def health_check(self) -> HealthStatus:
        try:
            resp = await self._client.get(
                _BASE_URL, params={"filter[searchTerm]": "test", "page[size]": 1}
            )
            if resp.status_code < 500:
                return HealthStatus.HEALTHY
            return HealthStatus.DEGRADED
        except Exception:
            return HealthStatus.FAILED
