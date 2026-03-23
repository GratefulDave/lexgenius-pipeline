from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from lexgenius_pipeline.db.models.workflow import TaskRun, WorkflowRun
from lexgenius_pipeline.db.repositories.base import AbstractRepository


class WorkflowRunRepository(AbstractRepository[WorkflowRun]):
    """CRUD + domain queries for WorkflowRun (and its TaskRuns)."""

    async def get(self, id: str) -> WorkflowRun | None:
        return await self._session.get(WorkflowRun, id)

    async def add(self, entity: WorkflowRun) -> WorkflowRun:
        self._session.add(entity)
        await self._session.flush()
        return entity

    async def delete(self, id: str) -> None:
        await self._session.execute(delete(WorkflowRun).where(WorkflowRun.id == id))

    async def list_by_status(self, status: str, *, limit: int = 50) -> list[WorkflowRun]:
        result = await self._session.execute(
            select(WorkflowRun)
            .where(WorkflowRun.status == status)
            .order_by(WorkflowRun.started_at.desc())
            .limit(limit)
        )
        return list(result.scalars())

    async def list_by_name(self, workflow_name: str, *, limit: int = 50) -> list[WorkflowRun]:
        result = await self._session.execute(
            select(WorkflowRun)
            .where(WorkflowRun.workflow_name == workflow_name)
            .order_by(WorkflowRun.started_at.desc())
            .limit(limit)
        )
        return list(result.scalars())

    async def add_task_run(self, task_run: TaskRun) -> TaskRun:
        self._session.add(task_run)
        await self._session.flush()
        return task_run

    async def list_task_runs(self, workflow_run_id: str) -> list[TaskRun]:
        result = await self._session.execute(
            select(TaskRun)
            .where(TaskRun.workflow_run_id == workflow_run_id)
            .order_by(TaskRun.started_at)
        )
        return list(result.scalars())
