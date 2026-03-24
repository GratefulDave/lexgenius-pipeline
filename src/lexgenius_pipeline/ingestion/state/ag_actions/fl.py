"""Florida Attorney General press releases via HTML scraping.

Source: https://www.myfloridalegal.com

Florida AG uses Drupal CMS. News releases are accessible via the
site's search and listing pages. The content type is "News Release".
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

_BASE_URL = "https://www.myfloridalegal.com"


class FloridaAGConnector(BaseAGActionsConnector):
    """Florida Attorney General — press releases via HTML scraping.

    Source: https://www.myfloridalegal.com
    No RSS feed available. Drupal-based CMS.
    """

    connector_id = "state.fl.ag_actions"
    state_code = "FL"
    jurisdiction = "Florida"
    source_label = "Florida Attorney General"

    PRESS_RELEASES_URL = _BASE_URL

    async def _fetch_releases(
        self,
        query: IngestionQuery,
        watermark: Watermark | None = None,
    ) -> list[RawPressRelease]:
        def parse(html: str, base_url: str) -> list[RawPressRelease]:
            parser = GenericPressReleaseParser(base_url, [_BASE_URL])
            try:
                parser.feed(html)
            except Exception as exc:
                raise ConnectorError(
                    f"Failed to parse FL AG press page: {exc}", self.connector_id
                ) from exc
            return parser.releases[: query.max_records]

        return await self._scrape_releases(self.PRESS_RELEASES_URL, item_parser=parse)

    async def health_check(self) -> HealthStatus:
        return await self._health_check_url(self.PRESS_RELEASES_URL)
