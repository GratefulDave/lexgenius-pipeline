"""Illinois Attorney General press releases via HTML scraping.

Source: https://illinoisattorneygeneral.gov/news-room/

Illinois AG recently redesigned their website. Press releases are
accessible through the news room. The site uses a modern CMS.
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

_BASE_URL = "https://illinoisattorneygeneral.gov"
_PRESS_URL = f"{_BASE_URL}/news-room/"


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
            parser = GenericPressReleaseParser(base_url, ["/news-room/"])
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
