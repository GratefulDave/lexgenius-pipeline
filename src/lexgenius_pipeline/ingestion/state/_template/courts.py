from __future__ import annotations

"""Template for implementing a new state court connector.

To add a new state (e.g. California):

1. Copy this file to  state/ca/courts.py
2. Replace STATE_CODE, STATE_NAME, and BASE_URL with the state-specific values
3. Implement fetch_latest() to parse the state court's public data feed/API
4. Register the connector in state/ca/__init__.py
5. Mark the state as implemented=True in state/_registry.py

Example:
    from lexgenius_pipeline.ingestion.state.base import BaseStateConnector

    class CaliforniaCourtConnector(BaseStateConnector):
        connector_id = "state.ca.courts"
        state_code = "CA"
        jurisdiction = "California"
        source_label = "California Courts"
        ...
"""

from lexgenius_pipeline.common.models import IngestionQuery, NormalizedRecord, Watermark
from lexgenius_pipeline.common.types import HealthStatus
from lexgenius_pipeline.ingestion.state.base import BaseStateConnector


class TemplateStateCourtConnector(BaseStateConnector):
    """Stub template — replace with state-specific implementation.

    Steps to implement:
    1. Set connector_id = "state.{code}.courts"  (e.g. "state.ca.courts")
    2. Set state_code = "{CODE}"                  (e.g. "CA")
    3. Set jurisdiction = "{State Name}"          (e.g. "California")
    4. Set source_label to a descriptive name
    5. Implement fetch_latest() to call the state court's API/RSS
    6. Implement health_check() to verify the endpoint is reachable
    """

    connector_id = "state.template.courts"
    state_code = "XX"
    jurisdiction = "Template State"
    source_label = "Template State Courts"
    supports_incremental = True

    async def fetch_latest(
        self,
        query: IngestionQuery,
        watermark: Watermark | None = None,
    ) -> list[NormalizedRecord]:
        # TODO: implement state-specific fetch logic
        return []

    async def health_check(self) -> HealthStatus:
        # TODO: implement health check for the state court endpoint
        return HealthStatus.DEGRADED
