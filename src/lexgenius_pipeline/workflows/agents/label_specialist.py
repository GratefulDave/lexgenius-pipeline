from __future__ import annotations

from typing import Any

from lexgenius_pipeline.workflows.agents.base import BaseAgent
from lexgenius_pipeline.workflows.providers.base import LLMProvider
from lexgenius_pipeline.workflows.task_spec import TaskRequest, TaskResult


class LabelSpecialistAgent(BaseAgent):
    agent_name = "label_specialist"

    def __init__(self, provider: LLMProvider) -> None:
        self._provider = provider

    async def execute(self, context: dict[str, Any]) -> dict[str, Any]:
        request = TaskRequest(
            task_key="label_analysis",
            prompt="Analyze the drug label data and identify key safety information, warnings, and recent changes.",
            context=context,
        )
        result: TaskResult = await self._provider.run_one_shot(request)
        return {
            "agent": self.agent_name,
            "analysis": result.validated_output,
            "status": result.status,
        }
