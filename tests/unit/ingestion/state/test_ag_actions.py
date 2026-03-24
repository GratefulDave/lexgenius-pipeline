"""Unit tests for state Attorney General action connectors."""

from __future__ import annotations

import pytest

from lexgenius_pipeline.common.models import IngestionQuery
from lexgenius_pipeline.common.types import HealthStatus, SourceTier, RecordType
from lexgenius_pipeline.ingestion.state.ag_actions import (
    ALL_AG_CONNECTORS,
    BaseAGActionsConnector,
    CaliforniaAGConnector,
    ColoradoAGConnector,
    FloridaAGConnector,
    IllinoisAGConnector,
    MassachusettsAGConnector,
    NorthCarolinaAGConnector,
    NewYorkAGConnector,
    OhioAGConnector,
    PennsylvaniaAGConnector,
    TexasAGConnector,
)


# ── Expected connector IDs and metadata ─────────────────────────────

CONNECTOR_SPECS = [
    {"cls": CaliforniaAGConnector, "id": "state.ca.ag_actions", "code": "CA", "name": "California"},
    {"cls": NewYorkAGConnector, "id": "state.ny.ag_actions", "code": "NY", "name": "New York"},
    {"cls": TexasAGConnector, "id": "state.tx.ag_actions", "code": "TX", "name": "Texas"},
    {"cls": IllinoisAGConnector, "id": "state.il.ag_actions", "code": "IL", "name": "Illinois"},
    {"cls": MassachusettsAGConnector, "id": "state.ma.ag_actions", "code": "MA", "name": "Massachusetts"},
    {"cls": PennsylvaniaAGConnector, "id": "state.pa.ag_actions", "code": "PA", "name": "Pennsylvania"},
    {"cls": FloridaAGConnector, "id": "state.fl.ag_actions", "code": "FL", "name": "Florida"},
    {"cls": OhioAGConnector, "id": "state.oh.ag_actions", "code": "OH", "name": "Ohio"},
    {"cls": ColoradoAGConnector, "id": "state.co.ag_actions", "code": "CO", "name": "Colorado"},
    {"cls": NorthCarolinaAGConnector, "id": "state.nc.ag_actions", "code": "NC", "name": "North Carolina"},
]

# Parameterize as (connector_class, expected_id, state_code, jurisdiction_name)
PARAMS = [(s["cls"], s["id"], s["code"], s["name"]) for s in CONNECTOR_SPECS]
IDS = [s["id"] for s in CONNECTOR_SPECS]


# ── Instantiation tests ─────────────────────────────────────────────


class TestConnectorInstantiation:
    """Each connector should be instantiable without errors."""

    @pytest.mark.parametrize("cls,expected_id,code,name", PARAMS, ids=IDS)
    def test_instantiation(self, cls, expected_id, code, name) -> None:
        connector = cls()
        assert connector is not None

    @pytest.mark.parametrize("cls,expected_id,code,name", PARAMS, ids=IDS)
    def test_connector_id(self, cls, expected_id, code, name) -> None:
        connector = cls()
        assert connector.connector_id == expected_id

    @pytest.mark.parametrize("cls,expected_id,code,name", PARAMS, ids=IDS)
    def test_state_code(self, cls, expected_id, code, name) -> None:
        connector = cls()
        assert connector.state_code == code

    @pytest.mark.parametrize("cls,expected_id,code,name", PARAMS, ids=IDS)
    def test_jurisdiction(self, cls, expected_id, code, name) -> None:
        connector = cls()
        assert connector.jurisdiction == name


# ── Source tier and type tests ──────────────────────────────────────


class TestConnectorMetadata:
    """All AG connectors must be STATE tier and produce ENFORCEMENT records."""

    @pytest.mark.parametrize("cls,expected_id,code,name", PARAMS, ids=IDS)
    def test_source_tier_is_state(self, cls, expected_id, code, name) -> None:
        connector = cls()
        assert connector.source_tier == SourceTier.STATE

    @pytest.mark.parametrize("cls,expected_id,code,name", PARAMS, ids=IDS)
    def test_supports_incremental(self, cls, expected_id, code, name) -> None:
        connector = cls()
        assert connector.supports_incremental is True

    @pytest.mark.parametrize("cls,expected_id,code,name", PARAMS, ids=IDS)
    def test_has_source_label(self, cls, expected_id, code, name) -> None:
        connector = cls()
        assert "Attorney General" in connector.source_label
        assert isinstance(connector.source_label, str)
        assert len(connector.source_label) > 5

    @pytest.mark.parametrize("cls,expected_id,code,name", PARAMS, ids=IDS)
    def test_repr(self, cls, expected_id, code, name) -> None:
        connector = cls()
        r = repr(connector)
        assert "AttorneyGeneral" in r or "AG" in r or "Connector" in r


# ── Base class tests ────────────────────────────────────────────────


class TestBaseAGActionsConnector:
    """Tests for the shared base class logic."""

    def test_is_relevant_consumer_protection(self) -> None:
        assert BaseAGActionsConnector.is_relevant("Consumer protection lawsuit filed")
        assert BaseAGActionsConnector.is_relevant("AG settles with pharma company")
        assert BaseAGActionsConnector.is_relevant("Environmental contamination cleanup")
        assert BaseAGActionsConnector.is_relevant("Data breach affects millions")
        assert BaseAGActionsConnector.is_relevant("Product liability for defective device")
        assert BaseAGActionsConnector.is_relevant("Opioid settlement reached")
        assert BaseAGActionsConnector.is_relevant("Multistate coalition sues company")
        assert BaseAGActionsConnector.is_relevant("False claims act lawsuit")

    def test_is_not_relevant_unrelated(self) -> None:
        # These should NOT match (no relevance keywords)
        assert not BaseAGActionsConnector.is_relevant("AG visits local school")
        assert not BaseAGActionsConnector.is_relevant("Office closed for holiday")

    def test_is_relevant_case_insensitive(self) -> None:
        assert BaseAGActionsConnector.is_relevant("CONSUMER PROTECTION SUIT FILED")
        assert BaseAGActionsConnector.is_relevant("settlement Reached In Fraud Case")

    def test_all_connectors_in_registry(self) -> None:
        assert len(ALL_AG_CONNECTORS) == 10
        for cls in ALL_AG_CONNECTORS:
            assert issubclass(cls, BaseAGActionsConnector)


# ── Health check tests ──────────────────────────────────────────────


class TestHealthCheck:
    """Health checks should return HealthStatus enum values."""

    @pytest.mark.parametrize("cls,expected_id,code,name", PARAMS, ids=IDS)
    @pytest.mark.asyncio
    async def test_health_check_returns_health_status(self, cls, expected_id, code, name) -> None:
        connector = cls()
        result = await connector.health_check()
        assert isinstance(result, HealthStatus)
        assert result in {HealthStatus.HEALTHY, HealthStatus.DEGRADED, HealthStatus.FAILED}


# ── fetch_latest tests ──────────────────────────────────────────────


class TestFetchLatest:
    """fetch_latest with an empty query should return a list."""

    @pytest.mark.parametrize("cls,expected_id,code,name", PARAMS, ids=IDS)
    @pytest.mark.asyncio
    async def test_fetch_latest_empty_query(self, cls, expected_id, code, name) -> None:
        connector = cls()
        query = IngestionQuery()
        result = await connector.fetch_latest(query)
        assert isinstance(result, list)

    @pytest.mark.parametrize("cls,expected_id,code,name", PARAMS, ids=IDS)
    @pytest.mark.asyncio
    async def test_fetch_latest_with_date_filter(self, cls, expected_id, code, name) -> None:
        connector = cls()
        from datetime import datetime, timedelta, timezone

        query = IngestionQuery(
            date_from=datetime.now(tz=timezone.utc) - timedelta(days=30),
            date_to=datetime.now(tz=timezone.utc),
        )
        result = await connector.fetch_latest(query)
        assert isinstance(result, list)


# ── Connector ID format test ────────────────────────────────────────


class TestConnectorIDFormat:
    """All connector IDs must follow the state.{code}.ag_actions pattern."""

    @pytest.mark.parametrize("cls,expected_id,code,name", PARAMS, ids=IDS)
    def test_connector_id_format(self, cls, expected_id, code, name) -> None:
        parts = expected_id.split(".")
        assert len(parts) == 3
        assert parts[0] == "state"
        assert len(parts[1]) == 2  # 2-letter state code
        assert parts[2] == "ag_actions"


# ── Uniqueness tests ────────────────────────────────────────────────


class TestUniqueness:
    """No two connectors should share the same connector_id or state_code."""

    def test_unique_connector_ids(self) -> None:
        ids = [s["id"] for s in CONNECTOR_SPECS]
        assert len(ids) == len(set(ids)), f"Duplicate connector IDs: {ids}"

    def test_unique_state_codes(self) -> None:
        codes = [s["code"] for s in CONNECTOR_SPECS]
        assert len(codes) == len(set(codes)), f"Duplicate state codes: {codes}"

    def test_all_ag_connectors_count(self) -> None:
        assert len(ALL_AG_CONNECTORS) == len(CONNECTOR_SPECS)
