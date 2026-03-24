from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class TaskSpec(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    key: str
    prompt: str
    context: dict[str, Any] = Field(default_factory=dict)
    output_schema: type[BaseModel] | None = None
    timeout_ms: int = 30000


class TaskRequest(BaseModel):
    task_key: str
    prompt: str
    context: dict[str, Any] = Field(default_factory=dict)
    timeout_ms: int = 30000
    model_name: str = ""
    temperature: float = 0.2


class TaskResult(BaseModel):
    task_key: str
    status: Literal["succeeded", "failed", "timed_out"]
    validated_output: dict[str, Any] = Field(default_factory=dict)
    raw_output: dict[str, Any] = Field(default_factory=dict)
    error_message: str = ""
    duration_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_micros: int = 0
