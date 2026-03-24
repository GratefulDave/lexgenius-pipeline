# API Reference

## Settings

`lexgenius_pipeline.settings.Settings`

Loaded from environment variables with the `LGP_` prefix and from `.env`. Use `get_settings()` to obtain the singleton instance (cached via `lru_cache`).

```python
from lexgenius_pipeline.settings import get_settings
settings = get_settings()
```

### Fields

| Field | Type | Default | Description |
|---|---|---|---|
| `db_backend` | `Literal["sqlite", "postgresql"]` | `"sqlite"` | Database backend |
| `db_path` | `str` | `"lexgenius_pipeline.db"` | SQLite file path |
| `db_url` | `str` | `""` | Full async DB URL for PostgreSQL |
| `compute_backend` | `Literal["local", "lambda"]` | `"local"` | Determines connection pool strategy |
| `max_concurrent_connectors` | `int` | `5` | Semaphore size for `IngestionRunner` |
| `llm_provider` | `Literal["openai", "anthropic", "fixture"]` | `"openai"` | LLM backend |
| `llm_model` | `str` | `"gpt-4o-mini"` | Model identifier |
| `llm_api_key` | `str` | `""` | API key for LLM provider |
| `fda_api_key` | `str` | `""` | FDA openFDA API key |
| `exa_api_key` | `str` | `""` | Exa.ai API key |
| `comptox_api_key` | `str` | `""` | EPA CompTox API key |
| `congress_api_key` | `str` | `""` | Congress.gov API key |
| `pubmed_api_key` | `str` | `""` | NCBI PubMed API key |
| `regulations_gov_api_key` | `str` | `""` | Regulations.gov API key |
| `courtlistener_api_key` | `str` | `""` | CourtListener token |
| `epa_api_key` | `str` | `""` | EPA ECHO API key |
| `pacer_username` | `str` | `""` | PACER username |
| `pacer_password` | `str` | `""` | PACER password |
| `log_level` | `str` | `"INFO"` | Logging level |
| `log_format` | `Literal["json", "console"]` | `"console"` | Log output format |

---

## BaseConnector

`lexgenius_pipeline.ingestion.base.BaseConnector`

Abstract base class for all data source connectors.

### Class Attributes

| Attribute | Type | Description |
|---|---|---|
| `connector_id` | `str` | Dot-namespaced identifier, e.g. `"federal.fda.faers"` |
| `source_tier` | `SourceTier` | `FEDERAL`, `STATE`, `JUDICIAL`, or `COMMERCIAL` |
| `source_label` | `str` | Human-readable source name |
| `supports_incremental` | `bool` | Whether watermarks are used for incremental fetching |

### Methods

#### `fetch_latest(query, watermark) -> list[NormalizedRecord]`

```python
async def fetch_latest(
    self,
    query: IngestionQuery,
    watermark: Watermark | None = None,
) -> list[NormalizedRecord]: ...
```

Fetches new records from the source. If `watermark` is provided and `supports_incremental=True`, only records newer than `watermark.last_record_date` should be returned.

#### `health_check() -> HealthStatus`

```python
async def health_check(self) -> HealthStatus: ...
```

Returns `HealthStatus.HEALTHY`, `HealthStatus.DEGRADED`, or `HealthStatus.FAILED`. Must not raise.

---

## ConnectorRegistry

`lexgenius_pipeline.ingestion.registry.ConnectorRegistry`

In-process catalogue of registered connectors.

### Methods

| Method | Signature | Returns | Description |
|---|---|---|---|
| `register` | `(connector: BaseConnector) -> None` | `None` | Add a connector; raises `ValueError` on duplicate `connector_id` |
| `get` | `(connector_id: str) -> BaseConnector` | `BaseConnector` | Raises `KeyError` if not found |
| `list_all` | `() -> list[BaseConnector]` | `list[BaseConnector]` | All registered connectors |
| `list_by_tier` | `(tier: SourceTier) -> list[BaseConnector]` | `list[BaseConnector]` | Filter by tier |
| `list_by_agency` | `(agency: str) -> list[BaseConnector]` | `list[BaseConnector]` | Filter by second segment of `connector_id` |
| `__len__` | | `int` | Number of registered connectors |
| `__contains__` | `(connector_id: str) -> bool` | `bool` | Membership test |

---

## IngestionRunner

`lexgenius_pipeline.ingestion.runner.IngestionRunner`

### Constructor

```python
IngestionRunner(
    registry: ConnectorRegistry,
    session_factory: async_sessionmaker[AsyncSession],
    max_concurrent: int = 5,
)
```

### Methods

#### `run_all(query) -> RunMetrics`

```python
async def run_all(self, query: IngestionQuery) -> RunMetrics: ...
```

Runs all connectors in `registry` (filtered by `query.connector_ids` if set) concurrently under a semaphore. Returns aggregated `RunMetrics`.

#### `run_connector(connector, query) -> ConnectorMetrics`

```python
async def run_connector(
    self, connector: BaseConnector, query: IngestionQuery
) -> ConnectorMetrics: ...
```

Runs a single connector: creates `IngestionRun` row, fetches watermark, calls `fetch_latest`, deduplicates, persists records, updates watermark, finalises the run record.

---

## LLMProvider

`lexgenius_pipeline.workflows.providers.base.LLMProvider`

Abstract base class for all LLM backends.

### Methods

#### `run_one_shot(request, output_schema) -> TaskResult`

```python
async def run_one_shot(
    self,
    request: TaskRequest,
    output_schema: type[BaseModel] | None = None,
) -> TaskResult: ...
```

Executes a single prompt. If `output_schema` is provided, the provider instructs the model to return valid JSON matching the schema, and attempts to parse the response into `TaskResult.validated_output`. Never raises — errors are returned as `TaskResult(status="failed")`.

---

## WorkflowOrchestrator

`lexgenius_pipeline.workflows.orchestrator.WorkflowOrchestrator`

### Constructor

```python
WorkflowOrchestrator(
    provider: LLMProvider,
    max_workers: int = 4,
)
```

### Methods

#### `run_parallel(task_specs, timeout_ms) -> dict[str, TaskResult]`

```python
async def run_parallel(
    self,
    task_specs: list[TaskSpec],
    timeout_ms: int = 60000,
) -> dict[str, TaskResult]: ...
```

Executes all `task_specs` concurrently using `asyncio.TaskGroup` and a `Semaphore(max_workers)`. Returns a dict keyed by `TaskSpec.key`. Timed-out or failed tasks produce a `TaskResult` with the corresponding status rather than raising.

#### `run_sequential(task_specs) -> dict[str, TaskResult]`

```python
async def run_sequential(
    self,
    task_specs: list[TaskSpec],
) -> dict[str, TaskResult]: ...
```

Executes `task_specs` one at a time in list order. Errors are captured per-task and do not abort the sequence.

---

## NormalizedRecord

`lexgenius_pipeline.common.models.NormalizedRecord`

Pydantic model produced by every connector. This is the standard data contract between the ingestion and database layers.

### Fields

| Field | Type | Required | Description |
|---|---|---|---|
| `title` | `str` | Yes | Record title |
| `summary` | `str` | Yes | Short text description |
| `record_type` | `RecordType` | Yes | Enum value: `adverse_event`, `recall`, `filing`, `regulation`, `research`, `news`, `legislation`, `enforcement` |
| `source_connector_id` | `str` | Yes | The connector's `connector_id` |
| `source_label` | `str` | Yes | Human-readable source name |
| `source_url` | `str` | Yes | Canonical URL |
| `citation_url` | `str \| None` | No | Optional direct citation link |
| `published_at` | `datetime` | Yes | Publication date, must be timezone-aware (UTC) |
| `confidence` | `float` | No | Default `1.0`; range 0.0–1.0 |
| `fingerprint` | `str` | Yes | SHA-256 dedup hash from `generate_fingerprint()` |
| `metadata` | `dict[str, Any]` | No | Connector-specific structured data |
| `raw_payload` | `dict[str, Any]` | No | Full original API response |

### Related Models

#### `IngestionQuery`

```python
class IngestionQuery(BaseModel):
    connector_ids: list[str] | None = None  # if set, only run these connectors
    query_terms: list[str] | None = None    # search terms (drugs, chemicals, etc.)
    date_from: datetime | None = None
    date_to: datetime | None = None
    max_records: int = 1000
```

#### `Watermark`

```python
class Watermark(BaseModel):
    scope_key: str
    connector_id: str
    last_fetched_at: datetime
    last_record_date: datetime | None = None  # None on first run
```

#### `RunMetrics`

```python
class RunMetrics(BaseModel):
    records_fetched: int = 0
    records_written: int = 0
    duplicates_skipped: int = 0
    errors: int = 0
    duration_ms: float = 0.0
    peak_memory_mb: float | None = None
```

---

## TaskSpec / TaskRequest / TaskResult

`lexgenius_pipeline.workflows.task_spec`

### TaskSpec

Input to `WorkflowOrchestrator`.

```python
class TaskSpec(BaseModel):
    key: str                                       # unique within a pipeline run
    prompt: str                                    # LLM instruction
    context: dict[str, Any] = {}                   # injected as JSON after the prompt
    output_schema: type[BaseModel] | None = None   # structured output schema
    timeout_ms: int = 30000                        # per-task override
```

### TaskRequest

Internal wire type from orchestrator to provider.

```python
class TaskRequest(BaseModel):
    task_key: str
    prompt: str
    context: dict[str, Any] = {}
    timeout_ms: int = 30000
    model_name: str = ""        # overrides provider default
    temperature: float = 0.2
```

### TaskResult

Returned by every `LLMProvider.run_one_shot()` call.

```python
class TaskResult(BaseModel):
    task_key: str
    status: Literal["succeeded", "failed", "timed_out"]
    validated_output: dict[str, Any] = {}   # parsed JSON response
    raw_output: dict[str, Any] = {}         # raw provider response
    error_message: str = ""
    duration_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_micros: int = 0                    # cost in millionths of a dollar
```

---

## Enumerations

`lexgenius_pipeline.common.types`

### RecordType

```python
class RecordType(str, Enum):
    ADVERSE_EVENT = "adverse_event"
    RECALL        = "recall"
    FILING        = "filing"
    REGULATION    = "regulation"
    RESEARCH      = "research"
    NEWS          = "news"
    LEGISLATION   = "legislation"
    ENFORCEMENT   = "enforcement"
```

### SourceTier

```python
class SourceTier(str, Enum):
    FEDERAL    = "federal"
    STATE      = "state"
    JUDICIAL   = "judicial"
    COMMERCIAL = "commercial"
```

### SignalStrength

```python
class SignalStrength(str, Enum):
    WEAK     = "weak"
    MODERATE = "moderate"
    STRONG   = "strong"
    CRITICAL = "critical"
```

### HealthStatus

```python
class HealthStatus(str, Enum):
    HEALTHY  = "healthy"
    DEGRADED = "degraded"
    FAILED   = "failed"
```

### ExecutionStatus

```python
class ExecutionStatus(str, Enum):
    PENDING   = "pending"
    RUNNING   = "running"
    COMPLETED = "completed"
    FAILED    = "failed"
    TIMED_OUT = "timed_out"
```

---

## CLI Commands

The CLI entry point is `lexgenius` (configured in `pyproject.toml` under `[project.scripts]`).

```
lexgenius [OPTIONS] COMMAND [ARGS]...

Commands:
  health   Check health of all registered connectors
  ingest   Run ingestion connectors
  report   Run a workflow pipeline
```

### `lexgenius ingest`

```
Usage: lexgenius ingest [OPTIONS]

  Run ingestion connectors.

Options:
  --sources TEXT  Comma-separated connector IDs to run
  --all           Run all registered connectors
```

Examples:

```bash
# Run all connectors
lexgenius ingest --all

# Run specific connectors
lexgenius ingest --sources federal.fda.faers,federal.nih.pubmed

# Output is JSON RunMetrics
{
  "records_fetched": 142,
  "records_written": 138,
  "duplicates_skipped": 4,
  "errors": 0,
  "duration_ms": 8432.1,
  "peak_memory_mb": null
}
```

### `lexgenius report`

```
Usage: lexgenius report [OPTIONS] PIPELINE

  Run a workflow pipeline.

Arguments:
  PIPELINE  [daily|investigate|discover]  Required
```

Examples:

```bash
# Generate today's daily intelligence report
lexgenius report daily

# Run the discovery scan across all ingested records
lexgenius report discover

# Note: 'investigate' requires additional arguments and is not yet
# fully wired in the CLI; use the Python API directly for drug investigations
```

### `lexgenius health`

```
Usage: lexgenius health [OPTIONS]

  Check health of all connectors.
```

Returns a JSON object mapping each `connector_id` to its health status:

```json
{
  "federal.fda.faers": "healthy",
  "federal.nih.pubmed": "healthy",
  "judicial.pacer.rss": "failed: missing credentials"
}
```
