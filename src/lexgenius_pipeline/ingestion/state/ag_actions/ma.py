"""Massachusetts Attorney General press releases via HTML scraping.

Source: https://www.mass.gov/news/office-of-the-attorney-general

Mass.gov uses a Drupal-based CMS. Press releases are listed with title
links, dates, and summary text on the news listing page.
"""

from __future__ import annotations

from lexgenius_pipeline.common.errors import ConnectorError
from lexgenius_pipeline.common.models import IngestionQuery, Watermark
from lexgenius_pipeline.common.types import HealthStatus
from lexgenius_pipeline.ingestion.state.ag_actions.base import (
    BaseAGActionsConnector,
    GenericPressReleaseParser,
    RawPressRelease,
)

_BASE_URL = "https://www.mass.gov"
_PRESS_URL = f"{_BASE_URL}/news/office-of-the-attorney-general"


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
            parser = GenericPressReleaseParser(base_url, ["/news/"])
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
