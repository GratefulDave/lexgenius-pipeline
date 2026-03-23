from __future__ import annotations

import asyncio
from typing import Any


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Lambda handler for daily report generation.

    Event format:
    {
        "report_date": "2026-03-23",  # optional, defaults to today
        "llm_provider": "anthropic"   # optional, defaults to settings.llm_provider
    }
    """
    return asyncio.run(_run(event))


async def _run(event: dict[str, Any]) -> dict[str, Any]:
    from datetime import date

    from lexgenius_pipeline.settings import get_settings
    from lexgenius_pipeline.workflows.orchestrator import WorkflowOrchestrator
    from lexgenius_pipeline.workflows.providers.anthropic import AnthropicProvider
    from lexgenius_pipeline.workflows.providers.openai import OpenAIProvider
    from lexgenius_pipeline.workflows.pipelines.daily_report import DailyReportPipeline

    settings = get_settings()
    provider_name = event.get("llm_provider", settings.llm_provider)
    if provider_name == "anthropic":
        provider = AnthropicProvider(api_key=settings.llm_api_key)
    else:
        provider = OpenAIProvider(api_key=settings.llm_api_key)

    orchestrator = WorkflowOrchestrator(provider)
    pipeline = DailyReportPipeline(orchestrator)
    report_date_str = event.get("report_date", str(date.today()))
    report_date = date.fromisoformat(report_date_str)
    result = await pipeline.run(report_date)
    return {"statusCode": 200, "body": result}
