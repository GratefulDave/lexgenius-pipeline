from __future__ import annotations

import json
import time
from typing import Any

import httpx
from pydantic import BaseModel

from lexgenius_pipeline.workflows.providers.base import LLMProvider
from lexgenius_pipeline.workflows.task_spec import TaskRequest, TaskResult


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(
        self,
        api_key: str = "",
        model: str = "claude-sonnet-4-20250514",
    ) -> None:
        self._api_key = api_key
        self._model = model

    async def run_one_shot(
        self,
        request: TaskRequest,
        output_schema: type[BaseModel] | None = None,
    ) -> TaskResult:
        system_parts = ["You are a helpful assistant."]
        if output_schema is not None:
            schema = output_schema.model_json_schema()
            system_parts.append(
                f"Respond with valid JSON matching this schema:\n{json.dumps(schema, indent=2)}"
            )
        system_content = "\n\n".join(system_parts)

        user_content = request.prompt
        if request.context:
            user_content += f"\n\nContext:\n{json.dumps(request.context, indent=2)}"

        body: dict[str, Any] = {
            "model": request.model_name or self._model,
            "max_tokens": 4096,
            "system": system_content,
            "messages": [{"role": "user", "content": user_content}],
        }

        start = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=request.timeout_ms / 1000) as client:
                resp = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key": self._api_key,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                    json=body,
                )
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as exc:
            duration_ms = int((time.monotonic() - start) * 1000)
            return TaskResult(
                task_key=request.task_key,
                status="failed",
                error_message=str(exc),
                duration_ms=duration_ms,
            )

        duration_ms = int((time.monotonic() - start) * 1000)
        content = data["content"][0]["text"]
        usage = data.get("usage", {})

        validated_output: dict[str, Any] = {}
        try:
            validated_output = json.loads(content)
        except (json.JSONDecodeError, TypeError):
            validated_output = {"text": content}

        return TaskResult(
            task_key=request.task_key,
            status="succeeded",
            validated_output=validated_output,
            raw_output={"content": content},
            duration_ms=duration_ms,
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
        )
