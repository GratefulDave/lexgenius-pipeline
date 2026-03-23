from __future__ import annotations

import pytest

from lexgenius_pipeline.common.types import SourceTier
from lexgenius_pipeline.ingestion._mock import MockConnector
from lexgenius_pipeline.ingestion.registry import ConnectorRegistry


def _make_connector(connector_id: str, tier: SourceTier = SourceTier.COMMERCIAL) -> MockConnector:
    c = MockConnector(connector_id=connector_id)
    c.source_tier = tier
    return c


def test_register_and_get():
    registry = ConnectorRegistry()
    connector = MockConnector()
    registry.register(connector)
    assert registry.get("test.mock") is connector


def test_register_duplicate_raises():
    registry = ConnectorRegistry()
    registry.register(MockConnector())
    with pytest.raises(ValueError, match="already registered"):
        registry.register(MockConnector())


def test_get_nonexistent_raises_key_error():
    registry = ConnectorRegistry()
    with pytest.raises(KeyError, match="not found"):
        registry.get("does.not.exist")


def test_contains():
    registry = ConnectorRegistry()
    registry.register(MockConnector())
    assert "test.mock" in registry
    assert "other.mock" not in registry


def test_len():
    registry = ConnectorRegistry()
    assert len(registry) == 0
    registry.register(MockConnector())
    assert len(registry) == 1


def test_list_all():
    registry = ConnectorRegistry()
    c1 = _make_connector("federal.fda.faers")
    c2 = _make_connector("state.ca.oag")
    registry.register(c1)
    registry.register(c2)
    assert set(registry.list_all()) == {c1, c2}


def test_list_by_tier():
    registry = ConnectorRegistry()
    federal = _make_connector("federal.fda.faers", SourceTier.FEDERAL)
    state = _make_connector("state.ca.oag", SourceTier.STATE)
    registry.register(federal)
    registry.register(state)
    assert registry.list_by_tier(SourceTier.FEDERAL) == [federal]
    assert registry.list_by_tier(SourceTier.STATE) == [state]
    assert registry.list_by_tier(SourceTier.JUDICIAL) == []


def test_list_by_agency():
    registry = ConnectorRegistry()
    fda1 = _make_connector("federal.fda.faers")
    fda2 = _make_connector("federal.fda.recalls")
    epa = _make_connector("federal.epa.violations")
    registry.register(fda1)
    registry.register(fda2)
    registry.register(epa)
    fda_connectors = registry.list_by_agency("fda")
    assert fda1 in fda_connectors
    assert fda2 in fda_connectors
    assert epa not in fda_connectors
