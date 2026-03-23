from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from lexgenius_pipeline.db.models.signals import Signal
from lexgenius_pipeline.db.repositories.base import AbstractRepository


class SignalRepository(AbstractRepository[Signal]):
    """CRUD + domain queries for Signal."""

    async def get(self, id: str) -> Signal | None:
        return await self._session.get(Signal, id)

    async def add(self, entity: Signal) -> Signal:
        self._session.add(entity)
        await self._session.flush()
        return entity

    async def delete(self, id: str) -> None:
        await self._session.execute(delete(Signal).where(Signal.id == id))

    async def list_by_record(self, raw_record_id: str) -> list[Signal]:
        result = await self._session.execute(
            select(Signal)
            .where(Signal.raw_record_id == raw_record_id)
            .order_by(Signal.relevance_score.desc())
        )
        return list(result.scalars())

    async def list_by_strength(self, strength: str, *, limit: int = 100) -> list[Signal]:
        result = await self._session.execute(
            select(Signal)
            .where(Signal.strength == strength)
            .order_by(Signal.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars())

    async def list_by_type(self, signal_type: str, *, limit: int = 100) -> list[Signal]:
        result = await self._session.execute(
            select(Signal)
            .where(Signal.signal_type == signal_type)
            .order_by(Signal.relevance_score.desc())
            .limit(limit)
        )
        return list(result.scalars())
