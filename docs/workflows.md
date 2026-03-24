# Workflow System Guide

The workflow system applies LLM-powered analysis to ingested records and produces structured reports. It is composed of four layers: LLM providers, an orchestrator, analysis engines, and pipelines.

## LLM Provider Abstraction

All LLM calls go through the `LLMProvider` ABC (`workflows/providers/base.py`). This makes it trivial to switch providers or use a deterministic fixture in tests.

```python
from abc import ABC, abstractmethod
from pydantic import BaseModel
from lexgenius_pipeline.workflows.task_spec import TaskRequest, TaskResult

class LLMProvider(ABC):
    name: str = "base"

    @abstractmethod
    async def run_one_shot(
        self,
        request: TaskRequest,
        output_schema: type[BaseModel] | None = None,
    ) -> TaskResult: ...
```

### Available Providers

| Provider | Class | `LGP_LLM_PROVIDER` value | Notes |
|---|---|---|---|
| OpenAI | `OpenAIProvider` | `openai` | Default; uses `gpt-4o-mini` by default |
| Anthropic | `AnthropicProvider` | `anthropic` | Uses `claude-sonnet-4-20250514` by default |
| Fixture | `FixtureProvider` | `fixture` | Returns canned responses; for tests and offline use |

### Selecting a Provider

```python
from lexgenius_pipeline.settings import get_settings
from lexgenius_pipeline.workflows.providers.anthropic import AnthropicProvider
from lexgenius_pipeline.workflows.providers.openai import OpenAIProvider
from lexgenius_pipeline.workflows.providers.fixture import FixtureProvider

settings = get_settings()

if settings.llm_provider == "anthropic":
    provider = AnthropicProvider(api_key=settings.llm_api_key, model=settings.llm_model)
elif settings.llm_provider == "openai":
    provider = OpenAIProvider(api_key=settings.llm_api_key, model=settings.llm_model)
else:
    provider = FixtureProvider()
```

### Provider Behaviour

Both real providers:
- Accept a `TaskRequest` with `prompt`, `context` (injected as JSON after the prompt), and optional `output_schema`.
- If `output_schema` is provided, instruct the model to respond with valid JSON matching the schema.
- Return a `TaskResult` with `status`, `validated_output` (parsed JSON dict), token counts, and cost in microdollars.
- Handle HTTP errors gracefully: return `status="failed"` with `error_message` rather than raising.

## TaskSpec / TaskRequest / TaskResult Contracts

### TaskSpec

`TaskSpec` is the input type for `WorkflowOrchestrator`. It describes a single LLM task.

```python
class TaskSpec(BaseModel):
    key: str                              # unique identifier for this task within a run
    prompt: str                           # the instruction to the LLM
    context: dict[str, Any] = {}          # structured data injected as JSON context
    output_schema: type[BaseModel] | None # if set, LLM is prompted for structured JSON
    timeout_ms: int = 30000               # per-task timeout; overrides orchestrator default
```

### TaskRequest

`TaskRequest` is the internal wire type passed to `LLMProvider.run_one_shot()`. It is constructed from `TaskSpec` by the orchestrator.

```python
class TaskRequest(BaseModel):
    task_key: str
    prompt: str
    context: dict[str, Any] = {}
    timeout_ms: int = 30000
    model_name: str = ""        # overrides provider default if set
    temperature: float = 0.2
```

### TaskResult

`TaskResult` is returned by every LLM call.

```python
class TaskResult(BaseModel):
    task_key: str
    status: Literal["succeeded", "failed", "timed_out"]
    validated_output: dict[str, Any] = {}   # parsed JSON from the model
    raw_output: dict[str, Any] = {}         # raw response text keyed by "content"
    error_message: str = ""
    duration_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_micros: int = 0                    # cost in millionths of a dollar
```

## WorkflowOrchestrator

`WorkflowOrchestrator` (`workflows/orchestrator.py`) implements the fanout+reduce pattern used by all pipelines.

```python
from lexgenius_pipeline.workflows.orchestrator import WorkflowOrchestrator
from lexgenius_pipeline.workflows.providers.anthropic import AnthropicProvider

provider = AnthropicProvider(api_key="sk-ant-...")
orchestrator = WorkflowOrchestrator(provider, max_workers=4)
```

### Methods

| Method | Description |
|---|---|
| `run_parallel(task_specs, timeout_ms)` | Executes all specs concurrently under a semaphore; returns `dict[str, TaskResult]` keyed by `spec.key` |
| `run_sequential(task_specs)` | Executes specs one at a time in order; returns `dict[str, TaskResult]` |

### Fanout+Reduce Pattern

```python
# Fanout: N tasks run in parallel
phase1_results = await orchestrator.run_parallel([
    TaskSpec(key="filings", prompt=filings_prompt, context=ctx),
    TaskSpec(key="alerts",  prompt=alerts_prompt,  context=ctx),
    TaskSpec(key="trends",  prompt=trends_prompt,  context=ctx),
])

# Reduce: 1 summary task consumes phase 1 outputs
summary_context = {
    "filings": phase1_results["filings"].validated_output,
    "alerts":  phase1_results["alerts"].validated_output,
    "trends":  phase1_results["trends"].validated_output,
}
phase2_results = await orchestrator.run_sequential([
    TaskSpec(key="summary", prompt=summary_prompt, context=summary_context),
])
```

Failed or timed-out tasks produce a `TaskResult` with the corresponding status. They do not propagate exceptions — callers should check `result.status` before using `result.validated_output`.

## Analysis Engines

Statistical analysis runs in Python before any LLM call so models receive pre-computed numbers as context rather than raw data.

### Signal Detection (`workflows/analysis/signal_detection.py`)

Implements three standard pharmacovigilance disproportionality measures using 2x2 contingency tables where:

- **a** = cases with drug AND event
- **b** = cases with drug but NO event
- **c** = cases with NO drug but event
- **d** = cases with NO drug and NO event

#### Reporting Odds Ratio (ROR)

```python
from lexgenius_pipeline.workflows.analysis.signal_detection import calculate_ror

result = calculate_ror(a=45, b=955, c=200, d=9800)
# result.ror          — point estimate
# result.ci_lower     — lower 95% CI
# result.ci_upper     — upper 95% CI
# result.significant  — True if ci_lower > 1.0
# result.case_count   — value of a
```

Signal is considered significant when the lower bound of the 95% CI exceeds 1.0.

#### Proportional Reporting Ratio (PRR)

```python
from lexgenius_pipeline.workflows.analysis.signal_detection import calculate_prr

result = calculate_prr(a=45, b=955, c=200, d=9800)
# result.prr          — point estimate
# result.chi_squared  — chi-squared statistic
# result.p_value      — p-value (scipy.stats.chi2)
# result.significant  — True if PRR >= 2.0 AND chi2 >= 4.0
```

The EMA threshold (PRR >= 2.0, chi-squared >= 4.0) is used.

#### Bayesian Confidence Propagation Neural Network (BCPNN)

```python
from lexgenius_pipeline.workflows.analysis.signal_detection import calculate_bcpnn

result = calculate_bcpnn(a=45, b=955, c=200, d=9800)
# result.ic           — Information Component (log2 of observed/expected ratio)
# result.ic_lower     — lower 95% CI of IC
# result.ic_upper     — upper 95% CI of IC
# result.significant  — True if ic_lower > 0.0
```

Signal is significant when the lower bound of the IC 95% CI exceeds 0.

### Bradford Hill Criteria (`workflows/analysis/bradford_hill.py`)

Provides a weighted causality assessment based on nine classical criteria, seven of which are implemented.

```python
from lexgenius_pipeline.workflows.analysis.bradford_hill import assess_bradford_hill

assessment = assess_bradford_hill(
    ror_result=ror,
    prr_result=prr,
    case_count=45,
    has_temporal_relationship=True,
    has_dose_response=False,
    has_biological_plausibility=True,
    consistent_across_studies=False,
    specific_to_exposure=True,
)
# assessment.overall_score   — weighted score 0.0 to 1.0
# assessment.meets_threshold — True if overall_score >= 0.6
```

Criterion weights:

| Criterion | Weight |
|---|---|
| Strength of association (ROR/PRR) | 0.25 |
| Consistency | 0.15 |
| Temporality | 0.15 |
| Plausibility | 0.15 |
| Specificity | 0.10 |
| Biological gradient (dose-response) | 0.10 |
| Coherence (case count proxy) | 0.10 |

## Agents

Agents are single-purpose async components that combine statistical analysis with an LLM call.

### BaseAgent

```python
from abc import ABC, abstractmethod
from typing import Any

class BaseAgent(ABC):
    agent_name: str

    @abstractmethod
    async def execute(self, context: dict[str, Any]) -> dict[str, Any]: ...
```

### FAERSAnalystAgent

Combines ROR and PRR signal detection with an LLM narrative assessment.

```python
from lexgenius_pipeline.workflows.agents.faers_analyst import FAERSAnalystAgent

agent = FAERSAnalystAgent(provider=provider)
result = await agent.execute({
    "a": 45, "b": 955, "c": 200, "d": 9800,
    "drug_name": "Roundup",
    "indication": "herbicide exposure",
})
# result["signal_stats"]  — dict with ror, prr, significance flags, case_count
# result["assessment"]    — LLM validated_output dict
# result["status"]        — "succeeded" | "failed" | "timed_out"
```

### LabelSpecialistAgent

Analyses drug label data to identify safety warnings and recent label changes.

```python
from lexgenius_pipeline.workflows.agents.label_specialist import LabelSpecialistAgent

agent = LabelSpecialistAgent(provider=provider)
result = await agent.execute({
    "drug_name": "Zantac",
    "label_sections": {"warnings": "...", "adverse_reactions": "..."},
})
# result["analysis"]  — LLM validated_output dict
# result["status"]    — task status
```

### ReportSynthesizerAgent

Merges outputs from multiple agents into a unified executive-level report.

```python
from lexgenius_pipeline.workflows.agents.report_synthesizer import ReportSynthesizerAgent

agent = ReportSynthesizerAgent(provider=provider)
result = await agent.execute({
    "faers_analysis": faers_result,
    "label_analysis": label_result,
    "filing_summary": filing_result,
})
# result["report"]   — synthesized report as LLM validated_output dict
# result["status"]   — task status
```

## Pipelines

Pipelines are the highest-level entry point. They wire together TaskSpecs, agents, and analysis logic into a complete workflow run.

### DailyReportPipeline

Generates a daily intelligence briefing covering filings, adverse event alerts, and advertising trends.

```python
from datetime import date
from lexgenius_pipeline.workflows.pipelines.daily_report import DailyReportPipeline

pipeline = DailyReportPipeline(orchestrator)
result = await pipeline.run(
    report_date=date.today(),
    context={"jurisdiction": "federal", "drug_categories": ["opioids"]},
)
```

**Execution pattern:**
1. Phase 1 (parallel): `filings`, `alerts`, `ad_trends` — each loaded from a versioned prompt file in `workflows/prompts/daily_report_v1/`.
2. Phase 2 (sequential): `summary` — receives all three phase 1 outputs as context and produces an executive summary.

**Return value:**
```python
{
    "date": "2024-03-15",
    "summary": { ... },          # LLM executive summary
    "top_filings": { ... },      # phase 1 filings output
    "alerts": { ... },           # phase 1 alerts output
    "ad_trends": { ... },        # phase 1 ad trends output
}
```

### DrugInvestigationPipeline

Performs a targeted safety signal investigation for a specific drug using ingested records.

```python
from lexgenius_pipeline.workflows.pipelines.drug_investigation import DrugInvestigationPipeline

pipeline = DrugInvestigationPipeline(orchestrator)
result = await pipeline.run(
    drug_name="glyphosate",
    records=normalized_records,   # list[NormalizedRecord] from DB query
)
```

Internally: filters `adverse_event` records, computes ROR and PRR, passes signal statistics and sample record titles to the LLM for a narrative assessment.

**Return value:**
```python
{
    "drug_name": "glyphosate",
    "record_count": 150,
    "signal_stats": {
        "ror": 3.2, "ror_significant": True,
        "prr": 2.8, "prr_significant": True,
        "case_count": 45,
    },
    "assessment": { ... },    # LLM output
    "status": "succeeded",
}
```

### DiscoveryScanPipeline

Scans a broad set of records to surface emerging signals across all domains.

```python
from lexgenius_pipeline.workflows.pipelines.discovery_scan import DiscoveryScanPipeline

pipeline = DiscoveryScanPipeline(orchestrator)
result = await pipeline.run(records=normalized_records)
```

Deduplicates records first (`deduplicate_records()`), computes domain and source breakdowns, then prompts the LLM to identify patterns, anomalies, and high-priority items.

**Return value:**
```python
{
    "total_records": 892,
    "domain_breakdown": {"adverse_event": 320, "filing": 210, ...},
    "signals": { ... },    # LLM output with emerging signal analysis
    "status": "succeeded",
}
```

## Adding a New Pipeline

### Step 1: Create the pipeline module

```
src/lexgenius_pipeline/workflows/pipelines/my_pipeline.py
```

### Step 2: Implement the class

```python
from __future__ import annotations
from typing import Any
from lexgenius_pipeline.workflows.orchestrator import WorkflowOrchestrator
from lexgenius_pipeline.workflows.task_spec import TaskSpec

class MyPipeline:
    def __init__(self, orchestrator: WorkflowOrchestrator) -> None:
        self._orchestrator = orchestrator

    async def run(self, **kwargs) -> dict[str, Any]:
        # Phase 1: parallel fanout
        phase1 = await self._orchestrator.run_parallel([
            TaskSpec(key="task_a", prompt="...", context={}),
            TaskSpec(key="task_b", prompt="...", context={}),
        ])

        # Phase 2: sequential reduce
        phase2 = await self._orchestrator.run_sequential([
            TaskSpec(
                key="synthesis",
                prompt="...",
                context={
                    "task_a": phase1["task_a"].validated_output,
                    "task_b": phase1["task_b"].validated_output,
                },
            )
        ])

        return {
            "result_a": phase1["task_a"].validated_output,
            "synthesis": phase2["synthesis"].validated_output,
        }
```

### Step 3: Add prompts (optional)

Place versioned prompt text in `workflows/prompts/{pipeline_name}_v1/*.txt` and load them with `importlib.resources`:

```python
import importlib.resources

def _load_prompt(filename: str) -> str:
    path = (
        importlib.resources.files("lexgenius_pipeline")
        .joinpath("workflows/prompts/my_pipeline_v1")
        .joinpath(filename)
    )
    return path.read_text(encoding="utf-8")
```

### Step 4: Expose in CLI

Add a branch to the `report` command in `cli.py`:

```python
elif pipeline == "my_pipeline":
    p = MyPipeline(orchestrator)
    result = await p.run()
```

And register the choice:

```python
@click.argument("pipeline", type=click.Choice(["daily", "investigate", "discover", "my_pipeline"]))
```

### Step 5: Write tests

Use `FixtureProvider` so tests run without LLM credentials:

```python
from lexgenius_pipeline.workflows.providers.fixture import FixtureProvider
from lexgenius_pipeline.workflows.orchestrator import WorkflowOrchestrator

async def test_my_pipeline():
    provider = FixtureProvider()
    orchestrator = WorkflowOrchestrator(provider)
    pipeline = MyPipeline(orchestrator)
    result = await pipeline.run()
    assert result["status"] in ("succeeded", "failed")
```
