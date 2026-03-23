"""Tests for commercial, judicial, and state connectors."""
from __future__ import annotations

import pytest

from lexgenius_pipeline.common.types import HealthStatus, SourceTier
from lexgenius_pipeline.ingestion.commercial.exa_research import ExaResearchConnector
from lexgenius_pipeline.ingestion.commercial.google_news import GoogleNewsConnector
from lexgenius_pipeline.ingestion.commercial.news_rss import NewsRSSConnector
from lexgenius_pipeline.ingestion.judicial.courtlistener import CourtListenerConnector
from lexgenius_pipeline.ingestion.judicial.pacer import PACERConnector
from lexgenius_pipeline.ingestion.judicial.regulations_gov import RegulationsGovConnector
from lexgenius_pipeline.ingestion.registry import ConnectorRegistry
from lexgenius_pipeline.ingestion.state._registry import STATE_REGISTRY, StateInfo
from lexgenius_pipeline.ingestion.state._template.courts import TemplateStateCourtConnector
from lexgenius_pipeline.ingestion.state.base import BaseStateConnector


# ---------------------------------------------------------------------------
# Instantiation tests
# ---------------------------------------------------------------------------

def test_google_news_instantiation():
    connector = GoogleNewsConnector()
    assert connector is not None


def test_news_rss_instantiation():
    connector = NewsRSSConnector()
    assert connector is not None


def test_exa_research_instantiation():
    connector = ExaResearchConnector()
    assert connector is not None


def test_pacer_instantiation():
    connector = PACERConnector()
    assert connector is not None


def test_courtlistener_instantiation():
    connector = CourtListenerConnector()
    assert connector is not None


def test_regulations_gov_instantiation():
    connector = RegulationsGovConnector()
    assert connector is not None


def test_template_state_connector_instantiation():
    connector = TemplateStateCourtConnector()
    assert connector is not None


# ---------------------------------------------------------------------------
# connector_id tests
# ---------------------------------------------------------------------------

def test_google_news_connector_id():
    assert GoogleNewsConnector.connector_id == "commercial.google_news"


def test_news_rss_connector_id():
    assert NewsRSSConnector.connector_id == "commercial.news_rss"


def test_exa_research_connector_id():
    assert ExaResearchConnector.connector_id == "commercial.exa_research"


def test_pacer_connector_id():
    assert PACERConnector.connector_id == "judicial.pacer.rss"


def test_courtlistener_connector_id():
    assert CourtListenerConnector.connector_id == "judicial.courtlistener"


def test_regulations_gov_connector_id():
    assert RegulationsGovConnector.connector_id == "judicial.regulations_gov"


# ---------------------------------------------------------------------------
# source_tier tests
# ---------------------------------------------------------------------------

def test_commercial_connectors_have_commercial_tier():
    for cls in (GoogleNewsConnector, NewsRSSConnector, ExaResearchConnector):
        assert cls.source_tier == SourceTier.COMMERCIAL, f"{cls.__name__} wrong tier"


def test_judicial_connectors_have_judicial_tier():
    for cls in (PACERConnector, CourtListenerConnector, RegulationsGovConnector):
        assert cls.source_tier == SourceTier.JUDICIAL, f"{cls.__name__} wrong tier"


def test_state_base_connector_tier():
    assert BaseStateConnector.source_tier == SourceTier.STATE


def test_template_state_connector_tier():
    assert TemplateStateCourtConnector.source_tier == SourceTier.STATE


# ---------------------------------------------------------------------------
# PACER stub tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pacer_fetch_returns_empty():
    from lexgenius_pipeline.common.models import IngestionQuery
    connector = PACERConnector()
    result = await connector.fetch_latest(IngestionQuery(query_terms=["test"]))
    assert result == []


@pytest.mark.asyncio
async def test_pacer_health_check_degraded():
    connector = PACERConnector()
    status = await connector.health_check()
    assert status == HealthStatus.DEGRADED


def test_pacer_supports_incremental_false():
    assert PACERConnector.supports_incremental is False


# ---------------------------------------------------------------------------
# Template state connector stub tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_template_state_fetch_returns_empty():
    from lexgenius_pipeline.common.models import IngestionQuery
    connector = TemplateStateCourtConnector()
    result = await connector.fetch_latest(IngestionQuery(query_terms=["test"]))
    assert result == []


@pytest.mark.asyncio
async def test_template_state_health_check_degraded():
    connector = TemplateStateCourtConnector()
    status = await connector.health_check()
    assert status == HealthStatus.DEGRADED


# ---------------------------------------------------------------------------
# STATE_REGISTRY tests
# ---------------------------------------------------------------------------

def test_state_registry_has_50_states():
    assert len(STATE_REGISTRY) == 50


def test_state_registry_de_implemented():
    assert STATE_REGISTRY["DE"].implemented is True
    assert STATE_REGISTRY["DE"].name == "Delaware"
    assert STATE_REGISTRY["DE"].fips_code == "10"


def test_state_registry_pa_implemented():
    assert STATE_REGISTRY["PA"].implemented is True
    assert STATE_REGISTRY["PA"].name == "Pennsylvania"
    assert STATE_REGISTRY["PA"].fips_code == "42"


def test_state_registry_unimplemented_states():
    unimplemented = [s for s in STATE_REGISTRY.values() if not s.implemented]
    # 48 states should be unimplemented (DE and PA are implemented)
    assert len(unimplemented) == 48


def test_state_registry_all_codes_2_letters():
    for code, info in STATE_REGISTRY.items():
        assert len(code) == 2, f"Code {code!r} is not 2 letters"
        assert info.code == code


def test_state_info_dataclass():
    info = StateInfo("TX", "Texas", "48")
    assert info.code == "TX"
    assert info.name == "Texas"
    assert info.fips_code == "48"
    assert info.implemented is False


# ---------------------------------------------------------------------------
# ConnectorRegistry integration tests
# ---------------------------------------------------------------------------

def test_registry_register_all_commercial():
    registry = ConnectorRegistry()
    for cls in (GoogleNewsConnector, NewsRSSConnector, ExaResearchConnector):
        registry.register(cls())
    assert len(registry) == 3


def test_registry_register_all_judicial():
    registry = ConnectorRegistry()
    for cls in (PACERConnector, CourtListenerConnector, RegulationsGovConnector):
        registry.register(cls())
    assert len(registry) == 3


def test_registry_list_by_tier_commercial():
    registry = ConnectorRegistry()
    for cls in (GoogleNewsConnector, NewsRSSConnector, ExaResearchConnector):
        registry.register(cls())
    registry.register(PACERConnector())

    commercial = registry.list_by_tier(SourceTier.COMMERCIAL)
    judicial = registry.list_by_tier(SourceTier.JUDICIAL)
    assert len(commercial) == 3
    assert len(judicial) == 1


def test_registry_list_by_tier_judicial():
    registry = ConnectorRegistry()
    for cls in (PACERConnector, CourtListenerConnector, RegulationsGovConnector):
        registry.register(cls())

    judicial = registry.list_by_tier(SourceTier.JUDICIAL)
    assert len(judicial) == 3


def test_registry_duplicate_raises():
    registry = ConnectorRegistry()
    registry.register(GoogleNewsConnector())
    with pytest.raises(ValueError, match="already registered"):
        registry.register(GoogleNewsConnector())


def test_registry_contains():
    registry = ConnectorRegistry()
    registry.register(GoogleNewsConnector())
    assert "commercial.google_news" in registry
    assert "commercial.news_rss" not in registry


def test_registry_mixed_tiers():
    registry = ConnectorRegistry()
    connectors = [
        GoogleNewsConnector(),
        NewsRSSConnector(),
        ExaResearchConnector(),
        PACERConnector(),
        CourtListenerConnector(),
        RegulationsGovConnector(),
    ]
    for c in connectors:
        registry.register(c)
    assert len(registry) == 6
    assert len(registry.list_by_tier(SourceTier.COMMERCIAL)) == 3
    assert len(registry.list_by_tier(SourceTier.JUDICIAL)) == 3
    assert len(registry.list_by_tier(SourceTier.STATE)) == 0
