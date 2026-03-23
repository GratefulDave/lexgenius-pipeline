from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Generic, TypeVar

from sqlalchemy.ext.asyncio import AsyncSession

T = TypeVar("T")


class AbstractRepository(ABC, Generic[T]):
    """Generic async repository base."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @abstractmethod
    async def get(self, id: str) -> T | None:
        """Return the entity with *id*, or None if not found."""

    @abstractmethod
    async def add(self, entity: T) -> T:
        """Persist a new entity and return it."""

    @abstractmethod
    async def delete(self, id: str) -> None:
        """Remove the entity with *id*."""
