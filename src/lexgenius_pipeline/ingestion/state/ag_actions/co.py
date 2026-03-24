"""Colorado Attorney General press releases via HTML scraping.

Source: https://coag.gov/media-center/press-room/

Colorado AG uses a modern CMS (likely WordPress). Press releases
are listed in the press room with title links and dates.
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

_BASE_URL = "https://coag.gov"
_PRESS_URL = f"{_BASE_URL}/media-center/press-room/"


class ColoradoAGConnector(BaseAGActionsConnector):
    """Colorado Attorney General — press releases via HTML scraping.

    Press page: https://coag.gov/media-center/press-room/
    No RSS feed available.
    """

    connector_id = "state.co.ag_actions"
    state_code = "CO"
    jurisdiction = "Colorado"
    source_label = "Colorado Attorney General"

    PRESS_RELEASES_URL = f"{_BASE_URL}/media-center/press-room/"

    async def _fetch_releases(
        self,
        query: IngestionQuery,
        watermark: Watermark | None = None,
    ) -> list[RawPressRelease]:
        def parse(html: str, base_url: str) -> list[RawPressRelease]:
            parser = GenericPressReleaseParser(
                base_url, ["press", "news", "media-center"]
            )
            try:
                parser.feed(html)
            except Exception as exc:
                raise ConnectorError(
                    f"Failed to parse CO AG press page: {exc}", self.connector_id
                ) from exc
            return parser.releases[: query.max_records]

        return await self._scrape_releases(self.PRESS_RELEASES_URL, item_parser=parse)

    async def health_check(self) -> HealthStatus:
        return await self._health_check_url(self.PRESS_RELEASES_URL)
