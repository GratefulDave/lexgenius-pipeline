"""California Attorney General press releases via RSS feed.

Source: https://oag.ca.gov/news/feed (RSS 2.0)
Press page: https://oag.ca.gov/media/news

California publishes a Drupal RSS feed of all press releases.
"""

from __future__ import annotations

import re

from lexgenius_pipeline.common.models import IngestionQuery, NormalizedRecord, Watermark
from lexgenius_pipeline.common.types import HealthStatus
from lexgenius_pipeline.ingestion.state.ag_actions.base import BaseAGActionsConnector, RawPressRelease


class CaliforniaAGConnector(BaseAGActionsConnector):
    """California Attorney General — press releases via RSS feed.

    RSS feed: https://oag.ca.gov/news/feed
    Press page: https://oag.ca.gov/media/news
    """

    connector_id = "state.ca.ag_actions"
    state_code = "CA"
    jurisdiction = "California"
    source_label = "California Attorney General"

    RSS_FEED_URL = "https://oag.ca.gov/news/feed"
    PRESS_RELEASES_URL = "https://oag.ca.gov/media/news"

    async def _fetch_releases(
        self,
        query: IngestionQuery,
        watermark: Watermark | None = None,
    ) -> list[RawPressRelease]:
        max_items = query.max_records if query.max_records < 100 else 100
        return await self._fetch_rss_feed(self.RSS_FEED_URL, max_items=max_items)

    async def health_check(self) -> HealthStatus:
        return await self._health_check_url(self.RSS_FEED_URL)
