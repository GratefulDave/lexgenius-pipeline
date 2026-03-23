from __future__ import annotations

from lexgenius_pipeline.common.models import IngestionQuery
from lexgenius_pipeline.common.types import SourceTier
from lexgenius_pipeline.ingestion._mock import MockConnector, create_mock_record
from lexgenius_pipeline.ingestion.registry import ConnectorRegistry
from lexgenius_pipeline.ingestion.runner import IngestionRunner


async def test_run_connector_persists_records(session_factory):
    record = create_mock_record("Record 1")
    connector = MockConnector([record])
    registry = ConnectorRegistry()
    registry.register(connector)

    runner = IngestionRunner(registry, session_factory)
    metrics = await runner.run_connector(connector, IngestionQuery())

    assert metrics.records_fetched == 1
    assert metrics.records_written == 1
    assert metrics.duplicates_skipped == 0
    assert metrics.errors == 0


async def test_run_connector_skips_intra_run_duplicates(session_factory):
    """Two records with the same fingerprint in a single fetch."""
    record = create_mock_record("Same Record")
    connector = MockConnector([record, record])
    registry = ConnectorRegistry()
    registry.register(connector)

    runner = IngestionRunner(registry, session_factory)
    metrics = await runner.run_connector(connector, IngestionQuery())

    assert metrics.records_fetched == 2
    assert metrics.records_written == 1
    assert metrics.duplicates_skipped == 1


async def test_run_connector_skips_cross_run_duplicates(session_factory):
    """Fingerprint dedup catches records fetched again across runs (watermark ignored)."""
    record = create_mock_record("Persistent Record")
    connector = MockConnector([record], ignore_watermark=True)
    registry = ConnectorRegistry()
    registry.register(connector)

    runner = IngestionRunner(registry, session_factory)
    first = await runner.run_connector(connector, IngestionQuery())
    second = await runner.run_connector(connector, IngestionQuery())

    assert first.records_written == 1
    assert second.records_fetched == 1
    assert second.records_written == 0
    assert second.duplicates_skipped == 1


async def test_run_all_aggregates_multiple_connectors(session_factory):
    c1 = MockConnector(
        [create_mock_record("R1", connector_id="test.a")],
        connector_id="test.a",
    )
    c2 = MockConnector(
        [
            create_mock_record("R2", connector_id="test.b"),
            create_mock_record("R3", connector_id="test.b", source_url="https://example.com/r3"),
        ],
        connector_id="test.b",
    )
    c2.source_tier = SourceTier.FEDERAL

    registry = ConnectorRegistry()
    registry.register(c1)
    registry.register(c2)

    runner = IngestionRunner(registry, session_factory)
    metrics = await runner.run_all(IngestionQuery())

    assert metrics.records_fetched == 3
    assert metrics.records_written == 3
    assert metrics.duplicates_skipped == 0


async def test_run_all_filters_by_connector_ids(session_factory):
    c1 = MockConnector([create_mock_record("R1", connector_id="test.a")], connector_id="test.a")
    c2 = MockConnector([create_mock_record("R2", connector_id="test.b")], connector_id="test.b")

    registry = ConnectorRegistry()
    registry.register(c1)
    registry.register(c2)

    runner = IngestionRunner(registry, session_factory)
    metrics = await runner.run_all(IngestionQuery(connector_ids=["test.a"]))

    assert metrics.records_fetched == 1
    assert metrics.records_written == 1
