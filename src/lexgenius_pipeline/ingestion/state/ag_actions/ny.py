"""New York Attorney General press releases via HTML scraping.

Source: https://ag.ny.gov/press-releases
CMS: Custom (likely Drupal-based)

NY AG does not publish a public RSS feed. Press releases are listed
on a filterable page with JS-rendered content. We scrape the listing
page and extract title, link, date, and summary from the HTML.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any

from lexgenius_pipeline.common.errors import ConnectorError
from lexgenius_pipeline.common.models import IngestionQuery, NormalizedRecord, Watermark
from lexgenius_pipeline.common.types import HealthStatus
from lexgenius_pipeline.ingestion.state.ag_actions.base import BaseAGActionsConnector, RawPressRelease

_BASE_URL = "https://ag.ny.gov"
_PRESS_URL = f"{_BASE_URL}/press-releases"


class _NYAGParser(HTMLParser):
    """Extract press release entries from the NY AG press releases page.

    The NY AG site lists press releases as <article> elements with:
    - <h3> containing an <a> with title and href
    - <span class="field-content"> for date
    - Paragraph text for summary
    """

    def __init__(self, base_url: str) -> None:
        super().__init__()
        self.base_url = base_url
        self.releases: list[RawPressRelease] = []
        self._in_article = False
        self._in_title = False
        self._in_date = False
        self._in_summary = False
        self._current_title = ""
        self._current_link = ""
        self._current_date_str = ""
        self._current_summary_parts: list[str] = []
        self._current_p_depth = 0

    def handle_starttag(self, tag: str, attrs: dict[str, str | None]) -> None:
        attrs_dict = dict(attrs)
        if tag == "article":
            self._in_article = True
            self._current_title = ""
            self._current_link = ""
            self._current_date_str = ""
            self._current_summary_parts = []
        elif self._in_article:
            if tag == "h3":
                self._in_title = True
            elif tag == "a" and self._in_title:
                href = attrs_dict.get("href", "")
                if href:
                    self._current_link = href if href.startswith("http") else f"{self.base_url}{href}"
            elif tag == "time":
                self._current_date_str = attrs_dict.get("datetime", "") or attrs_dict.get("content", "")
            elif tag == "p" and not self._in_title and not self._in_date:
                self._in_summary = True
                self._current_p_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag == "article" and self._in_article:
            self._in_article = False
            if self._current_title and self._current_link:
                published_at = self._parse_date(self._current_date_str)
                summary = " ".join(self._current_summary_parts).strip()
                self.releases.append(
                    RawPressRelease(
                        title=self._current_title,
                        url=self._current_link,
                        published_at=published_at,
                        summary=summary[:500],
                        extra={"source_type": "scrape"},
                    )
                )
        elif tag == "h3" and self._in_title:
            self._in_title = False
        elif tag == "p" and self._in_summary:
            self._current_p_depth -= 1
            if self._current_p_depth <= 0:
                self._in_summary = False
                self._current_p_depth = 0

    def handle_data(self, data: str) -> None:
        if self._in_title and not self._current_link:
            self._current_title += data.strip()
        elif self._in_title:
            # Data inside <a> within <h3>
            pass  # title was set from starttag
        elif self._in_summary:
            self._current_summary_parts.append(data.strip())

    @staticmethod
    def _parse_date(date_str: str) -> datetime:
        if not date_str:
            return datetime.now(tz=timezone.utc)
        for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%B %d, %Y", "%Y-%m-%dT%H:%M:%S"):
            try:
                return datetime.strptime(date_str.strip()[:20], fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
        return datetime.now(tz=timezone.utc)


class NewYorkAGConnector(BaseAGActionsConnector):
    """New York Attorney General — press releases via HTML scraping.

    Press page: https://ag.ny.gov/press-releases
    No RSS feed available.
    """

    connector_id = "state.ny.ag_actions"
    state_code = "NY"
    jurisdiction = "New York"
    source_label = "New York Attorney General"

    PRESS_RELEASES_URL = f"{_BASE_URL}/press-releases"

    async def _fetch_releases(
        self,
        query: IngestionQuery,
        watermark: Watermark | None = None,
    ) -> list[RawPressRelease]:
        def parse(html: str, base_url: str) -> list[RawPressRelease]:
            parser = _NYAGParser(base_url)
            try:
                parser.feed(html)
            except Exception as exc:
                raise ConnectorError(
                    f"Failed to parse NY AG press page: {exc}", self.connector_id
                ) from exc
            return parser.releases[: query.max_records]

        return await self._scrape_releases(self.PRESS_RELEASES_URL, item_parser=parse)

    async def health_check(self) -> HealthStatus:
        return await self._health_check_url(self.PRESS_RELEASES_URL)
