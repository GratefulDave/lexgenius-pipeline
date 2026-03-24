"""Massachusetts Attorney General press releases via HTML scraping.

Source: https://www.mass.gov/news/office-of-the-attorney-general

Mass.gov uses a Drupal-based CMS. Press releases are listed with title
links, dates, and summary text on the news listing page.
"""

from __future__ import annotations

from datetime import datetime, timezone
from html.parser import HTMLParser

from lexgenius_pipeline.common.errors import ConnectorError
from lexgenius_pipeline.common.models import IngestionQuery, Watermark
from lexgenius_pipeline.common.types import HealthStatus
from lexgenius_pipeline.ingestion.state.ag_actions.base import BaseAGActionsConnector, RawPressRelease

_BASE_URL = "https://www.mass.gov"
_PRESS_URL = f"{_BASE_URL}/news/office-of-the-attorney-general"


class _MAAGParser(HTMLParser):
    """Parse Mass.gov AG press releases page.

    Mass.gov lists items with <a> links inside headings, with dates
    in surrounding elements.
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
        self._date_pattern: bool = False

    def handle_starttag(self, tag: str, attrs: dict[str, str | None]) -> None:
        attrs_dict = dict(attrs)
        href = attrs_dict.get("href", "")
        cls = attrs_dict.get("class", "") or ""

        if tag == "a" and href and "/news/" in href:
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
            return datetime.now(tz=timezone.utc)
        for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%m/%d/%Y", "%B %d, %Y"):
            try:
                return datetime.strptime(date_str.strip()[:20], fmt).replace(
                    tzinfo=timezone.utc
                )
            except ValueError:
                continue
        return datetime.now(tz=timezone.utc)


class MassachusettsAGConnector(BaseAGActionsConnector):
    """Massachusetts Attorney General — press releases via HTML scraping.

    Press page: https://www.mass.gov/news/office-of-the-attorney-general
    Note: mass.gov is a JS-heavy SPA that may return 403 to bots.
    The connector gracefully handles this and returns empty results.
    No RSS feed available.
    """

    connector_id = "state.ma.ag_actions"
    state_code = "MA"
    jurisdiction = "Massachusetts"
    source_label = "Massachusetts Attorney General"

    PRESS_RELEASES_URL = f"{_BASE_URL}/news/office-of-the-attorney-general"

    async def _fetch_releases(
        self,
        query: IngestionQuery,
        watermark: Watermark | None = None,
    ) -> list[RawPressRelease]:
        def parse(html: str, base_url: str) -> list[RawPressRelease]:
            parser = _MAAGParser(base_url)
            try:
                parser.feed(html)
            except Exception as exc:
                raise ConnectorError(
                    f"Failed to parse MA AG press page: {exc}", self.connector_id
                ) from exc
            return parser.releases[: query.max_records]

        try:
            return await self._scrape_releases(self.PRESS_RELEASES_URL, item_parser=parse)
        except ConnectorError:
            # mass.gov returns 403 for bots — return empty gracefully
            return []

    async def health_check(self) -> HealthStatus:
        # mass.gov is known to 403 programmatic access
        # Try the base domain instead
        result = await self._health_check_url(_BASE_URL)
        if result == HealthStatus.FAILED:
            return HealthStatus.DEGRADED
        return result
