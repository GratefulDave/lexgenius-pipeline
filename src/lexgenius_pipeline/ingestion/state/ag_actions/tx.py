"""Texas Attorney General press releases via HTML scraping.

Source: https://www.texasattorneygeneral.gov/news/press_releases

Texas OAG publishes press releases on a paginated listing page.
Each release has a title link, date, and summary paragraph.
The URL pattern is /news/releases/{slug}.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from html.parser import HTMLParser

from lexgenius_pipeline.common.errors import ConnectorError
from lexgenius_pipeline.common.models import IngestionQuery, Watermark
from lexgenius_pipeline.common.types import HealthStatus
from lexgenius_pipeline.ingestion.state.ag_actions.base import BaseAGActionsConnector, RawPressRelease

_BASE_URL = "https://www.texasattorneygeneral.gov"
_PRESS_URL = f"{_BASE_URL}/news/press_releases"


class _TXAGParser(HTMLParser):
    """Parse Texas OAG press release listing page.

    Press releases are listed as:
    - <h4> containing <a href="/news/releases/..."> with title
    - Date in <span> or as text following the link
    - Summary paragraph after the heading
    """

    def __init__(self, base_url: str) -> None:
        super().__init__()
        self.base_url = base_url.rstrip("/")
        self.releases: list[RawPressRelease] = []
        self._in_h4 = False
        self._in_link = False
        self._current_title = ""
        self._current_link = ""
        self._current_date_str = ""
        self._capture_date = False
        self._in_summary = False
        self._summary_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: dict[str, str | None]) -> None:
        attrs_dict = dict(attrs)
        if tag == "h4":
            self._in_h4 = True
            self._current_title = ""
            self._current_link = ""
        elif tag == "a" and self._in_h4:
            self._in_link = True
            href = attrs_dict.get("href", "")
            if href:
                if href.startswith("/"):
                    href = f"{self.base_url}{href}"
                self._current_link = href
        elif tag == "span" and self._in_h4:
            # Date might be in a span after the link
            self._capture_date = True
            self._current_date_str = ""
        elif tag == "p" and not self._in_h4 and self._current_title:
            self._in_summary = True
            self._summary_parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "h4" and self._in_h4:
            self._in_h4 = False
            self._in_link = False
        elif tag == "a":
            self._in_link = False
        elif tag == "span" and self._capture_date:
            self._capture_date = False
        elif tag == "p" and self._in_summary:
            self._in_summary = False
            if self._current_title and self._current_link:
                summary = " ".join(self._summary_parts).strip()
                published_at = self._parse_date(self._current_date_str)
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
        elif self._capture_date:
            self._current_date_str += stripped
        elif self._in_summary:
            self._summary_parts.append(stripped)

    @staticmethod
    def _parse_date(date_str: str) -> datetime:
        if not date_str:
            return datetime.now(tz=timezone.utc)
        # Texas uses "Month DD, YYYY" format
        for fmt in ("%B %d, %Y", "%b %d, %Y", "%m/%d/%Y", "%Y-%m-%d"):
            try:
                return datetime.strptime(date_str.strip(), fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
        return datetime.now(tz=timezone.utc)


class TexasAGConnector(BaseAGActionsConnector):
    """Texas Attorney General — press releases via HTML scraping.

    Press page: https://www.texasattorneygeneral.gov/news/press_releases
    No RSS feed available.
    """

    connector_id = "state.tx.ag_actions"
    state_code = "TX"
    jurisdiction = "Texas"
    source_label = "Texas Attorney General"

    PRESS_RELEASES_URL = f"{_BASE_URL}/news/press_releases"

    async def _fetch_releases(
        self,
        query: IngestionQuery,
        watermark: Watermark | None = None,
    ) -> list[RawPressRelease]:
        def parse(html: str, base_url: str) -> list[RawPressRelease]:
            parser = _TXAGParser(base_url)
            try:
                parser.feed(html)
            except Exception as exc:
                raise ConnectorError(
                    f"Failed to parse TX AG press page: {exc}", self.connector_id
                ) from exc
            return parser.releases[: query.max_records]

        return await self._scrape_releases(self.PRESS_RELEASES_URL, item_parser=parse)

    async def health_check(self) -> HealthStatus:
        return await self._health_check_url(self.PRESS_RELEASES_URL)
