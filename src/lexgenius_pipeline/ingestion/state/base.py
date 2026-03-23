from __future__ import annotations

from lexgenius_pipeline.common.types import SourceTier
from lexgenius_pipeline.ingestion.base import BaseConnector


class BaseStateConnector(BaseConnector):
    """Base class for all state-level data source connectors.

    Each state implementation should subclass this and set:
      - state_code: 2-letter state abbreviation (e.g. "DE")
      - jurisdiction: Human-readable jurisdiction (e.g. "Delaware")
      - connector_id: e.g. "state.de.courts"
      - source_label: e.g. "Delaware Courts"
    """

    source_tier = SourceTier.STATE
    state_code: str   # 2-letter state abbreviation
    jurisdiction: str  # Human-readable jurisdiction name
