"""Pennsylvania Attorney General press releases via HTML scraping.

Source: https://www.attorneygeneral.gov (press releases section)

PA OAG website uses WordPress. Press releases are listed in the
News & Media section. The exact URL structure varies.
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

_BASE_URL = "https://www.attorneygeneral.gov"


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
            parser = GenericPressReleaseParser(
                base_url, ["press-release", "news-release", "/news/"]
            )
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
