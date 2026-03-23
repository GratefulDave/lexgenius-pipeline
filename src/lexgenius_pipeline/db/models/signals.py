from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from lexgenius_pipeline.db.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class Signal(Base):
    __tablename__ = "signals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    raw_record_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("raw_records.id", ondelete="CASCADE"), nullable=False, index=True
    )
    signal_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    strength: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(1024), nullable=False)
    summary: Mapped[str] = mapped_column(String(4096), nullable=False)
    entity_tags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    relevance_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )

    __table_args__ = (
        Index("ix_signals_type_strength", "signal_type", "strength"),
    )
