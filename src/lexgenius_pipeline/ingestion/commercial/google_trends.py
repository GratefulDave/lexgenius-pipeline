from __future__ import annotations

import asyncio
import functools
from datetime import datetime, timezone
from urllib.parse import quote_plus

import structlog

from lexgenius_pipeline.common.errors import ConnectorError
from lexgenius_pipeline.common.models import IngestionQuery, NormalizedRecord, Watermark
from lexgenius_pipeline.common.rate_limiter import AsyncRateLimiter
from lexgenius_pipeline.common.types import HealthStatus, RecordType, SourceTier
from lexgenius_pipeline.ingestion.base import BaseConnector
from lexgenius_pipeline.ingestion.normalize import generate_fingerprint
from lexgenius_pipeline.settings import Settings, get_settings

logger = structlog.get_logger(__name__)

_DEFAULT_KEYWORDS = [
    "{term} lawsuit",
    "{term} class action",
    "{term} side effects",
    "{term} recall",
]


class GoogleTrendsConnector(BaseConnector):
    connector_id = "commercial.google_trends"
    source_tier = SourceTier.COMMERCIAL
    source_label = "Google Trends"
    supports_incremental = False

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._rate_limiter = AsyncRateLimiter(rate=0.2, burst=1)

    async def fetch_latest(
        self,
        query: IngestionQuery,
        watermark: Watermark | None = None,
    ) -> list[NormalizedRecord]:
        terms = query.query_terms or []
        if not terms:
            logger.warning("google_trends.no_query_terms")
            return []

        try:
            from pytrends.request import TrendReq
        except ImportError:
            logger.warning("google_trends.pytrends_not_installed")
            return []

        records: list[NormalizedRecord] = []
        pytrends = TrendReq(hl="en-US", tz=300)
        loop = asyncio.get_event_loop()

        for term in terms:
            await self._rate_limiter.acquire()
            keywords = [kw.format(term=term) for kw in _DEFAULT_KEYWORDS]
            # pytrends supports max 5 keywords per request
            keywords = keywords[:5]

            try:
                await loop.run_in_executor(
                    None,
                    functools.partial(
                        pytrends.build_payload, keywords, timeframe="today 3-m", geo="US"
                    ),
                )
                interest_df = await loop.run_in_executor(
                    None, pytrends.interest_over_time
                )
            except Exception as exc:
                logger.warning(
                    "google_trends.api_error",
                    term=term,
                    error=str(exc),
                )
                continue

            if interest_df is None or interest_df.empty:
                continue

            # Drop isPartial column if present
            if "isPartial" in interest_df.columns:
                interest_df = interest_df.drop(columns=["isPartial"])

            latest_row = interest_df.iloc[-1]
            latest_date = interest_df.index[-1]
            published_at = latest_date.to_pydatetime().replace(tzinfo=timezone.utc)

            max_interest = int(latest_row.max()) if not latest_row.empty else 0
            peak_keyword = latest_row.idxmax() if not latest_row.empty else keywords[0]

            encoded_keywords = "+".join(quote_plus(kw) for kw in keywords[:3])
            source_url = (
                f"https://trends.google.com/trends/explore?q={encoded_keywords}&geo=US"
            )

            trend_data = {kw: int(latest_row.get(kw, 0)) for kw in keywords if kw in latest_row}

            records.append(
                NormalizedRecord(
                    title=f"Google Trends: {term} lawsuit interest",
                    summary=(
                        f"Search interest for '{peak_keyword}' peaked at {max_interest}/100. "
                        f"Trends: {trend_data}"
                    ),
                    record_type=RecordType.RESEARCH,
                    source_connector_id=self.connector_id,
                    source_label=self.source_label,
                    source_url=source_url,
                    published_at=published_at,
                    fingerprint=generate_fingerprint(
                        self.connector_id,
                        source_url,
                        f"trends_{term}",
                        published_at,
                    ),
                    metadata={
                        "term": term,
                        "max_interest": max_interest,
                        "peak_keyword": peak_keyword,
                        "trend_data": trend_data,
                    },
                    raw_payload={"term": term, "keywords": keywords, "trends": trend_data},
                )
            )

        logger.info("google_trends.fetched", count=len(records))
        return records

    async def health_check(self) -> HealthStatus:
        try:
            from pytrends.request import TrendReq

            pytrends = TrendReq(hl="en-US", tz=300)
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                functools.partial(
                    pytrends.build_payload, ["test"], timeframe="today 1-m", geo="US"
                ),
            )
            df = await loop.run_in_executor(None, pytrends.interest_over_time)
            if df is not None and not df.empty:
                return HealthStatus.HEALTHY
            return HealthStatus.DEGRADED
        except ImportError:
            return HealthStatus.FAILED
        except Exception:
            return HealthStatus.DEGRADED
