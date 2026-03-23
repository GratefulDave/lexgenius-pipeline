from __future__ import annotations

import asyncio
from typing import Any


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Lambda handler for drug safety investigation.

    Event format:
    {
        "drug_name": "aspirin",                           # required
        "connector_ids": ["federal.fda.faers"],           # optional, queries all if omitted
        "max_records": 500                                # optional, default 500
    }
    """
    return asyncio.run(_run(event))


async def _run(event: dict[str, Any]) -> dict[str, Any]:
    from lexgenius_pipeline.settings import get_settings
    from lexgenius_pipeline.db.engine import create_engine, create_session_factory
    from lexgenius_pipeline.db.repositories import RawRecordRepository
    from lexgenius_pipeline.common.models import NormalizedRecord
    from lexgenius_pipeline.common.types import RecordType
    from lexgenius_pipeline.workflows.orchestrator import WorkflowOrchestrator
    from lexgenius_pipeline.workflows.providers.anthropic import AnthropicProvider
    from lexgenius_pipeline.workflows.providers.openai import OpenAIProvider
    from lexgenius_pipeline.workflows.pipelines.drug_investigation import DrugInvestigationPipeline

    drug_name: str = event["drug_name"]
    connector_ids: list[str] | None = event.get("connector_ids")
    max_records: int = event.get("max_records", 500)

    settings = get_settings()
    engine = create_engine(settings)
    sf = create_session_factory(engine)

    async with sf() as session:
        repo = RawRecordRepository(session)
        if connector_ids:
            raw_records = []
            per_connector = max(1, max_records // len(connector_ids))
            for cid in connector_ids:
                raw_records.extend(await repo.list_by_connector(cid, limit=per_connector))
        else:
            raw_records = await repo.list_by_type("adverse_event", limit=max_records)

    await engine.dispose()

    records = [
        NormalizedRecord(
            title=r.title,
            summary=r.summary,
            record_type=RecordType(r.record_type),
            source_connector_id=r.connector_id,
            source_label=r.source_label,
            source_url=r.source_url,
            citation_url=r.citation_url,
            published_at=r.published_at,
            confidence=r.confidence,
            fingerprint=r.fingerprint,
            metadata=r.metadata_,
            raw_payload=r.raw_payload,
        )
        for r in raw_records
    ]

    provider_name = settings.llm_provider
    if provider_name == "anthropic":
        provider = AnthropicProvider(api_key=settings.llm_api_key)
    else:
        provider = OpenAIProvider(api_key=settings.llm_api_key)

    orchestrator = WorkflowOrchestrator(provider)
    pipeline = DrugInvestigationPipeline(orchestrator)
    result = await pipeline.run(drug_name, records)
    return {"statusCode": 200, "body": result}
