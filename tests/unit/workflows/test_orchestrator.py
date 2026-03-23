from __future__ import annotations

import asyncio

import pytest

from lexgenius_pipeline.workflows.orchestrator import WorkflowOrchestrator
from lexgenius_pipeline.workflows.providers.fixture import FixtureProvider
from lexgenius_pipeline.workflows.task_spec import TaskSpec


@pytest.fixture
def fixture_provider():
    return FixtureProvider(
        responses={
            "task_a": {"result": "a"},
            "task_b": {"result": "b"},
        }
    )


@pytest.fixture
def orchestrator(fixture_provider):
    return WorkflowOrchestrator(fixture_provider, max_workers=4)


async def test_run_parallel_returns_all_results(orchestrator):
    specs = [
        TaskSpec(key="task_a", prompt="Do A"),
        TaskSpec(key="task_b", prompt="Do B"),
    ]
    results = await orchestrator.run_parallel(specs)
    assert set(results.keys()) == {"task_a", "task_b"}
    assert results["task_a"].status == "succeeded"
    assert results["task_a"].validated_output == {"result": "a"}
    assert results["task_b"].status == "succeeded"
    assert results["task_b"].validated_output == {"result": "b"}


async def test_run_parallel_timeout():
    from pydantic import BaseModel
    from lexgenius_pipeline.workflows.providers.base import LLMProvider
    from lexgenius_pipeline.workflows.task_spec import TaskRequest, TaskResult

    class SlowProvider(LLMProvider):
        name = "slow"

        async def run_one_shot(
            self,
            request: TaskRequest,
            output_schema: type[BaseModel] | None = None,
        ) -> TaskResult:
            await asyncio.sleep(10)
            return TaskResult(task_key=request.task_key, status="succeeded")

    orch = WorkflowOrchestrator(SlowProvider(), max_workers=2)
    specs = [TaskSpec(key="slow_task", prompt="wait", timeout_ms=100)]
    results = await orch.run_parallel(specs, timeout_ms=100)
    assert results["slow_task"].status == "timed_out"


async def test_run_sequential_runs_in_order(orchestrator):
    specs = [
        TaskSpec(key="task_a", prompt="Do A"),
        TaskSpec(key="task_b", prompt="Do B"),
    ]
    results = await orchestrator.run_sequential(specs)
    assert results["task_a"].status == "succeeded"
    assert results["task_b"].status == "succeeded"
    assert results["task_a"].validated_output == {"result": "a"}
    assert results["task_b"].validated_output == {"result": "b"}


async def test_run_sequential_handles_exception():
    from pydantic import BaseModel
    from lexgenius_pipeline.workflows.providers.base import LLMProvider
    from lexgenius_pipeline.workflows.task_spec import TaskRequest, TaskResult

    class BrokenProvider(LLMProvider):
        name = "broken"

        async def run_one_shot(
            self,
            request: TaskRequest,
            output_schema: type[BaseModel] | None = None,
        ) -> TaskResult:
            raise RuntimeError("provider exploded")

    orch = WorkflowOrchestrator(BrokenProvider())
    specs = [TaskSpec(key="bad_task", prompt="explode")]
    results = await orch.run_sequential(specs)
    assert results["bad_task"].status == "failed"
    assert "provider exploded" in results["bad_task"].error_message
