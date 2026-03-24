"""North Carolina Attorney General press releases via HTML scraping.

Source: https://ncdoj.gov/newsroom/press-releases/

NC DOJ uses WordPress. Press releases are listed with title links
and dates in a tabular-like layout.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from html.parser import HTMLParser

from lexgenius_pipeline.common.errors import ConnectorError
from lexgenius_pipeline.common.models import IngestionQuery, Watermark
from lexgenius_pipeline.common.types import HealthStatus
from lexgenius_pipeline.ingestion.state.ag_actions.base import BaseAGActionsConnector, RawPressRelease

_BASE_URL = "https://ncdoj.gov"
_PRESS_URL = f"{_BASE_URL}/newsroom/press-releases/"


class _NCAGParser(HTMLParser):
    """Parse NC DOJ press releases page.

    NC DOJ lists releases in a table-like format with:
    - Date in one column (MM/DD/YY format)
    - Title as <a> link in another column
    - Structure: /newsroom/press-releases/ lists entries with
      date text and links to individual release pages
    """

    def __init__(self, base_url: str) -> None:
        super().__init__()
        self.base_url = base_url.rstrip("/")
        self.releases: list[RawPressRelease] = []
        self._current_title = ""
        self._current_link = ""
        self._current_date = ""
        self._in_link = False
        self._in_date = False
        self._in_summary = False
        self._summary_parts: list[str] = []
        self._last_data = ""
        self._in_td = False
        self._td_data = ""
        self._in_press_list = False

    def handle_starttag(self, tag: str, attrs: dict[str, str | None]) -> None:
        attrs_dict = dict(attrs)
        href = attrs_dict.get("href", "")
        cls = attrs_dict.get("class", "") or ""

        # Detect the press releases list section
        if tag == "div" and ("press-release" in cls.lower() or "newsroom" in cls.lower()):
            self._in_press_list = True
        elif tag == "a" and href and self._in_press_list:
            if href.startswith("/") or self.base_url in href:
                self._in_link = True
                self._current_title = ""
                self._summary_parts = []
                if href.startswith("/"):
                    href = f"{self.base_url}{href}"
                self._current_link = href
        elif tag == "time" and self._in_press_list:
            self._current_date = attrs_dict.get("datetime", "") or attrs_dict.get(
                "content", ""
            )
        elif tag == "td":
            self._in_td = True
            self._td_data = ""

    def handle_endtag(self, tag: str) -> None:
        if tag == "div":
            self._in_press_list = False
        elif tag == "a" and self._in_link:
            self._in_link = False
        elif tag == "td":
            self._in_td = False
            # If we captured date-like text in a td before a link
            if self._td_data and not self._current_date and not self._current_link:
                date_candidate = self._td_data.strip()
                if re.match(r"\d{1,2}/\d{1,2}/\d{2,4}", date_candidate):
                    self._current_date = date_candidate
            self._td_data = ""

    def handle_data(self, data: str) -> None:
        stripped = data.strip()
        if not stripped:
            return
        if self._in_link:
            self._current_title += stripped
        elif self._in_td:
            self._td_data += stripped
        elif self._in_summary:
            self._summary_parts.append(stripped)

    @staticmethod
    def _parse_date(date_str: str) -> datetime:
        if not date_str:
            return datetime.now(tz=timezone.utc)
        # NC uses MM/DD/YY or MM/DD/YYYY format
        for fmt in ("%m/%d/%y", "%m/%d/%Y", "%Y-%m-%d", "%B %d, %Y"):
            try:
                dt = datetime.strptime(date_str.strip(), fmt)
                # Handle 2-digit years
                if dt.year < 100:
                    dt = dt.replace(year=dt.year + 2000)
                return dt.replace(tzinfo=timezone.utc)
            except ValueError:
                continue
        return datetime.now(tz=timezone.utc)


class NorthCarolinaAGConnector(BaseAGActionsConnector):
    """North Carolina Attorney General — press releases via HTML scraping.

    Press page: https://ncdoj.gov/newsroom/press-releases/
    No RSS feed available.
    """

    connector_id = "state.nc.ag_actions"
    state_code = "NC"
    jurisdiction = "North Carolina"
    source_label = "North Carolina Attorney General"

    PRESS_RELEASES_URL = f"{_BASE_URL}/newsroom/press-releases/"

    async def _fetch_releases(
        self,
        query: IngestionQuery,
        watermark: Watermark | None = None,
    ) -> list[RawPressRelease]:
        def parse(html: str, base_url: str) -> list[RawPressRelease]:
            parser = _NCAGParser(base_url)
            try:
                parser.feed(html)
            except Exception as exc:
                raise ConnectorError(
                    f"Failed to parse NC AG press page: {exc}", self.connector_id
                ) from exc
            # Filter out entries without both title and link
            valid = [
                r
                for r in parser.releases
                if r.title and r.url and r.title != "News & Observer"
            ]
            return valid[: query.max_records]

        return await self._scrape_releases(self.PRESS_RELEASES_URL, item_parser=parse)

    async def health_check(self) -> HealthStatus:
        return await self._health_check_url(self.PRESS_RELEASES_URL)
