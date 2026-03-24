"""Illinois Attorney General press releases via HTML scraping.

Source: https://illinoisattorneygeneral.gov/news-room/

Illinois AG recently redesigned their website. Press releases are
accessible through the news room. The site uses a modern CMS.
"""

from __future__ import annotations

from datetime import datetime, timezone
from html.parser import HTMLParser

from lexgenius_pipeline.common.errors import ConnectorError
from lexgenius_pipeline.common.models import IngestionQuery, Watermark
from lexgenius_pipeline.common.types import HealthStatus
from lexgenius_pipeline.ingestion.state.ag_actions.base import BaseAGActionsConnector, RawPressRelease

_BASE_URL = "https://illinoisattorneygeneral.gov"
_PRESS_URL = f"{_BASE_URL}/news-room/"


class _ILAGParser(HTMLParser):
    """Parse Illinois AG news room page for press releases.

    The site lists releases with title links and dates.
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
        cls = attrs_dict.get("class", "") or ""
        href = attrs_dict.get("href", "")

        # Look for press release links (news-item or press-release patterns)
        if tag == "a" and href and "/news-room/" in href:
            self._in_link = True
            self._current_title = ""
            self._current_date = ""
            self._summary_parts = []
            if href.startswith("/"):
                href = f"{self.base_url}{href}"
            self._current_link = href
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
        for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%B %d, %Y", "%b %d, %Y"):
            try:
                return datetime.strptime(date_str.strip(), fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
        return datetime.now(tz=timezone.utc)


class IllinoisAGConnector(BaseAGActionsConnector):
    """Illinois Attorney General — press releases via HTML scraping.

    Press page: https://illinoisattorneygeneral.gov/news-room/
    No RSS feed available.
    """

    connector_id = "state.il.ag_actions"
    state_code = "IL"
    jurisdiction = "Illinois"
    source_label = "Illinois Attorney General"

    PRESS_RELEASES_URL = f"{_BASE_URL}/news-room/"

    async def _fetch_releases(
        self,
        query: IngestionQuery,
        watermark: Watermark | None = None,
    ) -> list[RawPressRelease]:
        def parse(html: str, base_url: str) -> list[RawPressRelease]:
            parser = _ILAGParser(base_url)
            try:
                parser.feed(html)
            except Exception as exc:
                raise ConnectorError(
                    f"Failed to parse IL AG press page: {exc}", self.connector_id
                ) from exc
            return parser.releases[: query.max_records]

        return await self._scrape_releases(self.PRESS_RELEASES_URL, item_parser=parse)

    async def health_check(self) -> HealthStatus:
        return await self._health_check_url(self.PRESS_RELEASES_URL)
