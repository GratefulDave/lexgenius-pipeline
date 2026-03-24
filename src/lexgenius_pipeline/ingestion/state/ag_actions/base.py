"""Base class for state Attorney General action connectors.

Provides shared logic for:
- RSS feed parsing (for states with RSS feeds)
- HTML press release page scraping (for states without RSS)
- Keyword filtering for mass-tort-relevant content
- Record normalization
"""

from __future__ import annotations

import re
from abc import abstractmethod
from html.parser import HTMLParser
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

import structlog
from defusedxml import ElementTree

from lexgenius_pipeline.common.errors import ConnectorError
from lexgenius_pipeline.common.http_client import create_http_client
from lexgenius_pipeline.common.models import IngestionQuery, NormalizedRecord, Watermark
from lexgenius_pipeline.common.rate_limiter import AsyncRateLimiter
from lexgenius_pipeline.common.types import HealthStatus, RecordType
from lexgenius_pipeline.ingestion.normalize import generate_fingerprint
from lexgenius_pipeline.ingestion.state.base import BaseStateConnector

logger = structlog.get_logger(__name__)

# ── Mass-tort relevance keywords ────────────────────────────────────

RELEVANCE_KEYWORDS: list[str] = [
    # Enforcement / consumer protection
    "consumer protection",
    "enforcement",
    "settlement",
    "lawsuit",
    "litigation",
    "sue",
    "sued",
    "complaint",
    "attorney general",
    "ag sues",
    "ag settles",
    "multistate",
    "coalition",
    # Pharma / medical
    "drug",
    "pharmaceutical",
    "pharma",
    "medical device",
    "recall",
    "safety",
    "opioid",
    "prescription",
    "fda",
    "medication",
    "device",
    # Environmental
    "environmental",
    "contamination",
    "toxic",
    "cleanup",
    "superfund",
    "pollution",
    "hazardous",
    "chemical",
    "water",
    "air quality",
    "epa",
    "pfas",
    "lead",
    "asbestos",
    # Data privacy
    "data privacy",
    "data breach",
    "consumer data",
    "privacy",
    "cybersecurity",
    "personal information",
    # Product liability
    "product liability",
    "defective",
    "harmful",
    "dangerous",
    "unsafe",
    "failure to warn",
    # Fraud / deceptive
    "false claims",
    "fraud",
    "deceptive",
    "unfair practice",
    "scam",
    "misleading",
]

# Precompile a single regex pattern for fast matching (case-insensitive).
_KEYWORD_PATTERN = re.compile(
    "|".join(re.escape(kw) for kw in RELEVANCE_KEYWORDS),
    re.IGNORECASE,
)


@dataclass
class RawPressRelease:
    """Intermediate representation for a parsed press release."""

    title: str
    url: str
    published_at: datetime
    summary: str = ""
    raw_html: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


class GenericPressReleaseParser(HTMLParser):
    """Reusable HTML parser for state AG press release listing pages.

    Accepts *link_patterns* — a list of substrings that a link's href must
    contain to be considered a press-release link.  Extracts title from link
    text, date from ``<time>`` elements, and summary from ``<p>`` tags that
    follow a matched link.
    """

    def __init__(self, base_url: str, link_patterns: list[str]) -> None:
        super().__init__()
        self.base_url = base_url.rstrip("/")
        self.link_patterns = [p.lower() for p in link_patterns]
        self.releases: list[RawPressRelease] = []
        self._current_title = ""
        self._current_link = ""
        self._current_date = ""
        self._in_link = False
        self._in_summary = False
        self._summary_parts: list[str] = []

    def _matches_link(self, href: str) -> bool:
        href_lower = href.lower()
        return any(p in href_lower for p in self.link_patterns)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = dict(attrs)
        href = attrs_dict.get("href", "")

        if tag == "a" and href and self._matches_link(href):
            self._in_link = True
            self._current_title = ""
            self._current_date = ""
            self._summary_parts = []
            if href.startswith("/"):
                href = f"{self.base_url}{href}"
            self._current_link = href
        elif tag == "time" and self._current_link:
            self._current_date = attrs_dict.get("datetime", "") or attrs_dict.get("content", "")
        elif tag == "p" and self._current_link and not self._in_link:
            self._in_summary = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._in_link:
            self._in_link = False
        elif tag == "p" and self._in_summary:
            self._in_summary = False
            if self._current_title and self._current_link:
                summary = " ".join(self._summary_parts).strip()
                published_at = BaseAGActionsConnector._parse_date(self._current_date)
                self.releases.append(
                    RawPressRelease(
                        title=self._current_title.strip(),
                        url=self._current_link,
                        published_at=published_at,
                        summary=summary[:500],
                        extra={"source_type": "scrape"},
                    )
                )
                self._current_title = ""
                self._current_link = ""

    def handle_data(self, data: str) -> None:
        stripped = data.strip()
        if not stripped:
            return
        if self._in_link:
            self._current_title += stripped
        elif self._in_summary:
            self._summary_parts.append(stripped)


class BaseAGActionsConnector(BaseStateConnector):
    """Base for all state AG press release / enforcement connectors.

    Subclasses must set:
      - connector_id   (e.g. "state.ca.ag_actions")
      - state_code     (e.g. "CA")
      - jurisdiction   (e.g. "California")
      - source_label   (e.g. "California Attorney General")

    Subclasses must implement:
      - _fetch_releases()  — return list[RawPressRelease]
      - health_check()     — verify source endpoint is reachable
    """

    source_label: str = "Attorney General"
    supports_incremental = True

    # ── Override these in subclasses ─────────────────────────────────
    RSS_FEED_URL: str | None = None
    PRESS_RELEASES_URL: str | None = None

    def __init__(self) -> None:
        self._rate_limiter = AsyncRateLimiter(rate=1.0, burst=2)

    # ── Keyword relevance filter ────────────────────────────────────

    @classmethod
    def is_relevant(cls, text: str) -> bool:
        """Return True if *text* contains any mass-tort-relevant keyword."""
        return bool(_KEYWORD_PATTERN.search(text))

    # ── Main fetch pipeline ─────────────────────────────────────────

    async def fetch_latest(
        self,
        query: IngestionQuery,
        watermark: Watermark | None = None,
    ) -> list[NormalizedRecord]:
        """Fetch and filter AG press releases."""
        raw_releases = await self._fetch_releases(query, watermark)
        records: list[NormalizedRecord] = []

        for release in raw_releases:
            # Apply date filter
            if query.date_from and release.published_at < query.date_from:
                continue
            if query.date_to and release.published_at > query.date_to:
                continue

            # Apply keyword relevance filter
            combined_text = f"{release.title} {release.summary}"
            if not self.is_relevant(combined_text):
                continue

            records.append(self._normalize_release(release))

        logger.info(
            "ag_actions.fetched",
            connector=self.connector_id,
            total=len(raw_releases),
            relevant=len(records),
        )
        return records

    def _normalize_release(self, release: RawPressRelease) -> NormalizedRecord:
        """Convert a RawPressRelease into a NormalizedRecord."""
        return NormalizedRecord(
            title=release.title,
            summary=release.summary or release.title,
            record_type=RecordType.ENFORCEMENT,
            source_connector_id=self.connector_id,
            source_label=self.source_label,
            source_url=release.url,
            published_at=release.published_at,
            confidence=1.0,
            fingerprint=generate_fingerprint(
                self.connector_id, release.url, release.title, release.published_at
            ),
            metadata={"state_code": self.state_code, **release.extra},
            raw_payload={"title": release.title, "summary": release.summary},
        )

    # ── Abstract methods ────────────────────────────────────────────

    @abstractmethod
    async def _fetch_releases(
        self,
        query: IngestionQuery,
        watermark: Watermark | None = None,
    ) -> list[RawPressRelease]:
        """Fetch raw press releases from the state AG source.

        Subclasses implement the actual HTTP call and parsing here.
        """

    # ── Shared RSS parser ───────────────────────────────────────────

    async def _fetch_rss_feed(
        self, feed_url: str, max_items: int | None = None
    ) -> list[RawPressRelease]:
        """Parse an RSS feed and return RawPressRelease items."""
        releases: list[RawPressRelease] = []

        await self._rate_limiter.acquire()
        async with create_http_client() as client:
            try:
                resp = await client.get(feed_url)
                resp.raise_for_status()
            except Exception as exc:
                raise ConnectorError(
                    f"Failed to fetch RSS feed {feed_url}: {exc}", self.connector_id
                ) from exc

            content = resp.text
            try:
                root = ElementTree.fromstring(content)
            except ElementTree.ParseError as exc:
                raise ConnectorError(
                    f"Failed to parse RSS XML from {feed_url}: {exc}",
                    self.connector_id,
                ) from exc

            # Handle RSS 2.0 with namespace
            ns = ""
            if root.tag.startswith("{"):
                ns = root.tag.split("}")[0] + "}"

            items = root.iter(f"{ns}item")
            if max_items:
                items = list(items)[:max_items]

            for item in items:
                release = self._parse_rss_item(item, ns)
                if release:
                    releases.append(release)

        return releases

    def _parse_rss_item(
        self, item: ElementTree.Element, ns: str = ""
    ) -> RawPressRelease | None:
        """Parse a single RSS <item> into a RawPressRelease."""
        def _text(tag: str) -> str:
            el = item.find(f"{ns}{tag}")
            if el is not None and el.text:
                return el.text.strip()
            return ""

        title = _text("title")
        link = _text("link")
        description = _text("description")

        if not title or not link:
            return None

        # Strip HTML tags from description
        summary = re.sub(r"<[^>]+>", "", description).strip()
        summary = summary[:500]

        published_at = self._parse_rss_date(_text("pubDate"))

        return RawPressRelease(
            title=title,
            url=link,
            published_at=published_at,
            summary=summary,
            extra={"source_type": "rss"},
        )

    @staticmethod
    def _parse_rss_date(date_str: str) -> datetime:
        """Parse common RSS date formats."""
        if not date_str:
            logger.warning("ag_actions.date_fallback", reason="empty date string")
            return datetime.now(tz=timezone.utc)

        # RFC 2822 (most common RSS format)
        try:
            return parsedate_to_datetime(date_str)
        except (ValueError, TypeError):
            pass

        # ISO 8601
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%B %d, %Y", "%b %d, %Y"):
            try:
                return datetime.strptime(date_str.strip(), fmt).replace(
                    tzinfo=timezone.utc
                )
            except ValueError:
                continue

        logger.warning("ag_actions.date_fallback", reason="unparseable date", date_str=date_str)
        return datetime.now(tz=timezone.utc)

    # ── Shared HTML scraping helpers ────────────────────────────────

    async def _fetch_press_page(self, url: str) -> str:
        """Fetch an HTML page and return the text content.

        Returns empty string on client errors (4xx) rather than raising.
        """
        await self._rate_limiter.acquire()
        async with create_http_client() as client:
            try:
                resp = await client.get(url)
                if resp.status_code >= 500:
                    resp.raise_for_status()
                if resp.status_code >= 400:
                    logger.warning(
                        "ag_actions.fetch_failed",
                        connector=self.connector_id,
                        url=url,
                        status=resp.status_code,
                    )
                    return ""
                return resp.text
            except ConnectorError:
                raise
            except Exception as exc:
                raise ConnectorError(
                    f"Failed to fetch press page {url}: {exc}", self.connector_id
                ) from exc

    async def _health_check_url(self, url: str) -> HealthStatus:
        """Check if a URL is reachable and returns 2xx."""
        async with create_http_client(timeout=15.0) as client:
            try:
                resp = await client.head(url, follow_redirects=True)
                if resp.status_code < 400:
                    return HealthStatus.HEALTHY
                return HealthStatus.DEGRADED
            except Exception:
                return HealthStatus.FAILED

    # ── Generic scrape-based connector implementation ────────────────

    @staticmethod
    def _parse_date(date_str: str, state: str = "") -> datetime:
        """Parse common date formats with logging on fallback."""
        if not date_str:
            logger.warning("ag_actions.date_fallback", reason="empty date string", state=state)
            return datetime.now(tz=timezone.utc)
        for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%m/%d/%Y", "%B %d, %Y", "%b %d, %Y"):
            try:
                return datetime.strptime(date_str.strip()[:20], fmt).replace(
                    tzinfo=timezone.utc
                )
            except ValueError:
                continue
        logger.warning(
            "ag_actions.date_fallback", reason="unparseable date", date_str=date_str, state=state
        )
        return datetime.now(tz=timezone.utc)

    async def _scrape_releases(
        self,
        url: str,
        *,
        item_parser: callable,
    ) -> list[RawPressRelease]:
        """Generic scrape implementation for states without RSS.

        *item_parser* receives (html: str, base_url: str) and returns
        a list of RawPressRelease.
        """
        html = await self._fetch_press_page(url)
        return item_parser(html, url)
