from __future__ import annotations

from lexgenius_pipeline.common.models import NormalizedRecord
from lexgenius_pipeline.workflows.task_spec import TaskRequest


async def filter_relevant_records(
    records: list[NormalizedRecord],
    query_context: str,
    provider,  # LLMProvider - typed as Any to avoid circular import
) -> list[NormalizedRecord]:
    """Filter records to those deemed relevant to query_context via LLM."""
    relevant: list[NormalizedRecord] = []
    for record in records:
        prompt = (
            f"Is this record relevant to the following context?\n"
            f"Context: {query_context}\n"
            f"Record: {record.title} - {record.summary}\n"
            f"Answer only YES or NO."
        )
        request = TaskRequest(task_key=f"relevancy_{record.fingerprint[:8]}", prompt=prompt)
        result = await provider.run_one_shot(request)
        if result.status == "succeeded":
            answer = result.validated_output.get("answer", str(result.raw_output)).upper()
            if "YES" in answer:
                relevant.append(record)
    return relevant
