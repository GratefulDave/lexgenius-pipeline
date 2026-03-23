from __future__ import annotations

import asyncio
import json
from typing import Any


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """AWS Lambda handler for data ingestion.

    Event format:
    {
        "connector_ids": ["federal.fda.faers", "federal.fda.recalls"],  # optional, runs all if omitted
        "query_terms": ["aspirin"],  # optional
        "max_records": 100  # optional, default 1000
    }
    """
    return asyncio.run(_run(event))


async def _run(event: dict[str, Any]) -> dict[str, Any]:
    from lexgenius_pipeline.settings import get_settings
    from lexgenius_pipeline.db.engine import create_engine, create_session_factory
    from lexgenius_pipeline.ingestion.registry import ConnectorRegistry
    from lexgenius_pipeline.ingestion.runner import IngestionRunner
    from lexgenius_pipeline.common.models import IngestionQuery
    # Import all connectors
    from lexgenius_pipeline.ingestion.federal.fda import FAERSConnector, MAUDEConnector, DailyMedConnector, RecallsConnector
    from lexgenius_pipeline.ingestion.federal.nih import PubMedConnector, ClinicalTrialsConnector
    from lexgenius_pipeline.ingestion.federal.cpsc import CPSCRecallsConnector
    from lexgenius_pipeline.ingestion.federal.epa import EPAEnforcementConnector
    from lexgenius_pipeline.ingestion.federal.federal_register import FederalRegisterConnector
    from lexgenius_pipeline.ingestion.federal.congress import CongressConnector

    settings = get_settings()
    engine = create_engine(settings)
    sf = create_session_factory(engine)

    # Register all connectors
    registry = ConnectorRegistry()
    connectors = [
        FAERSConnector(settings), MAUDEConnector(settings), DailyMedConnector(settings),
        RecallsConnector(settings), PubMedConnector(settings), ClinicalTrialsConnector(settings),
        CPSCRecallsConnector(settings), EPAEnforcementConnector(settings),
        FederalRegisterConnector(settings), CongressConnector(settings),
    ]
    for c in connectors:
        registry.register(c)

    query = IngestionQuery(
        connector_ids=event.get("connector_ids"),
        query_terms=event.get("query_terms"),
        max_records=event.get("max_records", 1000),
    )
    runner = IngestionRunner(registry, sf)
    metrics = await runner.run_all(query)
    await engine.dispose()

    return {
        "statusCode": 200,
        "body": {
            "records_fetched": metrics.records_fetched,
            "records_written": metrics.records_written,
            "duplicates_skipped": metrics.duplicates_skipped,
            "errors": metrics.errors,
            "duration_ms": metrics.duration_ms,
        }
    }
