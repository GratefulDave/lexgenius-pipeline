from __future__ import annotations

import json
import time
from typing import Any

import httpx
from pydantic import BaseModel

from lexgenius_pipeline.workflows.providers.base import LLMProvider
from lexgenius_pipeline.workflows.task_spec import TaskRequest, TaskResult


class OpenAIProvider(LLMProvider):
    name = "openai"

    def __init__(self, api_key: str = "", model: str = "gpt-4o-mini") -> None:
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

        messages = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": user_content},
        ]

        body: dict[str, Any] = {
            "model": request.model_name or self._model,
            "messages": messages,
            "temperature": request.temperature,
        }

        start = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=request.timeout_ms / 1000) as client:
                resp = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
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
        content = data["choices"][0]["message"]["content"]
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
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
        )
