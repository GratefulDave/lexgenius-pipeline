from __future__ import annotations

from typing import Any

from lexgenius_pipeline.workflows.agents.base import BaseAgent
from lexgenius_pipeline.workflows.providers.base import LLMProvider
from lexgenius_pipeline.workflows.task_spec import TaskRequest, TaskResult


class ReportSynthesizerAgent(BaseAgent):
    agent_name = "report_synthesizer"

    def __init__(self, provider: LLMProvider) -> None:
        self._provider = provider

    async def execute(self, context: dict[str, Any]) -> dict[str, Any]:
        request = TaskRequest(
            task_key="report_synthesis",
            prompt="Synthesize the following agent outputs into a unified, coherent report with executive summary and key findings.",
            context=context,
        )
        result: TaskResult = await self._provider.run_one_shot(request)
        return {
            "agent": self.agent_name,
            "report": result.validated_output,
            "status": result.status,
        }
