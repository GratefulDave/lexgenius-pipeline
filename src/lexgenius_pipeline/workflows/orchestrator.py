from __future__ import annotations

import asyncio

from lexgenius_pipeline.workflows.providers.base import LLMProvider
from lexgenius_pipeline.workflows.task_spec import TaskRequest, TaskResult, TaskSpec


class WorkflowOrchestrator:
    def __init__(self, provider: LLMProvider, max_workers: int = 4) -> None:
        self._provider = provider
        self._max_workers = max_workers
        self._semaphore = asyncio.Semaphore(max_workers)

    async def run_parallel(
        self,
        task_specs: list[TaskSpec],
        timeout_ms: int = 60000,
    ) -> dict[str, TaskResult]:
        results: dict[str, TaskResult] = {}
        async with asyncio.TaskGroup() as tg:
            for spec in task_specs:
                tg.create_task(self._run_one(spec, timeout_ms, results))
        return results

    async def _run_one(
        self,
        spec: TaskSpec,
        timeout_ms: int,
        results: dict[str, TaskResult],
    ) -> None:
        async with self._semaphore:
            timeout_s = (spec.timeout_ms or timeout_ms) / 1000
            try:
                result = await asyncio.wait_for(
                    self._execute(spec),
                    timeout=timeout_s,
                )
                results[spec.key] = result
            except asyncio.TimeoutError:
                results[spec.key] = TaskResult(
                    task_key=spec.key,
                    status="timed_out",
                    error_message=f"Timed out after {timeout_s}s",
                )
            except Exception as e:
                results[spec.key] = TaskResult(
                    task_key=spec.key,
                    status="failed",
                    error_message=str(e),
                )

    async def _execute(self, spec: TaskSpec) -> TaskResult:
        request = TaskRequest(
            task_key=spec.key,
            prompt=spec.prompt,
            context=spec.context,
            timeout_ms=spec.timeout_ms,
        )
        return await self._provider.run_one_shot(request, spec.output_schema)

    async def run_sequential(self, task_specs: list[TaskSpec]) -> dict[str, TaskResult]:
        results: dict[str, TaskResult] = {}
        for spec in task_specs:
            try:
                results[spec.key] = await self._execute(spec)
            except Exception as e:
                results[spec.key] = TaskResult(
                    task_key=spec.key,
                    status="failed",
                    error_message=str(e),
                )
        return results
