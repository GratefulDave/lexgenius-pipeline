"""Pennsylvania Attorney General press releases via HTML scraping.

Source: https://www.attorneygeneral.gov (press releases section)

PA OAG website uses WordPress. Press releases are listed in the
News & Media section. The exact URL structure varies.
"""

from __future__ import annotations

from datetime import datetime, timezone
from html.parser import HTMLParser

import structlog

from lexgenius_pipeline.common.errors import ConnectorError
from lexgenius_pipeline.common.models import IngestionQuery, Watermark
from lexgenius_pipeline.common.types import HealthStatus
from lexgenius_pipeline.ingestion.state.ag_actions.base import BaseAGActionsConnector, RawPressRelease

logger = structlog.get_logger(__name__)

_BASE_URL = "https://www.attorneygeneral.gov"


class _PAAGParser(HTMLParser):
    """Parse PA AG press release listing page (WordPress-based).

    PA AG uses WordPress; press releases are typically in <article> elements
    with <a> links containing the title and href to the release.
    """

    def __init__(self, base_url: str) -> None:
        super().__init__()
        self.base_url = base_url.rstrip("/")
        self.releases: list[RawPressRelease] = []
        self._current_title = ""
        self._current_link = ""
        self._current_date = ""
        self._in_link = False
        self._in_summary = False
        self._summary_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: dict[str, str | None]) -> None:
        attrs_dict = dict(attrs)
        href = attrs_dict.get("href", "")
        cls = attrs_dict.get("class", "") or ""

        # Look for article links in the press release section
        if tag == "a" and href:
            href_lower = href.lower()
            if (
                "press-release" in href_lower
                or "news-release" in href_lower
                or "/news/" in href_lower
            ):
                self._in_link = True
                self._current_title = ""
                self._current_date = ""
                self._summary_parts = []
                if href.startswith("/"):
                    href = f"{self.base_url}{href}"
                self._current_link = href
        elif tag == "time" and self._current_link:
            self._current_date = attrs_dict.get("datetime", "")
        elif tag == "p" and self._current_link and not self._in_link:
            self._in_summary = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._in_link:
            self._in_link = False
        elif tag == "p" and self._in_summary:
            self._in_summary = False
            if self._current_title and self._current_link:
                summary = " ".join(self._summary_parts).strip()
                published_at = self._parse_date(self._current_date)
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

    @staticmethod
    def _parse_date(date_str: str) -> datetime:
        if not date_str:
            logger.warning("ag_actions.date_fallback", reason="empty date string", state="PA")
            return datetime.now(tz=timezone.utc)
        for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%m/%d/%Y", "%B %d, %Y"):
            try:
                return datetime.strptime(date_str.strip()[:20], fmt).replace(
                    tzinfo=timezone.utc
                )
            except ValueError:
                continue
        logger.warning("ag_actions.date_fallback", reason="unparseable date", date_str=date_str, state="PA")
        return datetime.now(tz=timezone.utc)


class PennsylvaniaAGConnector(BaseAGActionsConnector):
    """Pennsylvania Attorney General — press releases via HTML scraping.

    Press page: https://www.attorneygeneral.gov/ (News & Media section)
    No RSS feed available.
    """

    connector_id = "state.pa.ag_actions"
    state_code = "PA"
    jurisdiction = "Pennsylvania"
    source_label = "Pennsylvania Attorney General"

    PRESS_RELEASES_URL = f"{_BASE_URL}/"

    async def _fetch_releases(
        self,
        query: IngestionQuery,
        watermark: Watermark | None = None,
    ) -> list[RawPressRelease]:
        def parse(html: str, base_url: str) -> list[RawPressRelease]:
            parser = _PAAGParser(base_url)
            try:
                parser.feed(html)
            except Exception as exc:
                raise ConnectorError(
                    f"Failed to parse PA AG press page: {exc}", self.connector_id
                ) from exc
            return parser.releases[: query.max_records]

        return await self._scrape_releases(self.PRESS_RELEASES_URL, item_parser=parse)

    async def health_check(self) -> HealthStatus:
        return await self._health_check_url(self.PRESS_RELEASES_URL)
