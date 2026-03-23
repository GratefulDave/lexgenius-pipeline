from __future__ import annotations

import re
from datetime import datetime, timezone

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

_BASE_URL = "https://www.drugs.com/comments"
_HTML_TAG_RE = re.compile(r"<[^>]+>")
# Matches review blocks with rating and text content
_REVIEW_RE = re.compile(
    r'<div[^>]*class="[^"]*(?:ddc-comment|user-comment|review-comment)[^"]*"[^>]*>(.*?)</div>',
    re.IGNORECASE | re.DOTALL,
)
_RATING_RE = re.compile(r"(\d+(?:\.\d+)?)\s*/\s*(?:10|5)", re.IGNORECASE)
_DATE_RE = re.compile(
    r'<span[^>]*class="[^"]*(?:comment-date|date)[^"]*"[^>]*>([^<]+)</span>',
    re.IGNORECASE,
)
_REVIEW_TEXT_RE = re.compile(
    r'<(?:p|span)[^>]*class="[^"]*(?:comment-text|review-text|user-review)[^"]*"[^>]*>(.*?)</(?:p|span)>',
    re.IGNORECASE | re.DOTALL,
)
_SIDE_EFFECT_RE = re.compile(
    r"(?:side\s*effects?|adverse|symptoms?|experienced?|suffered?|caused?)[\s:]+([^.!?]{10,100})",
    re.IGNORECASE,
)


def _strip_html(text: str) -> str:
    return _HTML_TAG_RE.sub("", text).strip()


def _parse_review_date(date_str: str) -> datetime:
    date_str = date_str.strip()
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(date_str, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return datetime.now(tz=timezone.utc)


class DrugsDotComReviewsConnector(BaseConnector):
    connector_id = "commercial.drugsdotcom_reviews"
    source_tier = SourceTier.COMMERCIAL
    source_label = "Drugs.com Patient Reviews"
    supports_incremental = True

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._rate_limiter = AsyncRateLimiter(rate=0.5, burst=2)

    async def fetch_latest(
        self,
        query: IngestionQuery,
        watermark: Watermark | None = None,
    ) -> list[NormalizedRecord]:
        terms = query.query_terms or []
        if not terms:
            logger.warning("drugsdotcom_reviews.no_query_terms")
            return []

        records: list[NormalizedRecord] = []

        async with create_http_client() as client:
            for term in terms:
                await self._rate_limiter.acquire()
                drug_slug = term.lower().replace(" ", "-")
                url = f"{_BASE_URL}/{drug_slug}.html"

                try:
                    resp = await client.get(url)
                except Exception as exc:
                    logger.warning(
                        "drugsdotcom_reviews.request_error",
                        drug=term,
                        error=str(exc),
                    )
                    continue

                if resp.status_code >= 400:
                    logger.warning(
                        "drugsdotcom_reviews.http_error",
                        drug=term,
                        status=resp.status_code,
                    )
                    continue

                html = resp.text
                reviews = _REVIEW_RE.findall(html)
                review_dates = _DATE_RE.findall(html)
                review_texts = _REVIEW_TEXT_RE.findall(html)

                for i, review_html in enumerate(reviews):
                    review_text = _strip_html(review_texts[i]) if i < len(review_texts) else ""
                    if not review_text:
                        review_text = _strip_html(review_html)

                    if not review_text or len(review_text) < 20:
                        continue

                    rating_match = _RATING_RE.search(review_html)
                    rating = float(rating_match.group(1)) if rating_match else None

                    published_at = (
                        _parse_review_date(review_dates[i])
                        if i < len(review_dates)
                        else datetime.now(tz=timezone.utc)
                    )
                    if watermark and watermark.last_record_date:
                        if published_at <= watermark.last_record_date:
                            continue

                    side_effects = _SIDE_EFFECT_RE.findall(review_text)
                    source_url = url

                    metadata: dict[str, str | float | list[str] | None] = {
                        "drug": term,
                        "rating": rating,
                    }
                    if side_effects:
                        metadata["mentioned_side_effects"] = [se.strip() for se in side_effects[:5]]

                    records.append(
                        NormalizedRecord(
                            title=f"Patient review: {term}",
                            summary=review_text[:500],
                            record_type=RecordType.ADVERSE_EVENT,
                            source_connector_id=self.connector_id,
                            source_label=self.source_label,
                            source_url=source_url,
                            published_at=published_at,
                            fingerprint=generate_fingerprint(
                                self.connector_id,
                                source_url,
                                review_text[:100],
                                published_at,
                            ),
                            metadata=metadata,
                            raw_payload={
                                "drug": term,
                                "review_text": review_text,
                                "rating": rating,
                            },
                        )
                    )

        logger.info("drugsdotcom_reviews.fetched", count=len(records))
        return records

    async def health_check(self) -> HealthStatus:
        async with create_http_client() as client:
            try:
                resp = await client.get(f"{_BASE_URL}/aspirin.html")
                if resp.status_code < 500:
                    return HealthStatus.HEALTHY
                return HealthStatus.DEGRADED
            except Exception:
                return HealthStatus.FAILED
