from __future__ import annotations

import asyncio
import json

import click

from lexgenius_pipeline.ingestion.registry import ConnectorRegistry
from lexgenius_pipeline.ingestion.runner import IngestionRunner


@click.group()
def main() -> None:
    """LexGenius Pipeline CLI."""


@main.command()
@click.option("--sources", default=None, help="Comma-separated connector IDs")
@click.option("--all", "run_all", is_flag=True, help="Run all connectors")
def ingest(sources: str | None, run_all: bool) -> None:
    """Run ingestion connectors."""

    async def _run() -> None:
        registry = ConnectorRegistry()
        runner = IngestionRunner(registry)
        connector_ids: list[str] | None = None
        if run_all:
            connector_ids = None
        elif sources:
            connector_ids = [s.strip() for s in sources.split(",")]
        else:
            click.echo("Specify --sources or --all", err=True)
            return
        metrics = await runner.run(connector_ids=connector_ids)
        click.echo(json.dumps(metrics.model_dump(), indent=2))

    asyncio.run(_run())


@main.command()
@click.argument("pipeline", type=click.Choice(["daily", "investigate", "discover"]))
def report(pipeline: str) -> None:
    """Run a workflow pipeline."""

    async def _run() -> None:
        from datetime import date

        from lexgenius_pipeline.workflows.orchestrator import WorkflowOrchestrator
        from lexgenius_pipeline.workflows.pipelines.daily_report import DailyReportPipeline
        from lexgenius_pipeline.workflows.pipelines.discovery_scan import DiscoveryScanPipeline
        from lexgenius_pipeline.workflows.providers.fixture import FixtureProvider

        provider = FixtureProvider()
        orchestrator = WorkflowOrchestrator(provider)

        if pipeline == "daily":
            p = DailyReportPipeline(orchestrator)
            result = await p.run(report_date=date.today())
        elif pipeline == "discover":
            p2 = DiscoveryScanPipeline(orchestrator)
            result = await p2.run(records=[])
        else:
            click.echo(f"Pipeline '{pipeline}' requires additional arguments.", err=True)
            return

        click.echo(json.dumps(result, indent=2))

    asyncio.run(_run())


@main.command()
def health() -> None:
    """Check health of all connectors."""

    async def _run() -> None:
        registry = ConnectorRegistry()
        connectors = registry.list_all()
        results: dict[str, str] = {}
        for connector in connectors:
            try:
                ok = await connector.health_check()
                results[connector.connector_id] = "healthy" if ok else "degraded"
            except Exception as exc:
                results[connector.connector_id] = f"failed: {exc}"
        click.echo(json.dumps(results, indent=2))

    asyncio.run(_run())
