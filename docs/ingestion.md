# Ingestion System Guide

The ingestion system pulls records from external APIs, normalizes them into a common schema, deduplicates via fingerprint, and persists them to the database. All connectors run asynchronously under a concurrency semaphore.

## BaseConnector ABC

Every data source connector must subclass `BaseConnector` from `ingestion/base.py`.

```python
from abc import ABC, abstractmethod
from lexgenius_pipeline.common.models import IngestionQuery, NormalizedRecord, Watermark
from lexgenius_pipeline.common.types import HealthStatus, SourceTier

class BaseConnector(ABC):
    connector_id: str          # e.g. "federal.fda.faers"
    source_tier: SourceTier    # FEDERAL, STATE, JUDICIAL, or COMMERCIAL
    source_label: str          # human-readable, e.g. "FDA FAERS"
    supports_incremental: bool = True

    @abstractmethod
    async def fetch_latest(
        self,
        query: IngestionQuery,
        watermark: Watermark | None = None,
    ) -> list[NormalizedRecord]: ...

    @abstractmethod
    async def health_check(self) -> HealthStatus: ...
```

### Class Attributes

| Attribute | Type | Required | Description |
|---|---|---|---|
| `connector_id` | `str` | Yes | Dot-namespaced ID: `"{tier}.{agency}.{source}"` |
| `source_tier` | `SourceTier` | Yes | Enum: `FEDERAL`, `STATE`, `JUDICIAL`, `COMMERCIAL` |
| `source_label` | `str` | Yes | Human-readable name shown in reports |
| `supports_incremental` | `bool` | No | Default `True`; set `False` if the source has no date filter |

### `fetch_latest()` Contract

- Receives an `IngestionQuery` (query terms, date range, max records) and an optional `Watermark`.
- If a watermark is present and `supports_incremental=True`, skip records at or before `watermark.last_record_date`.
- Returns a list of `NormalizedRecord` objects. An empty list is valid (no new records).
- Raise `ConnectorError` for unrecoverable source errors, `RateLimitError` for HTTP 429.

### `health_check()` Contract

- Makes a lightweight probe request to the source API.
- Returns `HealthStatus.HEALTHY`, `HealthStatus.DEGRADED`, or `HealthStatus.FAILED`.
- Should not raise exceptions — catch them and return `FAILED`.

## ConnectorRegistry

`ConnectorRegistry` (`ingestion/registry.py`) is a simple in-process catalogue. It is populated at startup and passed to `IngestionRunner`.

```python
from lexgenius_pipeline.ingestion.registry import ConnectorRegistry
from lexgenius_pipeline.ingestion.federal.fda.faers import FAERSConnector

registry = ConnectorRegistry()
registry.register(FAERSConnector())
```

### Methods

| Method | Signature | Description |
|---|---|---|
| `register` | `(connector: BaseConnector) -> None` | Adds a connector; raises `ValueError` if `connector_id` already registered |
| `get` | `(connector_id: str) -> BaseConnector` | Returns connector or raises `KeyError` |
| `list_all` | `() -> list[BaseConnector]` | All registered connectors |
| `list_by_tier` | `(tier: SourceTier) -> list[BaseConnector]` | Filter by tier enum |
| `list_by_agency` | `(agency: str) -> list[BaseConnector]` | Filter by second segment of `connector_id` (e.g. `"fda"`) |
| `__len__` | | Number of registered connectors |
| `__contains__` | `(connector_id: str) -> bool` | Membership test |

## IngestionRunner

`IngestionRunner` (`ingestion/runner.py`) drives the full ingestion cycle: watermark lookup, connector execution, record persistence, watermark update, and metrics tracking.

```python
from lexgenius_pipeline.ingestion.runner import IngestionRunner
from lexgenius_pipeline.common.models import IngestionQuery

runner = IngestionRunner(
    registry=registry,
    session_factory=session_factory,
    max_concurrent=5,      # default from LGP_MAX_CONCURRENT_CONNECTORS
)

query = IngestionQuery(
    query_terms=["Roundup", "glyphosate"],
    max_records=500,
)

metrics = await runner.run_all(query)
print(metrics.records_written)
```

### Methods

| Method | Description |
|---|---|
| `run_all(query)` | Runs all (or filtered) connectors in parallel; returns `RunMetrics` |
| `run_connector(connector, query)` | Runs a single connector; returns `ConnectorMetrics` |

### Parallel Execution

`run_all()` creates one asyncio task per connector and controls concurrency with `asyncio.Semaphore(max_concurrent)`. Failed connectors do not block others — errors are counted in `RunMetrics.errors`.

### Per-Run Database Record

Each `run_connector()` call creates an `IngestionRun` row at the start (status `"running"`) and updates it to `"completed"` or `"failed"` when the connector finishes. This provides a full audit trail of every ingestion attempt.

### Deduplication

Before inserting each record, the runner calls `RawRecordRepository.fingerprint_exists(record.fingerprint)`. If the fingerprint is already present, the record is skipped and `duplicates_skipped` is incremented. This makes re-running ingestion idempotent.

## Watermarks

Watermarks enable incremental fetching: each connector only retrieves records newer than the last successful run.

```python
# Reading a watermark (internal to IngestionRunner)
watermark = await get_watermark(session, connector_id="federal.fda.faers", scope_key="federal.fda.faers")
# watermark is None on first run

# Updating after a successful fetch
await update_watermark(
    session,
    connector_id="federal.fda.faers",
    scope_key="federal.fda.faers",
    last_record_date=max(r.published_at for r in records),
)
```

The watermark is stored as a `SourceCheckpoint` row with a unique constraint on `(scope_key, connector_id)`. `update_watermark()` calls `CheckpointRepository.upsert()`, which updates the existing row or inserts a new one.

Connectors that do not support incremental fetching (`supports_incremental=False`) receive `watermark=None` on every call and should fetch a fixed recent window instead.

## Fingerprint Generation

```python
from lexgenius_pipeline.ingestion.normalize import generate_fingerprint

fp = generate_fingerprint(
    source_connector_id="federal.fda.faers",
    source_url="https://api.fda.gov/drug/event.json?search=safetyreportid:12345",
    title="FAERS Report 12345: IBUPROFEN",
    published_at=datetime(2024, 3, 15, tzinfo=timezone.utc),
)
# Returns a 64-character hex SHA-256 string
```

The fingerprint is a SHA-256 hash of `"{connector_id}|{source_url}|{title}|{published_at.isoformat()}"`. It is stored in `RawRecord.fingerprint` with a unique index.

## Connector Catalogue

### Federal Tier

| connector_id | Source Label | API Endpoint | Auth Required | record_type |
|---|---|---|---|---|
| `federal.fda.faers` | FDA FAERS | `https://api.fda.gov/drug/event.json` | Optional (`LGP_FDA_API_KEY`) | `adverse_event` |
| `federal.fda.maude` | FDA MAUDE | `https://api.fda.gov/device/event.json` | Optional (`LGP_FDA_API_KEY`) | `adverse_event` |
| `federal.fda.recalls` | FDA Recalls | `https://api.fda.gov/food/enforcement.json` | Optional (`LGP_FDA_API_KEY`) | `recall` |
| `federal.fda.dailymed` | DailyMed | `https://dailymed.nlm.nih.gov/dailymed/services/v2/` | None | `regulation` |
| `federal.nih.pubmed` | NIH PubMed | `https://eutils.ncbi.nlm.nih.gov/entrez/eutils/` | Optional (`LGP_PUBMED_API_KEY`) | `research` |
| `federal.nih.clinical_trials` | ClinicalTrials.gov | `https://clinicaltrials.gov/api/v2/studies` | None | `research` |
| `federal.epa.enforcement` | EPA Enforcement | `https://echo.epa.gov/api/` | Optional (`LGP_EPA_API_KEY`) | `enforcement` |
| `federal.epa.comptox` | EPA CompTox | `https://comptox.epa.gov/dashboard-api/` | Optional (`LGP_COMPTOX_API_KEY`) | `research` |
| `federal.congress.legislation` | Congress.gov | `https://api.congress.gov/v3/bill` | Required (`LGP_CONGRESS_API_KEY`) | `legislation` |
| `federal.cpsc.recalls` | CPSC SaferProducts Recalls | `https://www.saferproducts.gov/RestWebServices/` | None | `recall` |
| `federal.sec.edgar` | SEC EDGAR | `https://efts.sec.gov/LATEST/search-index` | None | `filing` |
| `federal.usgs.water_quality` | USGS Water Quality | `https://waterservices.usgs.gov/nwis/dv/` | None | `research` |
| `federal.federal_register.notices` | Federal Register | `https://www.federalregister.gov/api/v1/articles` | None | `regulation` |

Placeholder agencies with no implemented connectors yet: `federal.cdc.*`, `federal.doj.*`, `federal.ftc.*`, `federal.nhtsa.*`, `federal.osha.*`.

### State Tier

| connector_id pattern | Description |
|---|---|
| `state.{code}.courts` | State court filing connectors |

Two states have implemented connectors: Delaware (`state.de.courts`) and Pennsylvania (`state.pa.courts`). All other states are registered in `STATE_REGISTRY` but marked `implemented=False`. The `ingestion/state/_template/courts.py` file provides a copy-and-modify starting point.

### Judicial Tier

| connector_id | Source Label | API Endpoint | Auth Required | record_type |
|---|---|---|---|---|
| `judicial.courtlistener` | CourtListener | `https://www.courtlistener.com/api/rest/v4/search/` | Optional (`LGP_COURTLISTENER_API_KEY`) | `filing` |
| `judicial.pacer.rss` | PACER Federal Courts | PACER RSS feeds | Required (`LGP_PACER_USERNAME`, `LGP_PACER_PASSWORD`) | `filing` |
| `judicial.regulations_gov` | Regulations.gov | `https://api.regulations.gov/v4/` | Required (`LGP_REGULATIONS_GOV_API_KEY`) | `regulation` |

### Commercial Tier

| connector_id | Source Label | API / Source | Auth Required | record_type |
|---|---|---|---|---|
| `commercial.exa_research` | Exa Research | `https://api.exa.ai/` | Required (`LGP_EXA_API_KEY`) | `research` |
| `commercial.google_news` | Google News | Google News RSS | None | `news` |
| `commercial.news_rss` | News RSS Feeds | Configurable RSS URLs | None | `news` |

## Adding a New Connector

### Step 1: Create the module

Place the new connector in the appropriate tier directory. Use the existing connectors as reference.

```
src/lexgenius_pipeline/ingestion/federal/myagency/__init__.py
src/lexgenius_pipeline/ingestion/federal/myagency/mysource.py
```

### Step 2: Implement the connector

```python
from __future__ import annotations

from lexgenius_pipeline.common.models import IngestionQuery, NormalizedRecord, Watermark
from lexgenius_pipeline.common.types import HealthStatus, RecordType, SourceTier
from lexgenius_pipeline.ingestion.base import BaseConnector
from lexgenius_pipeline.ingestion.normalize import generate_fingerprint
from lexgenius_pipeline.settings import get_settings

class MySourceConnector(BaseConnector):
    connector_id = "federal.myagency.mysource"
    source_tier = SourceTier.FEDERAL
    source_label = "My Agency Source"
    supports_incremental = True

    def __init__(self) -> None:
        self._settings = get_settings()
        self._client = create_http_client()

    async def fetch_latest(
        self,
        query: IngestionQuery,
        watermark: Watermark | None = None,
    ) -> list[NormalizedRecord]:
        # 1. Build request params using query.query_terms
        # 2. Respect watermark.last_record_date if present
        # 3. Build and return list[NormalizedRecord]
        records = []
        for item in api_results:
            records.append(NormalizedRecord(
                title=item["title"],
                summary=item["summary"],
                record_type=RecordType.REGULATION,   # choose the right type
                source_connector_id=self.connector_id,
                source_label=self.source_label,
                source_url=item["url"],
                published_at=parse_date(item["date"]),
                fingerprint=generate_fingerprint(
                    self.connector_id, item["url"], item["title"], published_at
                ),
                metadata={"extra_field": item.get("extra")},
                raw_payload=item,
            ))
        return records

    async def health_check(self) -> HealthStatus:
        try:
            resp = await self._client.get("https://api.myagency.gov/ping")
            return HealthStatus.HEALTHY if resp.status_code < 500 else HealthStatus.DEGRADED
        except Exception:
            return HealthStatus.FAILED
```

### Step 3: Register the connector

Add your connector to the registry at application startup (or in the Lambda handler):

```python
from lexgenius_pipeline.ingestion.federal.myagency.mysource import MySourceConnector

registry = ConnectorRegistry()
registry.register(MySourceConnector())
```

### Step 4: Add environment variable (if needed)

If the connector requires an API key, add it to `Settings` in `settings.py`:

```python
myagency_api_key: str = ""
```

And add a fallback mapping in `_read_fallback_env_vars` if the upstream env var name differs from the `LGP_` convention.

### Step 5: Write tests

Add a test in `tests/unit/ingestion/` that mocks the HTTP client and verifies `NormalizedRecord` output. Use the `live` pytest marker for any test that calls the real API:

```python
@pytest.mark.live
async def test_mysource_live():
    connector = MySourceConnector()
    records = await connector.fetch_latest(IngestionQuery(query_terms=["test"]))
    assert len(records) > 0
```

Run live tests explicitly: `pytest -m live`.
