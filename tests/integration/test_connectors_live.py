from __future__ import annotations

import pytest

from lexgenius_pipeline.common.errors import ConnectorError
from lexgenius_pipeline.common.models import IngestionQuery, NormalizedRecord
from lexgenius_pipeline.common.types import RecordType
from lexgenius_pipeline.ingestion.commercial.exa_research import ExaResearchConnector
from lexgenius_pipeline.ingestion.commercial.google_news import GoogleNewsConnector
from lexgenius_pipeline.ingestion.federal.cpsc.recalls import CPSCRecallsConnector
from lexgenius_pipeline.ingestion.federal.fda.dailymed import DailyMedConnector
from lexgenius_pipeline.ingestion.federal.fda.faers import FAERSConnector
from lexgenius_pipeline.ingestion.federal.fda.maude import MAUDEConnector
from lexgenius_pipeline.ingestion.federal.fda.recalls import RecallsConnector
from lexgenius_pipeline.ingestion.federal.federal_register.notices import FederalRegisterConnector
from lexgenius_pipeline.ingestion.federal.nih.clinical_trials import ClinicalTrialsConnector
from lexgenius_pipeline.ingestion.federal.nih.pubmed import PubMedConnector

from .conftest import skip_if_no_key


def _assert_records(records: list[NormalizedRecord], expected_type: RecordType | None = None) -> None:
    assert isinstance(records, list)
    if not records:
        pytest.skip("API returned no records — may be rate-limited or empty result set")
    rec = records[0]
    assert rec.title, "title must be non-empty"
    assert rec.fingerprint, "fingerprint must be non-empty"
    assert rec.source_url, "source_url must be non-empty"
    assert rec.published_at is not None, "published_at must be set"
    if expected_type is not None:
        assert rec.record_type == expected_type, f"expected {expected_type}, got {rec.record_type}"


@pytest.mark.live
async def test_faers_fetch_live(settings):
    connector = FAERSConnector(settings)
    query = IngestionQuery(query_terms=["aspirin"])
    records = await connector.fetch_latest(query)
    print(f"Fetched {len(records)} records from {connector.connector_id}")
    _assert_records(records, RecordType.ADVERSE_EVENT)


@pytest.mark.live
async def test_maude_fetch_live(settings):
    connector = MAUDEConnector(settings)
    query = IngestionQuery(query_terms=["pacemaker"])
    records = await connector.fetch_latest(query)
    print(f"Fetched {len(records)} records from {connector.connector_id}")
    _assert_records(records, RecordType.ADVERSE_EVENT)


@pytest.mark.live
async def test_dailymed_fetch_live(settings):
    connector = DailyMedConnector(settings)
    query = IngestionQuery(query_terms=["aspirin"])
    records = await connector.fetch_latest(query)
    print(f"Fetched {len(records)} records from {connector.connector_id}")
    _assert_records(records, RecordType.REGULATION)


@pytest.mark.live
async def test_recalls_fetch_live(settings):
    connector = RecallsConnector(settings)
    query = IngestionQuery(query_terms=["acetaminophen"])
    records = await connector.fetch_latest(query)
    print(f"Fetched {len(records)} records from {connector.connector_id}")
    _assert_records(records, RecordType.RECALL)


@pytest.mark.live
async def test_pubmed_fetch_live(settings):
    connector = PubMedConnector(settings)
    query = IngestionQuery(query_terms=["aspirin adverse events"])
    records = await connector.fetch_latest(query)
    print(f"Fetched {len(records)} records from {connector.connector_id}")
    _assert_records(records, RecordType.RESEARCH)


@pytest.mark.live
async def test_clinical_trials_fetch_live(settings):
    connector = ClinicalTrialsConnector(settings)
    query = IngestionQuery(query_terms=["aspirin"])
    try:
        records = await connector.fetch_latest(query)
    except ConnectorError as exc:
        if "403" in str(exc):
            pytest.skip("ClinicalTrials.gov blocked automated access (403)")
        raise
    print(f"Fetched {len(records)} records from {connector.connector_id}")
    _assert_records(records, RecordType.RESEARCH)


@pytest.mark.live
async def test_cpsc_recalls_fetch_live(settings):
    connector = CPSCRecallsConnector(settings)
    query = IngestionQuery(query_terms=["heater"])
    records = await connector.fetch_latest(query)
    print(f"Fetched {len(records)} records from {connector.connector_id}")
    _assert_records(records, RecordType.RECALL)


@pytest.mark.live
async def test_federal_register_fetch_live(settings):
    connector = FederalRegisterConnector(settings)
    query = IngestionQuery(query_terms=["pharmaceutical"])
    records = await connector.fetch_latest(query)
    print(f"Fetched {len(records)} records from {connector.connector_id}")
    _assert_records(records, RecordType.REGULATION)


@pytest.mark.live
async def test_google_news_fetch_live(settings):
    connector = GoogleNewsConnector(settings)
    query = IngestionQuery(query_terms=["mass tort litigation"])
    records = await connector.fetch_latest(query)
    print(f"Fetched {len(records)} records from {connector.connector_id}")
    _assert_records(records, RecordType.NEWS)


@pytest.mark.live
async def test_exa_research_fetch_live(settings):
    skip_if_no_key(settings, "exa_api_key")
    connector = ExaResearchConnector(settings)
    query = IngestionQuery(query_terms=["mass tort litigation trends"])
    records = await connector.fetch_latest(query)
    print(f"Fetched {len(records)} records from {connector.connector_id}")
    _assert_records(records, RecordType.RESEARCH)
