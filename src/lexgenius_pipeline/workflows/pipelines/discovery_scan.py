from __future__ import annotations

from collections import Counter
from typing import Any

from lexgenius_pipeline.common.models import NormalizedRecord
from lexgenius_pipeline.workflows.analysis.dedup import deduplicate_records
from lexgenius_pipeline.workflows.orchestrator import WorkflowOrchestrator
from lexgenius_pipeline.workflows.task_spec import TaskSpec


class DiscoveryScanPipeline:
    def __init__(self, orchestrator: WorkflowOrchestrator) -> None:
        self._orchestrator = orchestrator

    async def run(self, records: list[NormalizedRecord]) -> dict[str, Any]:
        unique_records = deduplicate_records(records)
        domain_counts = Counter(r.record_type.value for r in unique_records)
        source_counts = Counter(r.source_connector_id for r in unique_records)

        specs = [
            TaskSpec(
                key="discovery_scan",
                prompt="Scan the following records for emerging signals across domains. Identify patterns, anomalies, and high-priority items that warrant immediate attention.",
                context={
                    "total_records": len(unique_records),
                    "domain_breakdown": dict(domain_counts),
                    "top_sources": dict(source_counts.most_common(10)),
                    "sample_titles": [r.title for r in unique_records[:10]],
                },
            )
        ]
        results = await self._orchestrator.run_sequential(specs)
        scan_result = results.get("discovery_scan")

        return {
            "total_records": len(unique_records),
            "domain_breakdown": dict(domain_counts),
            "signals": scan_result.validated_output if scan_result else {},
            "status": scan_result.status if scan_result else "failed",
        }
