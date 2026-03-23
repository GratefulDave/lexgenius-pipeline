from __future__ import annotations

from typing import Any

from lexgenius_pipeline.common.models import NormalizedRecord
from lexgenius_pipeline.workflows.analysis.signal_detection import calculate_prr, calculate_ror
from lexgenius_pipeline.workflows.orchestrator import WorkflowOrchestrator
from lexgenius_pipeline.workflows.task_spec import TaskSpec


class DrugInvestigationPipeline:
    def __init__(self, orchestrator: WorkflowOrchestrator) -> None:
        self._orchestrator = orchestrator

    async def run(
        self,
        drug_name: str,
        records: list[NormalizedRecord],
    ) -> dict[str, Any]:
        adverse_events = [r for r in records if r.record_type.value == "adverse_event"]
        a = len(adverse_events)
        total = len(records)
        b = total - a
        c = max(1, a * 10)
        d = max(1, total * 10)

        signal_stats: dict[str, Any] = {}
        if a > 0:
            ror = calculate_ror(a, b, c, d)
            prr = calculate_prr(a, b, c, d)
            signal_stats = {
                "ror": ror.ror,
                "ror_significant": ror.significant,
                "prr": prr.prr,
                "prr_significant": prr.significant,
                "case_count": a,
            }

        specs = [
            TaskSpec(
                key="drug_assessment",
                prompt=f"Assess the safety signal for {drug_name} based on the provided adverse event data and statistics.",
                context={
                    "drug_name": drug_name,
                    "record_count": total,
                    "adverse_event_count": a,
                    "signal_stats": signal_stats,
                    "sample_titles": [r.title for r in records[:5]],
                },
            )
        ]
        results = await self._orchestrator.run_sequential(specs)
        assessment = results.get("drug_assessment")

        return {
            "drug_name": drug_name,
            "record_count": total,
            "signal_stats": signal_stats,
            "assessment": assessment.validated_output if assessment else {},
            "status": assessment.status if assessment else "failed",
        }
