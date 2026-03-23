from __future__ import annotations

from datetime import date

import pytest

from lexgenius_pipeline.workflows.orchestrator import WorkflowOrchestrator
from lexgenius_pipeline.workflows.pipelines.daily_report import DailyReportPipeline
from lexgenius_pipeline.workflows.providers.fixture import FixtureProvider


@pytest.fixture
def fixture_provider():
    return FixtureProvider(
        responses={
            "filings": {"top_filings": ["filing1", "filing2"]},
            "alerts": {"alerts": ["alert1"]},
            "ad_trends": {"trends": ["trend1"]},
            "summary": {"executive_summary": "Daily summary text."},
        }
    )


@pytest.fixture
def orchestrator(fixture_provider):
    return WorkflowOrchestrator(fixture_provider)


async def test_daily_report_pipeline_returns_valid_payload(orchestrator):
    pipeline = DailyReportPipeline(orchestrator)
    result = await pipeline.run(report_date=date(2024, 1, 15))

    assert result["date"] == "2024-01-15"
    assert "summary" in result
    assert "top_filings" in result
    assert "alerts" in result
    assert "ad_trends" in result


async def test_daily_report_pipeline_with_context(orchestrator):
    pipeline = DailyReportPipeline(orchestrator)
    result = await pipeline.run(
        report_date=date(2024, 1, 15),
        context={"client_id": "test-client"},
    )
    assert result["date"] == "2024-01-15"
    assert isinstance(result["top_filings"], dict)
    assert isinstance(result["alerts"], dict)
