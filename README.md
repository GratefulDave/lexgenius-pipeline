# lexgenius-pipeline

Legal intelligence pipeline for mass torts and class action lawsuits.

The "Bloomberg of torts" — competitive intelligence and emerging litigation detection. Ingests, normalizes, and analyzes data from 25 sources across federal agencies, state courts, judicial systems, and commercial providers, then surfaces pharmacovigilance signals and litigation trends via LLM-powered workflow pipelines.

---

## Features

- **25 data source connectors** across federal, state, judicial, and commercial tiers — FDA, NIH, SEC, EPA, USGS, Congress, CPSC, Federal Register, CourtListener, PACER, Regulations.gov, Exa, Google News, RSS feeds, and more
- **Async-first ingestion** with configurable parallel execution, watermark-based incremental fetching, and fingerprint-based deduplication
- **LLM-powered workflow pipelines**: daily litigation report, drug investigation, and emerging-case discovery scan
- **Pharmacovigilance signal detection** using PRR, ROR, BCPNN, and Bradford Hill causality criteria
- **Repository pattern** with SQLite (local dev) / PostgreSQL (production) swap via a single environment variable
- **AWS Lambda-ready** with SAM deployment template, RDS connection pooling via `NullPool`, and per-function handlers

---

## Architecture

```
External APIs
     |
     v
Connectors (federal / state / judicial / commercial)
     |
     v
NormalizedRecord  -->  Watermarks + Dedup
     |
     v
DB (SQLite / RDS PostgreSQL)
     |
     v
Analysis Engines (signal detection, relevancy scoring, Bradford Hill)
     |
     v
Workflow Pipelines (daily report / drug investigation / discovery scan)
     |
     v
LLM Providers (OpenAI / Anthropic / fixture)  -->  Reports
```

Each connector implements `BaseConnector` and produces `NormalizedRecord` objects with a typed `RecordType` (adverse event, recall, filing, regulation, research, news, legislation, enforcement). The `IngestionRunner` executes connectors concurrently up to `LGP_MAX_CONCURRENT_CONNECTORS` and persists watermarks so subsequent runs only fetch new data.

---

## Quick Start

### Prerequisites

- Python 3.11+
- (Optional) Docker for PostgreSQL local testing
- (Optional) AWS SAM CLI for Lambda deployment

### Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

For PostgreSQL support:

```bash
pip install -e ".[dev,postgresql]"
```

### Configure

```bash
cp .env.example .env
# Edit .env — fill in API keys. Defaults use SQLite; no DB config needed for local dev.
```

### Migrate

```bash
alembic upgrade head
```

### Run ingestion

```bash
# All connectors
lexgenius ingest --all

# Specific connectors
lexgenius ingest --sources federal.fda.faers,judicial.courtlistener

# Health check all connectors
lexgenius health
```

### Run a workflow pipeline

```bash
lexgenius report daily
lexgenius report discover
```

### Run tests

```bash
# Unit tests only (no network)
pytest tests/unit/ -v --tb=short

# All tests including live API calls
pytest tests/ -v -m live
```

---

## Data Sources

| Connector ID | Source | Record Type | Auth Required |
|---|---|---|---|
| `federal.fda.faers` | FDA Adverse Event Reporting System | adverse_event | Optional (higher rate limits) |
| `federal.fda.maude` | FDA MAUDE (medical device adverse events) | adverse_event | Optional |
| `federal.fda.recalls` | FDA Enforcement / Recalls | recall | No |
| `federal.fda.dailymed` | FDA DailyMed (drug labeling) | research | No |
| `federal.nih.pubmed` | NIH PubMed literature | research | Optional |
| `federal.nih.clinical_trials` | ClinicalTrials.gov | research | No |
| `federal.sec.edgar` | SEC EDGAR filings | filing | No (User-Agent header) |
| `federal.epa.comptox` | EPA CompTox chemicals dashboard | research | Yes (`LGP_COMPTOX_API_KEY`) |
| `federal.epa.enforcement` | EPA enforcement actions | enforcement | No |
| `federal.congress.legislation` | Congress.gov legislation | legislation | Yes (`LGP_CONGRESS_API_KEY`) |
| `federal.cpsc.recalls` | CPSC product recalls | recall | No |
| `federal.federal_register.notices` | Federal Register notices | regulation | No |
| `federal.usgs.water_quality` | USGS water quality data | research | No |
| `federal.cdc.*` | CDC data sources | adverse_event | Planned |
| `federal.doj.*` | DOJ enforcement actions | enforcement | Planned |
| `federal.ftc.*` | FTC actions | enforcement | Planned |
| `federal.nhtsa.*` | NHTSA safety complaints | adverse_event | Planned |
| `federal.osha.*` | OSHA inspections / citations | enforcement | Planned |
| `judicial.courtlistener` | CourtListener federal dockets | filing | Yes (`LGP_COURTLISTENER_API_KEY`) |
| `judicial.pacer.rss` | PACER RSS feeds | filing | Yes (`LGP_PACER_USERNAME` / `LGP_PACER_PASSWORD`) |
| `judicial.regulations_gov` | Regulations.gov docket comments | regulation | Yes (`LGP_REGULATIONS_GOV_API_KEY`) |
| `state.DE.*` | Delaware state courts | filing | Implemented |
| `state.PA.*` | Pennsylvania state courts | filing | Implemented |
| `commercial.exa_research` | Exa semantic web search | news | Yes (`LGP_EXA_API_KEY`) |
| `commercial.google_news` | Google News RSS | news | No |
| `commercial.news_rss` | Configurable RSS feeds | news | No |

---

## Project Structure

```
lexgenius-pipeline/
├── src/lexgenius_pipeline/
│   ├── cli.py                    # Click CLI entry point (ingest, report, health)
│   ├── settings.py               # Pydantic settings with LGP_ env prefix
│   ├── common/
│   │   ├── models.py             # NormalizedRecord, Watermark, IngestionQuery
│   │   ├── types.py              # RecordType, SourceTier, SignalStrength enums
│   │   ├── errors.py             # Domain exceptions
│   │   ├── http_client.py        # Shared HTTPX client factory
│   │   ├── rate_limiter.py       # Token-bucket rate limiter
│   │   └── retry.py              # Tenacity retry decorators
│   ├── ingestion/
│   │   ├── base.py               # BaseConnector ABC
│   │   ├── registry.py           # ConnectorRegistry (tier/agency filtering)
│   │   ├── runner.py             # IngestionRunner (async parallel execution)
│   │   ├── watermarks.py         # Incremental fetch state
│   │   ├── normalize.py          # Record normalization helpers
│   │   ├── metrics.py            # Per-run ingestion metrics
│   │   ├── federal/              # Federal agency connectors (FDA, NIH, SEC, EPA, ...)
│   │   ├── state/                # State court connectors (DE, PA, ...)
│   │   ├── judicial/             # Judicial connectors (CourtListener, PACER, Regs.gov)
│   │   └── commercial/           # Commercial connectors (Exa, Google News, RSS)
│   ├── workflows/
│   │   ├── orchestrator.py       # WorkflowOrchestrator (task graph execution)
│   │   ├── task_spec.py          # TaskSpec / TaskResult definitions
│   │   ├── pipelines/            # daily_report, drug_investigation, discovery_scan
│   │   ├── analysis/             # signal_detection, bradford_hill, relevancy, dedup
│   │   ├── agents/               # LLM agent wrappers
│   │   ├── prompts/              # Prompt templates
│   │   └── providers/            # LLM provider adapters (OpenAI, Anthropic, fixture)
│   └── db/
│       ├── engine.py             # SQLAlchemy async engine (NullPool for Lambda)
│       ├── models/               # ORM models
│       └── repositories/         # Repository pattern (SQLite / PostgreSQL)
├── deploy/
│   ├── README.md                 # Deployment guide (local, PostgreSQL, AWS SAM)
│   ├── template.yaml             # SAM template
│   ├── handlers/                 # Lambda handler functions
│   └── requirements.txt          # Lambda deployment dependencies
├── alembic/                      # Database migrations
├── tests/
│   ├── unit/                     # Fast tests, no network
│   └── integration/              # Live API tests (marked with @pytest.mark.live)
├── .env.example                  # Environment variable reference
├── alembic.ini
└── pyproject.toml
```

---

## Configuration

All settings use the `LGP_` environment variable prefix. Copy `.env.example` to `.env` to get started.

| Variable | Default | Description |
|---|---|---|
| `LGP_DB_BACKEND` | `sqlite` | `sqlite` or `postgresql` |
| `LGP_DB_PATH` | `lexgenius_pipeline.db` | SQLite file path (sqlite only) |
| `LGP_DB_URL` | _(empty)_ | Full async DB URL (required for postgresql) |
| `RDS_DATABASE_URL` | _(empty)_ | Fallback DB URL (AWS convention, picked up automatically) |
| `LGP_COMPUTE_BACKEND` | `local` | `local` or `lambda` (lambda uses NullPool) |
| `LGP_MAX_CONCURRENT_CONNECTORS` | `5` | Parallel connector execution limit |
| `LGP_LLM_PROVIDER` | `openai` | `openai`, `anthropic`, or `fixture` |
| `LGP_LLM_MODEL` | `gpt-4o-mini` | Model identifier |
| `LGP_LLM_API_KEY` | _(empty)_ | API key for the configured LLM provider |
| `LGP_LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `LGP_LOG_FORMAT` | `console` | `console` or `json` (use `json` in production) |
| `LGP_FDA_API_KEY` | _(empty)_ | FDA API key (optional, increases rate limits) |
| `LGP_EXA_API_KEY` | _(empty)_ | Exa semantic search API key |
| `LGP_COMPTOX_API_KEY` | _(empty)_ | EPA CompTox API key |
| `LGP_CONGRESS_API_KEY` | _(empty)_ | Congress.gov API key |
| `LGP_PUBMED_API_KEY` | _(empty)_ | PubMed / NCBI E-utilities API key |
| `LGP_REGULATIONS_GOV_API_KEY` | _(empty)_ | Regulations.gov API key |
| `LGP_COURTLISTENER_API_KEY` | _(empty)_ | CourtListener API token |
| `LGP_PACER_USERNAME` | _(empty)_ | PACER account username |
| `LGP_PACER_PASSWORD` | _(empty)_ | PACER account password |

---

## Development

### Running tests

```bash
# Fast unit tests (recommended for local dev iteration)
pytest tests/unit/ -v --tb=short

# Skip live tests explicitly
pytest tests/ -m "not live" -v

# Run live integration tests (requires API keys in .env)
pytest tests/ -m live -v
```

### Adding a new connector

1. Create a directory under the appropriate tier: `src/lexgenius_pipeline/ingestion/{tier}/{agency}/`.
2. Copy `src/lexgenius_pipeline/ingestion/federal/_template/` as a starting point.
3. Subclass `BaseConnector`, set `connector_id`, `source_tier`, and `source_label`, and implement `fetch_latest()` and `health_check()`.
4. Register the connector in `ConnectorRegistry.__init__()` or its tier's `__init__.py`.
5. Add unit tests under `tests/unit/ingestion/` and, if applicable, a live test marked `@pytest.mark.live`.

```python
from lexgenius_pipeline.ingestion.base import BaseConnector
from lexgenius_pipeline.common.types import RecordType, SourceTier

class MyAgencyConnector(BaseConnector):
    connector_id = "federal.myagency.source"
    source_tier = SourceTier.FEDERAL
    source_label = "My Agency Source"

    async def fetch_latest(self, query, watermark=None):
        # Fetch, normalize, and return List[NormalizedRecord]
        ...

    async def health_check(self):
        ...
```

### Adding a new pipeline

1. Create a new file under `src/lexgenius_pipeline/workflows/pipelines/`.
2. Subclass or compose `WorkflowOrchestrator` to define your task graph.
3. Add a `click.Choice` entry in `cli.py` under the `report` command.
4. Add prompt templates under `workflows/prompts/` as needed.

---

## Deployment

Local development uses SQLite with no additional configuration. Production deployment targets AWS Lambda with RDS PostgreSQL.

See [deploy/README.md](deploy/README.md) for:

- Switching from SQLite to PostgreSQL locally via Docker
- AWS SAM build and deploy steps
- Running Alembic migrations against RDS
- VPC and security group configuration
- Connection pooling behavior (`NullPool` under Lambda)

---

## License

TBD
