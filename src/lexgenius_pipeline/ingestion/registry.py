from __future__ import annotations

from lexgenius_pipeline.common.types import SourceTier
from lexgenius_pipeline.ingestion.base import BaseConnector


class ConnectorRegistry:
    """Catalogue of registered connectors with tier/agency filtering."""

    def __init__(self) -> None:
        self._connectors: dict[str, BaseConnector] = {}

    def register(self, connector: BaseConnector) -> None:
        if connector.connector_id in self._connectors:
            raise ValueError(f"Connector '{connector.connector_id}' already registered")
        self._connectors[connector.connector_id] = connector

    def get(self, connector_id: str) -> BaseConnector:
        try:
            return self._connectors[connector_id]
        except KeyError:
            raise KeyError(f"Connector '{connector_id}' not found in registry")

    def list_all(self) -> list[BaseConnector]:
        return list(self._connectors.values())

    def list_by_tier(self, tier: SourceTier) -> list[BaseConnector]:
        return [c for c in self._connectors.values() if c.source_tier == tier]

    def list_by_agency(self, agency: str) -> list[BaseConnector]:
        # Parses agency from connector_id pattern: "{tier}.{agency}.{source}"
        return [
            c for c in self._connectors.values()
            if len(c.connector_id.split(".")) >= 2 and c.connector_id.split(".")[1] == agency
        ]

    def __len__(self) -> int:
        return len(self._connectors)

    def __contains__(self, connector_id: str) -> bool:
        return connector_id in self._connectors
