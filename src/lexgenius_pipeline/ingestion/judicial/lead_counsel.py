from __future__ import annotations

import re
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

_JPML_BASE_URL = "https://www.jpml.gov"
_JPML_PENDING_URL = f"{_JPML_BASE_URL}/pending-mdls/"

_CL_BASE_URL = "https://www.courtlistener.com/api/rest/v4"
_CL_SEARCH_URL = f"{_CL_BASE_URL}/search/"

# Patterns for extracting lead counsel / PSC information
_PSC_RE = re.compile(
    r"(?:plaintiffs?['\u2019]?\s*steering\s*committee|PSC|"
    r"lead\s+counsel|liaison\s+counsel|co-lead\s+counsel)",
    re.IGNORECASE,
)
_ATTORNEY_RE = re.compile(
    r"(?:appointed|designated|named)\s+(?:as\s+)?(?:lead\s+counsel|"
    r"liaison\s+counsel|co-lead|PSC\s+member)",
    re.IGNORECASE,
)
_MDL_NUMBER_RE = re.compile(r"MDL[\s\-]*(?:No\.?\s*)?(\d+)", re.IGNORECASE)
_TAG_STRIP = re.compile(r"<[^>]+>")


def _parse_date(date_str: str | None) -> datetime:
    """Parse dates from various sources."""
    if not date_str:
        return datetime.now(tz=timezone.utc)
    cleaned = date_str.strip()
    try:
        dt = datetime.fromisoformat(cleaned.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc).replace(tzinfo=timezone.utc)
    except (ValueError, AttributeError):
        pass
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(cleaned, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return datetime.now(tz=timezone.utc)


def _extract_counsel_from_html(html: str) -> list[dict[str, Any]]:
    """Extract lead counsel appointment data from JPML HTML pages.

    Parses transfer order pages for references to lead counsel,
    PSC membership, and liaison counsel designations.
    """
    entries: list[dict[str, Any]] = []
    text = _TAG_STRIP.sub(" ", html)

    sentences = re.split(r"[.!?]\s+", text)

    for sentence in sentences:
        if not _PSC_RE.search(sentence):
            continue

        mdl_match = _MDL_NUMBER_RE.search(sentence)
        mdl_number = mdl_match.group(1) if mdl_match else ""

        appointment_type = "psc_member"
        lower = sentence.lower()
        if "lead counsel" in lower or "co-lead" in lower:
            appointment_type = "lead_counsel"
        elif "liaison counsel" in lower:
            appointment_type = "liaison_counsel"

        date_match = re.search(
            r"(\w+\s+\d{1,2},?\s+\d{4}|\d{1,2}/\d{1,2}/\d{4})",
            sentence,
        )
        date_str = date_match.group(1) if date_match else ""

        entries.append(
            {
                "mdl_number": mdl_number,
                "text": sentence.strip()[:500],
                "appointment_type": appointment_type,
                "date": date_str,
            }
        )

    return entries


class LeadCounselConnector(BaseConnector):
    """Lead counsel appointments in MDLs connector.

    Tracks Plaintiffs' Steering Committee (PSC) membership, lead counsel,
    and liaison counsel designations. Derived from JPML transfer order
    pages and CourtListener docket data.
    """

    connector_id = "judicial.lead_counsel"
    source_tier = SourceTier.JUDICIAL
    source_label = "MDL Lead Counsel"
    supports_incremental = True

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._rate_limiter = AsyncRateLimiter(rate=0.5, burst=2)

    async def fetch_latest(
        self,
        query: IngestionQuery,
        watermark: Watermark | None = None,
    ) -> list[NormalizedRecord]:
        records: list[NormalizedRecord] = []
        query_terms = query.query_terms or []

        async with create_http_client(timeout=60.0) as client:
            await self._rate_limiter.acquire()
            try:
                resp = await client.get(_JPML_PENDING_URL)
                resp.raise_for_status()
            except Exception as exc:
                raise ConnectorError(str(exc), self.connector_id) from exc

            html = resp.text
            jpml_entries = _extract_counsel_from_html(html)

            for entry in jpml_entries:
                mdl_number = entry.get("mdl_number", "")
                text = entry.get("text", "")
                appointment_type = entry.get("appointment_type", "psc_member")
                date_str = entry.get("date", "")

                if not text:
                    continue

                if query_terms:
                    combined = f"{text} MDL {mdl_number}".lower()
                    if not any(term.lower() in combined for term in query_terms):
                        continue

                published_at = _parse_date(date_str)

                if watermark and watermark.last_record_date:
                    if published_at <= watermark.last_record_date:
                        continue

                type_label = appointment_type.replace("_", " ").title()
                title = (
                    f"{type_label} — MDL-{mdl_number}"
                    if mdl_number
                    else f"{type_label} Appointment"
                )
                source_url = _JPML_PENDING_URL

                records.append(
                    NormalizedRecord(
                        title=title,
                        summary=text[:500],
                        record_type=RecordType.FILING,
                        source_connector_id=self.connector_id,
                        source_label=self.source_label,
                        source_url=source_url,
                        published_at=published_at,
                        fingerprint=generate_fingerprint(
                            self.connector_id,
                            source_url,
                            title,
                            published_at,
                        ),
                        metadata={
                            "mdl_number": mdl_number,
                            "appointment_type": appointment_type,
                            "data_source": "jpml",
                        },
                        raw_payload=entry,
                    )
                )

            if query_terms:
                headers: dict[str, str] = {}
                if self._settings.courtlistener_api_key:
                    headers["Authorization"] = f"Token {self._settings.courtlistener_api_key}"

                for term in query_terms:
                    search_q = f"{term} lead counsel OR steering committee"
                    params: dict[str, str | int] = {
                        "q": search_q,
                        "type": "r",
                        "order_by": "dateFiled desc",
                    }

                    await self._rate_limiter.acquire()
                    try:
                        resp = await client.get(_CL_SEARCH_URL, params=params, headers=headers)
                    except Exception:
                        logger.warning("lead_counsel.cl_search_failed", term=term)
                        continue

                    if resp.status_code >= 400:
                        continue

                    data = resp.json()
                    for item in data.get("results", []):
                        record = self._parse_cl_result(item, watermark)
                        if record:
                            records.append(record)

        logger.info("lead_counsel.fetched", count=len(records))
        return records

    def _parse_cl_result(
        self,
        item: dict[str, Any],
        watermark: Watermark | None,
    ) -> NormalizedRecord | None:
        """Parse a CourtListener search result for lead counsel info."""
        case_name = (item.get("caseName") or item.get("case_name") or "").strip()
        snippet = (item.get("snippet") or "").strip()

        if not case_name:
            return None

        combined = f"{case_name} {snippet}".lower()
        if not any(
            kw in combined
            for kw in ("lead counsel", "steering committee", "psc", "liaison counsel")
        ):
            return None

        date_filed = item.get("dateFiled") or item.get("date_filed")
        court = (item.get("court") or item.get("court_id") or "").strip()
        absolute_url = (item.get("absoluteUrl") or item.get("absolute_url") or "").strip()

        mdl_match = _MDL_NUMBER_RE.search(f"{case_name} {snippet}")
        mdl_number = mdl_match.group(1) if mdl_match else ""

        source_url = (
            f"https://www.courtlistener.com{absolute_url}"
            if absolute_url and not absolute_url.startswith("http")
            else absolute_url or "https://www.courtlistener.com/"
        )

        published_at = _parse_date(date_filed)

        if watermark and watermark.last_record_date:
            if published_at <= watermark.last_record_date:
                return None

        title = f"Lead Counsel Order — {case_name}"

        return NormalizedRecord(
            title=title,
            summary=snippet[:500] if snippet else title,
            record_type=RecordType.FILING,
            source_connector_id=self.connector_id,
            source_label=self.source_label,
            source_url=source_url,
            published_at=published_at,
            fingerprint=generate_fingerprint(self.connector_id, source_url, title, published_at),
            metadata={
                "mdl_number": mdl_number,
                "court": court,
                "appointment_type": "lead_counsel",
                "data_source": "courtlistener",
                "date_filed": date_filed,
            },
            raw_payload=item,
        )

    async def health_check(self) -> HealthStatus:
        async with create_http_client() as client:
            try:
                resp = await client.get(_JPML_BASE_URL)
                if resp.status_code < 500:
                    return HealthStatus.HEALTHY
                return HealthStatus.DEGRADED
            except Exception:
                return HealthStatus.FAILED
