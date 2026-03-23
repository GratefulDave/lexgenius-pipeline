# Database Guide

The database layer is built on SQLAlchemy 2.0 async. It supports SQLite (local development) and PostgreSQL (production / AWS RDS) through a common engine factory. All interaction goes through typed repository classes.

## ORM Models

All models inherit from `Base` (a `DeclarativeBase` defined in `db/base.py`). Primary keys are UUID strings generated at insert time.

### RawRecord

Table: `raw_records`

Stores every normalized record produced by an ingestion connector.

| Column | Type | Description |
|---|---|---|
| `id` | `String(36)` PK | UUID v4 |
| `connector_id` | `String(64)` | e.g. `"federal.fda.faers"` |
| `record_type` | `String(32)` | `RecordType` enum value |
| `source_label` | `String(128)` | Human-readable source name |
| `source_url` | `String(2048)` | Canonical URL for the record |
| `citation_url` | `String(2048)` nullable | Optional deep-link citation |
| `fingerprint` | `String(64)` unique | SHA-256 dedup key |
| `title` | `String(1024)` | Record title |
| `summary` | `String(4096)` | Short text summary |
| `published_at` | `DateTime(tz=True)` | Publication date (UTC) |
| `confidence` | `Float` | Confidence score 0.0–1.0, default 1.0 |
| `metadata_` | `JSON` | Connector-specific structured data |
| `raw_payload` | `JSON` | Full original API response |
| `created_at` | `DateTime(tz=True)` | Insert timestamp (UTC) |

Indexes: `connector_id`, `record_type`, `fingerprint` (unique), `published_at`, composite `(connector_id, published_at)`.

### SourceCheckpoint

Table: `source_checkpoints`

Stores watermarks for incremental ingestion. One row per `(scope_key, connector_id)` pair.

| Column | Type | Description |
|---|---|---|
| `id` | `String(36)` PK | UUID v4 |
| `scope_key` | `String(128)` | Logical scope (currently same as `connector_id`) |
| `connector_id` | `String(64)` | Connector that owns this checkpoint |
| `last_fetched_at` | `DateTime(tz=True)` | When the connector last ran |
| `last_record_date` | `DateTime(tz=True)` nullable | `published_at` of the most recent fetched record |

Unique constraint: `(scope_key, connector_id)`.

### IngestionRun

Table: `ingestion_runs`

Audit log of every connector execution.

| Column | Type | Description |
|---|---|---|
| `id` | `String(36)` PK | UUID v4 |
| `connector_id` | `String(64)` | Which connector ran |
| `status` | `String(16)` | `"running"`, `"completed"`, `"failed"` |
| `started_at` | `DateTime(tz=True)` | Run start (UTC) |
| `completed_at` | `DateTime(tz=True)` nullable | Run end (UTC) |
| `records_fetched` | `Integer` | Total records returned by the connector |
| `records_written` | `Integer` | Records actually inserted (after dedup) |
| `duplicates_skipped` | `Integer` | Records skipped due to fingerprint match |
| `errors` | `Integer` | Error count during the run |
| `duration_ms` | `Float` | Wall-clock duration in milliseconds |
| `peak_memory_mb` | `Float` nullable | Peak RSS memory (if measured) |

### Signal

Table: `signals`

Derived signals produced by analysis pipelines, linked to their source `RawRecord`.

| Column | Type | Description |
|---|---|---|
| `id` | `String(36)` PK | UUID v4 |
| `raw_record_id` | `String(36)` FK→`raw_records.id` | Source record (cascade delete) |
| `signal_type` | `String(64)` | Category of signal |
| `strength` | `String(16)` | `"weak"`, `"moderate"`, `"strong"`, `"critical"` |
| `title` | `String(1024)` | Signal title |
| `summary` | `String(4096)` | Signal narrative |
| `entity_tags` | `JSON` (list) | Tagged entities (drugs, chemicals, companies) |
| `relevance_score` | `Float` | 0.0–1.0 relevance to current matter |
| `created_at` | `DateTime(tz=True)` | Insert timestamp (UTC) |

Composite index: `(signal_type, strength)`.

### WorkflowRun

Table: `workflow_runs`

Top-level record for each pipeline execution.

| Column | Type | Description |
|---|---|---|
| `id` | `String(36)` PK | UUID v4 |
| `workflow_name` | `String(128)` | Pipeline identifier (e.g. `"daily_report"`) |
| `status` | `String(16)` | `"pending"`, `"running"`, `"completed"`, `"failed"` |
| `started_at` | `DateTime(tz=True)` | Start (UTC) |
| `completed_at` | `DateTime(tz=True)` nullable | End (UTC) |
| `metadata_` | `JSON` | Pipeline-specific metadata |

### TaskRun

Table: `task_runs`

Individual LLM task execution record, child of `WorkflowRun`.

| Column | Type | Description |
|---|---|---|
| `id` | `String(36)` PK | UUID v4 |
| `workflow_run_id` | `String(36)` FK→`workflow_runs.id` | Parent run (cascade delete) |
| `task_name` | `String(128)` | Task key from `TaskSpec` |
| `status` | `String(16)` | `"pending"`, `"running"`, `"completed"`, `"failed"`, `"timed_out"` |
| `started_at` | `DateTime(tz=True)` | Start (UTC) |
| `completed_at` | `DateTime(tz=True)` nullable | End (UTC) |
| `error_message` | `Text` nullable | Error detail if failed |
| `metadata_` | `JSON` | Token counts, cost, etc. |

Composite index: `(workflow_run_id, status)`.

### ReportSnapshot

Table: `report_snapshots`

Serialized report output for each workflow run.

| Column | Type | Description |
|---|---|---|
| `id` | `String(36)` PK | UUID v4 |
| `workflow_run_id` | `String(36)` FK→`workflow_runs.id` | Parent run (cascade delete) |
| `format` | `String(16)` | `"json"`, `"html"`, `"markdown"` |
| `content` | `Text` | Full serialized report |
| `created_at` | `DateTime(tz=True)` | Insert timestamp (UTC) |

## Repository Pattern

All database access goes through repository classes. This keeps SQLAlchemy ORM details out of business logic and makes the persistence layer testable in isolation.

### AbstractRepository

```python
from abc import ABC, abstractmethod
from typing import Generic, TypeVar
from sqlalchemy.ext.asyncio import AsyncSession

T = TypeVar("T")

class AbstractRepository(ABC, Generic[T]):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @abstractmethod
    async def get(self, id: str) -> T | None: ...

    @abstractmethod
    async def add(self, entity: T) -> T: ...

    @abstractmethod
    async def delete(self, id: str) -> None: ...
```

### Concrete Repositories

| Class | Model | Extra Methods |
|---|---|---|
| `RawRecordRepository` | `RawRecord` | `get_by_fingerprint()`, `fingerprint_exists()`, `list_by_connector()`, `list_by_type()` |
| `CheckpointRepository` | `SourceCheckpoint` | `get_by_scope()`, `upsert()` |
| `SignalRepository` | `Signal` | `list_by_type()`, `list_by_strength()` |
| `WorkflowRepository` | `WorkflowRun`, `TaskRun`, `ReportSnapshot` | `get_latest_run()`, `add_task_run()`, `add_snapshot()` |

### Usage Example

```python
from lexgenius_pipeline.db.repositories.record_repo import RawRecordRepository

async with session_factory() as session:
    async with session.begin():
        repo = RawRecordRepository(session)

        # Dedup check
        exists = await repo.fingerprint_exists(record.fingerprint)
        if not exists:
            await repo.add(normalize_to_orm(record))

        # Query
        recent = await repo.list_by_connector(
            "federal.fda.faers",
            since=datetime(2024, 1, 1, tzinfo=timezone.utc),
            limit=500,
        )
```

## Engine Factory

`db/engine.py` provides two public functions:

```python
from lexgenius_pipeline.db.engine import create_engine, create_session_factory
from lexgenius_pipeline.settings import get_settings

settings = get_settings()
engine = create_engine(settings)
session_factory = create_session_factory(engine)
```

### SQLite Configuration

```python
create_async_engine(
    "sqlite+aiosqlite:///lexgenius_pipeline.db",
    echo=False,
    connect_args={"check_same_thread": False},
)
```

`check_same_thread=False` is required for asyncio use with aiosqlite.

### PostgreSQL — Local / Long-Running Process

```python
create_async_engine(
    url,
    echo=False,
    pool_size=5,        # persistent pool connections
    max_overflow=10,    # additional burst connections
    pool_pre_ping=True, # discard stale connections before use
    pool_recycle=3600,  # recycle connections after 1 hour
)
```

### PostgreSQL — Lambda (NullPool)

When `LGP_COMPUTE_BACKEND=lambda`, `NullPool` is used instead:

```python
from sqlalchemy.pool import NullPool
create_async_engine(url, echo=False, poolclass=NullPool)
```

`NullPool` means every `async with session_factory() as session:` block opens a fresh connection and closes it immediately on exit. This prevents connection accumulation across concurrent Lambda invocations. For high-throughput workloads, use RDS Proxy in front of the database to absorb the connection churn.

### URL Normalisation

The engine factory normalises legacy `postgres://` scheme URLs (produced by some AWS services) to `postgresql+asyncpg://` automatically.

## Alembic Migrations

Alembic is configured in `alembic.ini` and `alembic/env.py`. It supports both SQLite and PostgreSQL backends via the same migration files.

### Creating a Migration

After changing or adding an ORM model:

```bash
alembic revision --autogenerate -m "add signal entity_tags index"
alembic upgrade head
```

`--autogenerate` compares the current ORM models against the database schema and generates the diff. Always review the generated migration before applying it.

### Applying Migrations

```bash
# Apply all pending migrations
alembic upgrade head

# Downgrade one step
alembic downgrade -1

# Show current revision
alembic current

# Show migration history
alembic history
```

### Running Against PostgreSQL

```bash
export LGP_DB_BACKEND=postgresql
export LGP_DB_URL=postgresql+asyncpg://user:pass@host:5432/lexgenius
alembic upgrade head
```

Or set `RDS_DATABASE_URL` (picked up as a fallback).

### Notes for Both Backends

- Migrations must be run from a host with network access to the database — not from within a Lambda function.
- `alembic.ini` reads `LGP_DB_BACKEND` and `LGP_DB_URL` at runtime via `alembic/env.py`; no hardcoded connection strings are needed.
- PostgreSQL-specific column types (e.g. `UUID`) and SQLite-compatible types (e.g. `String(36)`) are reconciled by using `String(36)` for all UUIDs so migrations apply cleanly to both backends.
