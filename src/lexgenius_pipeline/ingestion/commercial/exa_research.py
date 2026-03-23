from __future__ import annotations

from datetime import datetime, timezone

import structlog

from lexgenius_pipeline.common.errors import ConnectorError
from lexgenius_pipeline.common.http_client import create_http_client
from lexgenius_pipeline.common.models import IngestionQuery, NormalizedRecord, Watermark
from lexgenius_pipeline.common.types import HealthStatus, RecordType, SourceTier
from lexgenius_pipeline.ingestion.base import BaseConnector
from lexgenius_pipeline.ingestion.normalize import generate_fingerprint
from lexgenius_pipeline.settings import Settings, get_settings

logger = structlog.get_logger(__name__)

_EXA_URL = "https://api.exa.ai/search"


def _parse_exa_date(date_str: str | None) -> datetime:
    if not date_str:
        return datetime.now(tz=timezone.utc)
    try:
        # ISO 8601 format
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc).replace(tzinfo=timezone.utc)
    except Exception:
        return datetime.now(tz=timezone.utc)


class ExaResearchConnector(BaseConnector):
    """Exa AI semantic search connector for research content."""

    connector_id = "commercial.exa_research"
    source_tier = SourceTier.COMMERCIAL
    source_label = "Exa Research"
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
            logger.warning("exa_research.no_query_terms")
            return []

        if not self._settings.exa_api_key:
            logger.warning("exa_research.no_api_key")
            return []

        search_term = " ".join(terms)
        payload = {
            "query": search_term,
            "numResults": 5,
            "contents": {"text": {"maxCharacters": 600}},
        }
        headers = {"x-api-key": self._settings.exa_api_key, "Content-Type": "application/json"}

        try:
            resp = await self._client.post(_EXA_URL, json=payload, headers=headers)
        except Exception as exc:
            raise ConnectorError(str(exc), self.connector_id) from exc

        if resp.status_code == 401:
            raise ConnectorError("Invalid Exa API key", self.connector_id)
        if resp.status_code >= 400:
            raise ConnectorError(f"HTTP {resp.status_code}", self.connector_id)

        data = resp.json()
        results = data.get("results", [])
        records: list[NormalizedRecord] = []

        for item in results:
            title = (item.get("title") or "").strip()
            url = (item.get("url") or "").strip()
            published_date = item.get("publishedDate")
            text = (item.get("text") or "").strip()

            if not title or not url:
                continue

            published_at = _parse_exa_date(published_date)
            if watermark and watermark.last_record_date:
                if published_at <= watermark.last_record_date:
                    continue

            records.append(
                NormalizedRecord(
                    title=title,
                    summary=text[:500] if text else title,
                    record_type=RecordType.RESEARCH,
                    source_connector_id=self.connector_id,
                    source_label=self.source_label,
                    source_url=url,
                    published_at=published_at,
                    fingerprint=generate_fingerprint(
                        self.connector_id, url, title, published_at
                    ),
                    metadata={"exa_id": item.get("id"), "score": item.get("score")},
                    raw_payload=item,
                )
            )

        logger.info("exa_research.fetched", count=len(records))
        return records

    async def health_check(self) -> HealthStatus:
        if not self._settings.exa_api_key:
            return HealthStatus.DEGRADED
        try:
            payload = {"query": "test", "numResults": 1}
            headers = {"x-api-key": self._settings.exa_api_key, "Content-Type": "application/json"}
            resp = await self._client.post(_EXA_URL, json=payload, headers=headers)
            if resp.status_code < 500:
                return HealthStatus.HEALTHY
            return HealthStatus.DEGRADED
        except Exception:
            return HealthStatus.FAILED
