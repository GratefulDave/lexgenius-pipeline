from __future__ import annotations

import pytest

from lexgenius_pipeline.common.types import HealthStatus, SourceTier
from lexgenius_pipeline.ingestion._mock import MockConnector, create_mock_record
from lexgenius_pipeline.ingestion.base import BaseConnector
from lexgenius_pipeline.common.models import IngestionQuery


def test_base_connector_cannot_be_instantiated():
    with pytest.raises(TypeError):
        BaseConnector()  # type: ignore[abstract]


def test_mock_connector_has_required_attributes():
    connector = MockConnector()
    assert connector.connector_id == "test.mock"
    assert connector.source_tier == SourceTier.COMMERCIAL
    assert connector.source_label == "Mock Source"
    assert connector.supports_incremental is True


def test_mock_connector_custom_id():
    connector = MockConnector(connector_id="federal.fda.faers")
    assert connector.connector_id == "federal.fda.faers"


def test_mock_connector_repr():
    connector = MockConnector()
    assert "MockConnector" in repr(connector)
    assert "test.mock" in repr(connector)


async def test_mock_connector_fetch_latest_returns_records():
    record = create_mock_record("Test")
    connector = MockConnector([record])
    query = IngestionQuery()
    results = await connector.fetch_latest(query)
    assert results == [record]


async def test_mock_connector_fetch_latest_empty():
    connector = MockConnector()
    query = IngestionQuery()
    results = await connector.fetch_latest(query)
    assert results == []


async def test_mock_connector_health_check_returns_healthy():
    connector = MockConnector()
    status = await connector.health_check()
    assert status == HealthStatus.HEALTHY
