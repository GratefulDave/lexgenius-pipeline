# Architecture Overview

LexGenius Pipeline is a legal intelligence system that aggregates public data from 20+ government and commercial sources, stores normalized records, and applies LLM-powered analysis to surface signals relevant to mass tort and class action litigation.

## System Overview

```
External APIs / RSS Feeds
        |
        v
  [Ingestion Layer]
        |
   BaseConnector
   (per source)
        |
        v
  NormalizedRecord
  (Pydantic model)
        |
        v
   [Database Layer]
   RawRecord (ORM)
        |
        +-----> SourceCheckpoint (watermarks)
        |
        v
  [Analysis Layer]
  signal_detection  <-- PRR / ROR / BCPNN
  bradford_hill     <-- causality scoring
  relevancy / dedup
        |
        v
  [Workflow Layer]
  WorkflowOrchestrator
        |
   +----+----+
   |         |
  fanout   reduce
  (parallel) (sequential)
        |
        v
   LLM Provider
   (OpenAI / Anthropic / Fixture)
        |
        v
   TaskResult
        |
        v
  ReportSnapshot (DB)
        |
        v
  CLI output / Lambda response
```

## Two-Domain Separation

The codebase is split into two independent domains that share only the `common` package and the `db` layer.

### Ingestion Domain (`ingestion/`)

Responsible for pulling raw data from external sources and persisting it.

- **No LLM calls.** Ingestion connectors only talk to external APIs.
- **No workflow logic.** The runner does not know about pipelines or agents.
- Connectors produce `NormalizedRecord` objects; the runner persists them as `RawRecord` ORM rows.
- Watermarks (stored in `SourceCheckpoint`) enable incremental fetching so each run only retrieves new records.

### Workflow Domain (`workflows/`)

Responsible for analysis, reasoning, and report generation.

- **Reads from the database.** Workflows consume already-ingested `RawRecord` rows.
- **Calls LLMs.** All LLM interactions go through the `LLMProvider` abstraction.
- Statistical signal detection (PRR/ROR/BCPNN) is computed in Python before LLM calls so the model receives pre-computed statistics as context.
- Pipelines compose `TaskSpec` objects that the orchestrator fans out in parallel and reduces sequentially.

## Data Flow

```
Step 1: External API
        |
        |  HTTP (httpx, rate-limited, retried)
        v
Step 2: Connector.fetch_latest(query, watermark)
        Returns: list[NormalizedRecord]
        |
        v
Step 3: IngestionRunner._persist_records()
        - Fingerprint dedup check (SHA-256)
        - normalize_to_orm() -> RawRecord
        - session.add() + flush
        |
        v
Step 4: update_watermark()
        - Upserts SourceCheckpoint with last_record_date
        |
        v
Step 5: DB query (SQLite or PostgreSQL)
        RawRecord rows available for workflow queries
        |
        v
Step 6: Pipeline reads records, builds TaskSpec list
        |
        v
Step 7: WorkflowOrchestrator.run_parallel()
        - asyncio.TaskGroup with semaphore
        - Each task -> LLMProvider.run_one_shot()
        |
        v
Step 8: Reduce phase
        - Parallel results merged into summary context
        - WorkflowOrchestrator.run_sequential()
        |
        v
Step 9: Pipeline returns dict -> ReportSnapshot persisted
```

## Database Layer

The database layer uses SQLAlchemy 2.0 async with two backends selectable at runtime:

| Backend | Driver | Use case |
|---|---|---|
| SQLite | `aiosqlite` | Local development, single-machine |
| PostgreSQL | `asyncpg` | Production, AWS RDS / Aurora |

The `create_engine()` factory in `db/engine.py` reads `Settings` and returns the correct `AsyncEngine`. The rest of the codebase is backend-agnostic: it only interacts with the engine through `async_sessionmaker` and the repository pattern.

Connection pooling behaviour differs by `compute_backend`:
- `local`: pool_size=5, max_overflow=10, pool_recycle=3600
- `lambda`: `NullPool` (a fresh connection per invocation, preventing RDS connection exhaustion)

Alembic handles schema migrations and supports both backends via the same migration files.

## Component Relationships

```
settings.py
    |
    +-- db/engine.py (create_engine, create_session_factory)
    |       |
    |       +-- db/models/ (RawRecord, SourceCheckpoint, IngestionRun,
    |       |               Signal, WorkflowRun, TaskRun, ReportSnapshot)
    |       |
    |       +-- db/repositories/ (AbstractRepository + concrete repos)
    |
    +-- ingestion/
    |       |
    |       +-- base.py (BaseConnector ABC)
    |       +-- registry.py (ConnectorRegistry)
    |       +-- runner.py (IngestionRunner)
    |       +-- watermarks.py (get_watermark, update_watermark)
    |       +-- normalize.py (generate_fingerprint, normalize_to_orm)
    |       +-- federal/ state/ judicial/ commercial/
    |               (concrete connector implementations)
    |
    +-- workflows/
            |
            +-- providers/ (LLMProvider ABC + OpenAI, Anthropic, Fixture)
            +-- orchestrator.py (WorkflowOrchestrator)
            +-- task_spec.py (TaskSpec, TaskRequest, TaskResult)
            +-- agents/ (BaseAgent + FAERSAnalyst, LabelSpecialist, ReportSynthesizer)
            +-- analysis/ (signal_detection, bradford_hill, dedup, relevancy)
            +-- pipelines/ (DailyReport, DrugInvestigation, DiscoveryScan)
            +-- prompts/ (versioned .txt prompt files)
```

## Key Design Decisions

**Repository pattern over raw ORM sessions.** All database queries go through a repository class (`RawRecordRepository`, `CheckpointRepository`, etc.) so the persistence layer can be swapped without touching business logic.

**Async-first.** Every I/O operation — HTTP calls, database writes, LLM requests — is `async`. The CLI bridges into async with `asyncio.run()`. Lambda handlers can `await` directly.

**Fingerprint-based deduplication.** Each `NormalizedRecord` carries a SHA-256 fingerprint of `(connector_id, source_url, title, published_at)`. Before inserting, the runner checks `fingerprint_exists()`. This makes re-running ingestion safe.

**Versioned prompts.** Prompt text lives in `workflows/prompts/daily_report_v1/*.txt` and is loaded with `importlib.resources`. Prompts are decoupled from code so they can be iterated without code changes.

**LLM provider abstraction.** The `FixtureProvider` returns deterministic canned responses, enabling offline tests. Switching from OpenAI to Anthropic is a one-line settings change.
