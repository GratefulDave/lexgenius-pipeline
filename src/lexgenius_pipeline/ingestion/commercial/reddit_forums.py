from __future__ import annotations

from datetime import datetime, timezone

import structlog

from lexgenius_pipeline.common.errors import AuthenticationError, ConnectorError
from lexgenius_pipeline.common.http_client import create_http_client
from lexgenius_pipeline.common.models import IngestionQuery, NormalizedRecord, Watermark
from lexgenius_pipeline.common.rate_limiter import AsyncRateLimiter
from lexgenius_pipeline.common.types import HealthStatus, RecordType, SourceTier
from lexgenius_pipeline.ingestion.base import BaseConnector
from lexgenius_pipeline.ingestion.normalize import generate_fingerprint
from lexgenius_pipeline.settings import Settings, get_settings

logger = structlog.get_logger(__name__)

_TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
_API_BASE = "https://oauth.reddit.com"
_DEFAULT_SUBREDDITS = ["lawsuit", "legaladvice", "classaction", "masstort"]


class RedditForumsConnector(BaseConnector):
    connector_id = "commercial.reddit_forums"
    source_tier = SourceTier.COMMERCIAL
    source_label = "Reddit Legal Forums"
    supports_incremental = True

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._rate_limiter = AsyncRateLimiter(rate=1.0, burst=2)
        self._access_token: str | None = None

    async def _authenticate(self) -> str:
        client_id = self._settings.reddit_client_id
        client_secret = self._settings.reddit_client_secret

        if not client_id or not client_secret:
            raise AuthenticationError(
                "Reddit client_id and client_secret required", self.connector_id
            )

        async with create_http_client() as client:
            resp = await client.post(
                _TOKEN_URL,
                data={"grant_type": "client_credentials"},
                auth=(client_id, client_secret),
                headers={"User-Agent": "lexgenius-pipeline/0.1.0"},
            )
            if resp.status_code != 200:
                raise AuthenticationError(
                    f"Reddit auth failed: HTTP {resp.status_code}", self.connector_id
                )
            data = resp.json()
            token = data.get("access_token", "")
            if not token:
                raise AuthenticationError("No access_token in response", self.connector_id)
            self._access_token = token
            return token

    async def fetch_latest(
        self,
        query: IngestionQuery,
        watermark: Watermark | None = None,
    ) -> list[NormalizedRecord]:
        if not self._settings.reddit_client_id:
            logger.warning("reddit_forums.no_credentials")
            return []

        token = self._access_token or await self._authenticate()
        headers = {
            "Authorization": f"Bearer {token}",
            "User-Agent": "lexgenius-pipeline/0.1.0",
        }

        subreddits = _DEFAULT_SUBREDDITS
        terms_lower = [t.lower() for t in (query.query_terms or [])]
        records: list[NormalizedRecord] = []

        async with create_http_client() as client:
            for subreddit in subreddits:
                await self._rate_limiter.acquire()
                url = f"{_API_BASE}/r/{subreddit}/new.json?limit=25"
                try:
                    resp = await client.get(url, headers=headers)
                except Exception as exc:
                    logger.warning(
                        "reddit_forums.request_error",
                        subreddit=subreddit,
                        error=str(exc),
                    )
                    continue

                if resp.status_code == 401:
                    token = await self._authenticate()
                    headers["Authorization"] = f"Bearer {token}"
                    try:
                        resp = await client.get(url, headers=headers)
                    except Exception as exc:
                        logger.warning(
                            "reddit_forums.retry_error",
                            subreddit=subreddit,
                            error=str(exc),
                        )
                        continue

                if resp.status_code >= 400:
                    logger.warning(
                        "reddit_forums.http_error",
                        subreddit=subreddit,
                        status=resp.status_code,
                    )
                    continue

                data = resp.json()
                posts = data.get("data", {}).get("children", [])

                for post_wrapper in posts:
                    post = post_wrapper.get("data", {})
                    title = (post.get("title") or "").strip()
                    selftext = (post.get("selftext") or "").strip()
                    permalink = post.get("permalink", "")
                    created_utc = post.get("created_utc", 0)

                    if not title:
                        continue

                    if terms_lower:
                        combined = f"{title} {selftext}".lower()
                        if not any(term in combined for term in terms_lower):
                            continue

                    published_at = datetime.fromtimestamp(created_utc, tz=timezone.utc)
                    if watermark and watermark.last_record_date:
                        if published_at <= watermark.last_record_date:
                            continue

                    source_url = f"https://www.reddit.com{permalink}"

                    records.append(
                        NormalizedRecord(
                            title=title,
                            summary=selftext[:500] if selftext else title,
                            record_type=RecordType.NEWS,
                            source_connector_id=self.connector_id,
                            source_label=self.source_label,
                            source_url=source_url,
                            published_at=published_at,
                            fingerprint=generate_fingerprint(
                                self.connector_id, source_url, title, published_at
                            ),
                            metadata={
                                "subreddit": subreddit,
                                "score": post.get("score", 0),
                                "num_comments": post.get("num_comments", 0),
                                "author": post.get("author", ""),
                            },
                            raw_payload=post,
                        )
                    )

        logger.info("reddit_forums.fetched", count=len(records))
        return records

    async def health_check(self) -> HealthStatus:
        if not self._settings.reddit_client_id:
            return HealthStatus.DEGRADED
        try:
            await self._authenticate()
            return HealthStatus.HEALTHY
        except Exception:
            return HealthStatus.FAILED
