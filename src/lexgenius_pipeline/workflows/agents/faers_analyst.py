from __future__ import annotations

from typing import Any

from lexgenius_pipeline.workflows.agents.base import BaseAgent
from lexgenius_pipeline.workflows.analysis.signal_detection import calculate_prr, calculate_ror
from lexgenius_pipeline.workflows.providers.base import LLMProvider
from lexgenius_pipeline.workflows.task_spec import TaskRequest, TaskResult


class FAERSAnalystAgent(BaseAgent):
    agent_name = "faers_analyst"

    def __init__(self, provider: LLMProvider) -> None:
        self._provider = provider

    async def execute(self, context: dict[str, Any]) -> dict[str, Any]:
        signal_stats: dict[str, Any] = {}
        a = context.get("a", 0)
        b = context.get("b", 0)
        c = context.get("c", 0)
        d = context.get("d", 0)
        if all(isinstance(v, int) for v in [a, b, c, d]) and (a + b + c + d) > 0:
            ror = calculate_ror(a, b, c, d)
            prr = calculate_prr(a, b, c, d)
            signal_stats = {
                "ror": ror.ror,
                "ror_significant": ror.significant,
                "prr": prr.prr,
                "prr_significant": prr.significant,
                "case_count": a,
            }

        request = TaskRequest(
            task_key="faers_analysis",
            prompt="Analyze the adverse event data and provide a signal assessment.",
            context={**context, "signal_stats": signal_stats},
        )
        result: TaskResult = await self._provider.run_one_shot(request)
        return {
            "agent": self.agent_name,
            "signal_stats": signal_stats,
            "assessment": result.validated_output,
            "status": result.status,
        }
