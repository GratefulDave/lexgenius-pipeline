from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from lexgenius_pipeline.db.models.ingestion import RawRecord
from lexgenius_pipeline.db.repositories.base import AbstractRepository


class RawRecordRepository(AbstractRepository[RawRecord]):
    """CRUD + domain queries for RawRecord."""

    async def get(self, id: str) -> RawRecord | None:
        result = await self._session.get(RawRecord, id)
        return result

    async def add(self, entity: RawRecord) -> RawRecord:
        self._session.add(entity)
        await self._session.flush()
        return entity

    async def delete(self, id: str) -> None:
        await self._session.execute(delete(RawRecord).where(RawRecord.id == id))

    async def get_by_fingerprint(self, fingerprint: str) -> RawRecord | None:
        result = await self._session.execute(
            select(RawRecord).where(RawRecord.fingerprint == fingerprint)
        )
        return result.scalar_one_or_none()

    async def fingerprint_exists(self, fingerprint: str) -> bool:
        return await self.get_by_fingerprint(fingerprint) is not None

    async def list_by_connector(
        self,
        connector_id: str,
        *,
        since: datetime | None = None,
        limit: int = 100,
    ) -> list[RawRecord]:
        stmt = select(RawRecord).where(RawRecord.connector_id == connector_id)
        if since is not None:
            stmt = stmt.where(RawRecord.published_at >= since)
        stmt = stmt.order_by(RawRecord.published_at.desc()).limit(limit)
        result = await self._session.execute(stmt)
        return list(result.scalars())

    async def list_by_type(self, record_type: str, *, limit: int = 100) -> list[RawRecord]:
        result = await self._session.execute(
            select(RawRecord)
            .where(RawRecord.record_type == record_type)
            .order_by(RawRecord.published_at.desc())
            .limit(limit)
        )
        return list(result.scalars())
