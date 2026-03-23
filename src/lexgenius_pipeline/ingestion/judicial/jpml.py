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

_BASE_URL = "https://www.jpml.gov"
_TRANSFER_ORDERS_URL = f"{_BASE_URL}/pending-mdls/"
_HEARING_SCHEDULE_URL = f"{_BASE_URL}/hearing-sessions/"

# Pattern to extract MDL number from text (e.g., "MDL No. 3100" or "MDL-3100")
_MDL_NUMBER_RE = re.compile(r"MDL[\s\-]*(?:No\.?\s*)?(\d+)", re.IGNORECASE)

# Pattern to extract case title from transfer order text
_CASE_TITLE_RE = re.compile(r"(?:In\s+[Rr]e[:\s]+)(.+?)(?:\s*\(|$)", re.IGNORECASE)


def _parse_jpml_date(date_str: str | None) -> datetime:
    """Parse dates found on jpml.gov pages."""
    if not date_str:
        return datetime.now(tz=timezone.utc)
    cleaned = date_str.strip()
    for fmt in (
        "%B %d, %Y",
        "%b %d, %Y",
        "%m/%d/%Y",
        "%Y-%m-%d",
        "%B %Y",
    ):
        try:
            return datetime.strptime(cleaned, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return datetime.now(tz=timezone.utc)


def _extract_mdl_number(text: str) -> str:
    """Extract MDL number from text."""
    match = _MDL_NUMBER_RE.search(text)
    return match.group(1) if match else ""


def _extract_transfer_orders_from_html(html: str) -> list[dict[str, Any]]:
    """Extract transfer order data from JPML HTML page.

    Parses the pending-mdls page for transfer order entries. Each entry
    typically contains an MDL number, case title, transferee district,
    and date.
    """
    orders: list[dict[str, Any]] = []

    row_pattern = re.compile(r"<tr[^>]*>(.*?)</tr>", re.DOTALL | re.IGNORECASE)
    cell_pattern = re.compile(r"<td[^>]*>(.*?)</td>", re.DOTALL | re.IGNORECASE)
    link_pattern = re.compile(
        r'<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
        re.DOTALL | re.IGNORECASE,
    )
    tag_strip = re.compile(r"<[^>]+>")

    rows = row_pattern.findall(html)
    for row in rows:
        cells = cell_pattern.findall(row)
        if len(cells) < 2:
            continue

        row_text = tag_strip.sub(" ", row).strip()
        mdl_number = _extract_mdl_number(row_text)
        if not mdl_number:
            continue

        link_match = link_pattern.search(row)
        href = link_match.group(1) if link_match else ""
        link_text = tag_strip.sub(" ", link_match.group(2)).strip() if link_match else ""

        clean_cells = [tag_strip.sub(" ", c).strip() for c in cells]

        title = link_text or clean_cells[0] if clean_cells else f"MDL No. {mdl_number}"
        case_title_match = _CASE_TITLE_RE.search(title)
        if case_title_match:
            title = case_title_match.group(1).strip()

        date_str = ""
        date_re = re.compile(r"(\w+\s+\d{1,2},?\s+\d{4}|\d{1,2}/\d{1,2}/\d{4})")
        for cell in clean_cells:
            date_match = date_re.search(cell)
            if date_match:
                date_str = date_match.group(1)
                break

        district = ""
        for cell in clean_cells:
            if any(
                kw in cell.lower()
                for kw in (
                    "district",
                    "division",
                    "court",
                    "southern",
                    "northern",
                    "eastern",
                    "western",
                    "central",
                )
            ):
                district = cell.strip()
                break

        orders.append(
            {
                "mdl_number": mdl_number,
                "title": title,
                "date": date_str,
                "district": district,
                "href": href,
                "raw_text": row_text,
            }
        )

    if not orders:
        mdl_matches = list(_MDL_NUMBER_RE.finditer(html))
        for match in mdl_matches:
            mdl_num = match.group(1)
            start = max(0, match.start() - 100)
            end = min(len(html), match.end() + 200)
            context = tag_strip.sub(" ", html[start:end]).strip()

            date_re = re.compile(r"(\w+\s+\d{1,2},?\s+\d{4}|\d{1,2}/\d{1,2}/\d{4})")
            date_match = date_re.search(context)
            date_str = date_match.group(1) if date_match else ""

            title_match = _CASE_TITLE_RE.search(context)
            title = title_match.group(1).strip() if title_match else context[:120]

            orders.append(
                {
                    "mdl_number": mdl_num,
                    "title": title,
                    "date": date_str,
                    "district": "",
                    "href": "",
                    "raw_text": context,
                }
            )

    return orders


class JPMLTransferOrdersConnector(BaseConnector):
    """JPML MDL transfer orders connector.

    Scrapes jpml.gov for MDL transfer orders, pending petitions, and
    hearing schedules. MDL transfer orders are the single most important
    early signal that a mass tort is forming.
    """

    connector_id = "judicial.jpml.transfer_orders"
    source_tier = SourceTier.JUDICIAL
    source_label = "JPML Transfer Orders"
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
                resp = await client.get(_TRANSFER_ORDERS_URL)
                resp.raise_for_status()
            except Exception as exc:
                raise ConnectorError(str(exc), self.connector_id) from exc

            html = resp.text
            orders = _extract_transfer_orders_from_html(html)

            for order in orders:
                title = order.get("title", "")
                mdl_number = order.get("mdl_number", "")
                date_str = order.get("date", "")
                district = order.get("district", "")
                href = order.get("href", "")

                if not title and not mdl_number:
                    continue

                if not title:
                    title = f"MDL No. {mdl_number}"

                if query_terms:
                    combined = f"{title} {order.get('raw_text', '')}".lower()
                    if not any(term.lower() in combined for term in query_terms):
                        continue

                source_url = (
                    f"{_BASE_URL}{href}"
                    if href and not href.startswith("http")
                    else href or f"{_BASE_URL}/pending-mdls/"
                )
                published_at = _parse_jpml_date(date_str)

                if watermark and watermark.last_record_date:
                    if published_at <= watermark.last_record_date:
                        continue

                display_title = f"MDL-{mdl_number}: {title}" if mdl_number else title
                summary_parts = [display_title]
                if district:
                    summary_parts.append(f"Transferee District: {district}")

                records.append(
                    NormalizedRecord(
                        title=display_title,
                        summary="; ".join(summary_parts),
                        record_type=RecordType.FILING,
                        source_connector_id=self.connector_id,
                        source_label=self.source_label,
                        source_url=source_url,
                        published_at=published_at,
                        fingerprint=generate_fingerprint(
                            self.connector_id,
                            source_url,
                            display_title,
                            published_at,
                        ),
                        metadata={
                            "mdl_number": mdl_number,
                            "transferee_district": district,
                            "order_type": "transfer_order",
                        },
                        raw_payload=order,
                    )
                )

        logger.info("jpml.transfer_orders.fetched", count=len(records))
        return records

    async def health_check(self) -> HealthStatus:
        async with create_http_client() as client:
            try:
                resp = await client.get(_BASE_URL)
                if resp.status_code < 500:
                    return HealthStatus.HEALTHY
                return HealthStatus.DEGRADED
            except Exception:
                return HealthStatus.FAILED
