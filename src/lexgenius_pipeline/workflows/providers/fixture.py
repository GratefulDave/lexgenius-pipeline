from __future__ import annotations

from pydantic import BaseModel

from lexgenius_pipeline.workflows.providers.base import LLMProvider
from lexgenius_pipeline.workflows.task_spec import TaskRequest, TaskResult


class FixtureProvider(LLMProvider):
    name = "fixture"

    def __init__(self, responses: dict[str, dict] | None = None) -> None:
        self._responses: dict[str, dict] = responses or {}

    async def run_one_shot(
        self,
        request: TaskRequest,
        output_schema: type[BaseModel] | None = None,
    ) -> TaskResult:
        return TaskResult(
            task_key=request.task_key,
            status="succeeded",
            validated_output=self._responses.get(request.task_key, {}),
        )
