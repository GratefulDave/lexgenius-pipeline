from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from lexgenius_pipeline.db.models.ingestion import SourceCheckpoint
from lexgenius_pipeline.db.repositories.base import AbstractRepository


class CheckpointRepository(AbstractRepository[SourceCheckpoint]):
    """CRUD + domain queries for SourceCheckpoint."""

    async def get(self, id: str) -> SourceCheckpoint | None:
        return await self._session.get(SourceCheckpoint, id)

    async def add(self, entity: SourceCheckpoint) -> SourceCheckpoint:
        self._session.add(entity)
        await self._session.flush()
        return entity

    async def delete(self, id: str) -> None:
        await self._session.execute(
            delete(SourceCheckpoint).where(SourceCheckpoint.id == id)
        )

    async def get_by_scope(
        self, scope_key: str, connector_id: str
    ) -> SourceCheckpoint | None:
        result = await self._session.execute(
            select(SourceCheckpoint).where(
                SourceCheckpoint.scope_key == scope_key,
                SourceCheckpoint.connector_id == connector_id,
            )
        )
        return result.scalar_one_or_none()

    async def upsert(self, checkpoint: SourceCheckpoint) -> SourceCheckpoint:
        """Update existing checkpoint or insert a new one."""
        existing = await self.get_by_scope(checkpoint.scope_key, checkpoint.connector_id)
        if existing is None:
            return await self.add(checkpoint)
        existing.last_fetched_at = checkpoint.last_fetched_at
        existing.last_record_date = checkpoint.last_record_date
        await self._session.flush()
        return existing
