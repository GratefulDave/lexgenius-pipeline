"""Tests for federal agency connectors."""
from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest
import respx

from lexgenius_pipeline.common.models import IngestionQuery
from lexgenius_pipeline.common.types import HealthStatus, SourceTier
from lexgenius_pipeline.settings import Settings


# ---------------------------------------------------------------------------
# Imports — grouped by package
# ---------------------------------------------------------------------------

# CDC
from lexgenius_pipeline.ingestion.federal.cdc.wonder import CDCWonderConnector

# DOJ
from lexgenius_pipeline.ingestion.federal.doj.fca_settlements import DOJFCASettlementsConnector
from lexgenius_pipeline.ingestion.federal.doj.press_releases import DOJPressReleasesConnector

# FDA
from lexgenius_pipeline.ingestion.federal.fda.device_510k import FDA510KConnector
from lexgenius_pipeline.ingestion.federal.fda.device_recalls import FDARecallsDeviceConnector
from lexgenius_pipeline.ingestion.federal.fda.medwatch import FDAMedWatchConnector
from lexgenius_pipeline.ingestion.federal.fda.orange_book import FDAOrangeBookConnector
from lexgenius_pipeline.ingestion.federal.fda.safety_communications import FDASafetyCommunicationsConnector
from lexgenius_pipeline.ingestion.federal.fda.warning_letters import FDAWarningLettersConnector

# FTC
from lexgenius_pipeline.ingestion.federal.ftc.enforcement import FTCEnforcementConnector

# NHTSA
from lexgenius_pipeline.ingestion.federal.nhtsa.complaints import NHTSAComplaintsConnector
from lexgenius_pipeline.ingestion.federal.nhtsa.recalls import NHTSARecallsConnector

# OSHA
from lexgenius_pipeline.ingestion.federal.osha.inspections import OSHAInspectionsConnector

# CPSC (new consumer_reports)
from lexgenius_pipeline.ingestion.federal.cpsc.consumer_reports import CPSCConsumerReportsConnector

# CFPB
from lexgenius_pipeline.ingestion.federal.cfpb.enforcement import CFPBEnforcementConnector

# EPA (new connectors)
from lexgenius_pipeline.ingestion.federal.epa.echo import EPAECHOConnector
from lexgenius_pipeline.ingestion.federal.epa.superfund import EPASuperfundConnector
from lexgenius_pipeline.ingestion.federal.epa.tri import EPATRIConnector

# ATSDR
from lexgenius_pipeline.ingestion.federal.atsdr.health_assessments import ATSDRHealthAssessmentsConnector

# USDA
from lexgenius_pipeline.ingestion.federal.usda.recalls import USDRecallsConnector

# NAAG
from lexgenius_pipeline.ingestion.federal.naag.actions import NAAGActionsConnector

# FJC
from lexgenius_pipeline.ingestion.federal.fjc.idb import FJCIDBConnector

# NIH (new SEER)
from lexgenius_pipeline.ingestion.federal.nih.seer import NIHSEERConnector


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def mock_settings():
    """Provide default settings so connectors can be instantiated in clean CI."""
    with patch("lexgenius_pipeline.settings.get_settings", return_value=Settings()):
        yield


# ---------------------------------------------------------------------------
# Collect all new federal connectors for bulk testing
# ---------------------------------------------------------------------------

# Connectors whose data source doesn't support incremental fetching
_NON_INCREMENTAL_IDS = {
    "federal.atsdr.health_assessments",
    "federal.fjc.idb",
    "federal.nih.seer",
    "federal.naag.actions",
}

ALL_NEW_CONNECTORS = [
    # CDC
    ("federal.cdc.wonder", CDCWonderConnector),
    # DOJ
    ("federal.doj.press_releases", DOJPressReleasesConnector),
    ("federal.doj.fca_settlements", DOJFCASettlementsConnector),
    # FDA (new)
    ("federal.fda.safety_communications", FDASafetyCommunicationsConnector),
    ("federal.fda.medwatch", FDAMedWatchConnector),
    ("federal.fda.device_510k", FDA510KConnector),
    ("federal.fda.warning_letters", FDAWarningLettersConnector),
    ("federal.fda.device_recalls", FDARecallsDeviceConnector),
    ("federal.fda.orange_book", FDAOrangeBookConnector),
    # FTC
    ("federal.ftc.enforcement", FTCEnforcementConnector),
    # NHTSA
    ("federal.nhtsa.recalls", NHTSARecallsConnector),
    ("federal.nhtsa.complaints", NHTSAComplaintsConnector),
    # OSHA
    ("federal.osha.inspections", OSHAInspectionsConnector),
    # CPSC (new)
    ("federal.cpsc.consumer_reports", CPSCConsumerReportsConnector),
    # CFPB
    ("federal.cfpb.enforcement", CFPBEnforcementConnector),
    # EPA (new)
    ("federal.epa.echo", EPAECHOConnector),
    ("federal.epa.tri", EPATRIConnector),
    ("federal.epa.superfund", EPASuperfundConnector),
    # ATSDR
    ("federal.atsdr.health_assessments", ATSDRHealthAssessmentsConnector),
    # USDA
    ("federal.usda.recalls", USDRecallsConnector),
    # NAAG
    ("federal.naag.actions", NAAGActionsConnector),
    # FJC
    ("federal.fjc.idb", FJCIDBConnector),
    # NIH (new)
    ("federal.nih.seer", NIHSEERConnector),
]


# ---------------------------------------------------------------------------
# Parametrized instantiation tests
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("expected_id,cls", ALL_NEW_CONNECTORS)
def test_connector_instantiation(expected_id, cls):
    connector = cls()
    assert connector is not None
    assert isinstance(connector, cls)


# ---------------------------------------------------------------------------
# Parametrized connector_id tests
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("expected_id,cls", ALL_NEW_CONNECTORS)
def test_connector_id(expected_id, cls):
    assert cls.connector_id == expected_id, f"{cls.__name__} has wrong connector_id"


# ---------------------------------------------------------------------------
# Parametrized source_tier tests
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("expected_id,cls", ALL_NEW_CONNECTORS)
def test_connector_federal_tier(expected_id, cls):
    assert cls.source_tier == SourceTier.FEDERAL, f"{cls.__name__} should be FEDERAL tier"


# ---------------------------------------------------------------------------
# Parametrized supports_incremental tests
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("expected_id,cls", ALL_NEW_CONNECTORS)
def test_connector_supports_incremental(expected_id, cls):
    if expected_id in _NON_INCREMENTAL_IDS:
        assert cls.supports_incremental is False, (
            f"{cls.__name__} should NOT support incremental (scrape-based)"
        )
    else:
        assert cls.supports_incremental is True, (
            f"{cls.__name__} should support incremental"
        )


# ---------------------------------------------------------------------------
# Parametrized source_label tests
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("expected_id,cls", ALL_NEW_CONNECTORS)
def test_connector_has_source_label(expected_id, cls):
    assert isinstance(cls.source_label, str)
    assert len(cls.source_label) > 0


# ---------------------------------------------------------------------------
# fetch_latest returns empty for empty query (no terms) — mocked network
# ---------------------------------------------------------------------------

_EMPTY_QUERY = IngestionQuery()


@respx.mock
@pytest.mark.parametrize("expected_id,cls", ALL_NEW_CONNECTORS)
@pytest.mark.asyncio
async def test_fetch_latest_no_terms_returns_empty(expected_id, cls):
    """Connectors should return empty list when no query terms provided."""
    # Route all HTTP requests to a generic 200 empty-object response
    respx.route().mock(return_value=httpx.Response(200, json={}))
    connector = cls()
    result = await connector.fetch_latest(_EMPTY_QUERY)
    assert isinstance(result, list)


# ---------------------------------------------------------------------------
# fetch_latest with terms returns list (structure test, mocked network)
# ---------------------------------------------------------------------------

_QUERY_WITH_TERMS = IngestionQuery(query_terms=["cancer", "recall", "contamination"])


@respx.mock
@pytest.mark.parametrize("expected_id,cls", ALL_NEW_CONNECTORS)
@pytest.mark.asyncio
async def test_fetch_latest_with_terms_returns_list(expected_id, cls):
    """Connectors should return a list (possibly empty) when given terms."""
    # Return empty JSON object so connectors parse successfully but find no matches
    respx.route().mock(return_value=httpx.Response(200, json={}))
    connector = cls()
    result = await connector.fetch_latest(_QUERY_WITH_TERMS)
    assert isinstance(result, list)
    for record in result:
        assert hasattr(record, "title")
        assert hasattr(record, "source_connector_id")
        assert record.source_connector_id == expected_id


# ---------------------------------------------------------------------------
# health_check returns HealthStatus — mocked network
# ---------------------------------------------------------------------------

@respx.mock
@pytest.mark.parametrize("expected_id,cls", ALL_NEW_CONNECTORS)
@pytest.mark.asyncio
async def test_health_check_returns_status(expected_id, cls):
    """Health check should return a valid HealthStatus enum value."""
    respx.route().mock(return_value=httpx.Response(200, text="OK"))
    connector = cls()
    status = await connector.health_check()
    assert isinstance(status, HealthStatus)


# ---------------------------------------------------------------------------
# Connector repr test
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("expected_id,cls", ALL_NEW_CONNECTORS)
def test_connector_repr(expected_id, cls):
    connector = cls()
    r = repr(connector)
    assert expected_id in r


# ---------------------------------------------------------------------------
# FCA settlements specifically: should accept terms and return list
# ---------------------------------------------------------------------------

@respx.mock
@pytest.mark.asyncio
async def test_doj_fca_no_terms_returns_list():
    respx.route().mock(return_value=httpx.Response(200, json={}))
    connector = DOJFCASettlementsConnector()
    result = await connector.fetch_latest(IngestionQuery())
    assert isinstance(result, list)


# ---------------------------------------------------------------------------
# Total count test — verify we have all expected connectors
# ---------------------------------------------------------------------------

def test_new_connector_count():
    """We should have exactly 23 new federal connectors."""
    assert len(ALL_NEW_CONNECTORS) == 23
