from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseAgent(ABC):
    agent_name: str

    @abstractmethod
    async def execute(self, context: dict[str, Any]) -> dict[str, Any]: ...
