from __future__ import annotations

import importlib.resources
from datetime import date
from typing import Any

from lexgenius_pipeline.workflows.orchestrator import WorkflowOrchestrator
from lexgenius_pipeline.workflows.task_spec import TaskSpec


def _load_prompt(filename: str) -> str:
    prompts_path = (
        importlib.resources.files("lexgenius_pipeline")
        .joinpath("workflows/prompts/daily_report_v1")
        .joinpath(filename)
    )
    return prompts_path.read_text(encoding="utf-8")


class DailyReportPipeline:
    def __init__(self, orchestrator: WorkflowOrchestrator) -> None:
        self._orchestrator = orchestrator

    async def run(
        self,
        report_date: date,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        ctx = context or {}

        # Phase 1: parallel fanout
        fanout_specs = [
            TaskSpec(
                key="filings",
                prompt=_load_prompt("filings_minion.txt"),
                context=ctx,
            ),
            TaskSpec(
                key="alerts",
                prompt=_load_prompt("alerts_minion.txt"),
                context=ctx,
            ),
            TaskSpec(
                key="ad_trends",
                prompt=_load_prompt("ad_trends_minion.txt"),
                context=ctx,
            ),
        ]
        phase1 = await self._orchestrator.run_parallel(fanout_specs)

        # Phase 2: sequential summary using phase 1 results
        summary_context = {
            "date": report_date.isoformat(),
            "filings": phase1.get("filings", {}).validated_output if "filings" in phase1 else {},
            "alerts": phase1.get("alerts", {}).validated_output if "alerts" in phase1 else {},
            "ad_trends": phase1.get("ad_trends", {}).validated_output if "ad_trends" in phase1 else {},
            **ctx,
        }
        summary_specs = [
            TaskSpec(
                key="summary",
                prompt=_load_prompt("summary_minion.txt"),
                context=summary_context,
            )
        ]
        phase2 = await self._orchestrator.run_sequential(summary_specs)

        return {
            "date": report_date.isoformat(),
            "summary": phase2.get("summary", {}).validated_output if "summary" in phase2 else {},
            "top_filings": phase1.get("filings", {}).validated_output if "filings" in phase1 else {},
            "alerts": phase1.get("alerts", {}).validated_output if "alerts" in phase1 else {},
            "ad_trends": phase1.get("ad_trends", {}).validated_output if "ad_trends" in phase1 else {},
        }
