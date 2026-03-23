from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import BaseModel

from lexgenius_pipeline.workflows.task_spec import TaskRequest, TaskResult


class LLMProvider(ABC):
    name: str = "base"

    @abstractmethod
    async def run_one_shot(
        self,
        request: TaskRequest,
        output_schema: type[BaseModel] | None = None,
    ) -> TaskResult: ...
