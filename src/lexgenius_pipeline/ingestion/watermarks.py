from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from lexgenius_pipeline.common.models import Watermark
from lexgenius_pipeline.db.models.ingestion import SourceCheckpoint
from lexgenius_pipeline.db.repositories.checkpoint_repo import CheckpointRepository


async def get_watermark(
    session: AsyncSession,
    connector_id: str,
    scope_key: str,
) -> Watermark | None:
    """Read the watermark for a connector+scope, or None if first run."""
    repo = CheckpointRepository(session)
    cp = await repo.get_by_scope(scope_key, connector_id)
    if cp is None:
        return None
    return Watermark(
        scope_key=cp.scope_key,
        connector_id=cp.connector_id,
        last_fetched_at=cp.last_fetched_at,
        last_record_date=cp.last_record_date,
    )


async def update_watermark(
    session: AsyncSession,
    connector_id: str,
    scope_key: str,
    last_record_date: datetime | None = None,
) -> None:
    """Create or update the watermark for a connector+scope."""
    repo = CheckpointRepository(session)
    now = datetime.now(timezone.utc)
    checkpoint = SourceCheckpoint(
        scope_key=scope_key,
        connector_id=connector_id,
        last_fetched_at=now,
        last_record_date=last_record_date,
    )
    await repo.upsert(checkpoint)
