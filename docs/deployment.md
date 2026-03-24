# Deployment Guide

## Local Development Setup

### Prerequisites

- Python 3.11 or later
- `uv` (recommended) or `pip`

### Installation

```bash
# Clone the repository and enter it
cd lexgenius-pipeline

# Create a virtual environment and install with dev dependencies
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Or using uv (faster)
uv sync
```

### Configure Environment

```bash
cp .env.example .env
# Edit .env — the defaults use SQLite and require no further DB config for local development
```

The `.env` file is loaded automatically by `pydantic-settings`. All variables use the `LGP_` prefix. See the Environment Variables Reference section below for the full list.

### Apply Database Migrations

```bash
alembic upgrade head
```

This creates `lexgenius_pipeline.db` (SQLite) in the project root.

### Verify the Installation

```bash
# Check CLI is available
lexgenius --help

# Run unit tests
pytest tests/unit/ -v --tb=short

# Check connector health (requires API keys for authenticated sources)
lexgenius health
```

### Running Ingestion Locally

```bash
# Run all registered connectors
lexgenius ingest --all

# Run specific connectors
lexgenius ingest --sources federal.fda.faers,federal.nih.pubmed

# Run a workflow pipeline
lexgenius report daily
lexgenius report discover
```

---

## Environment Variables Reference

All variables are loaded with the `LGP_` prefix. Legacy variable names from prior projects are accepted as fallbacks (see the Fallback column).

### Database

| Variable | Default | Description | Fallback |
|---|---|---|---|
| `LGP_DB_BACKEND` | `sqlite` | Backend to use: `sqlite` or `postgresql` | — |
| `LGP_DB_PATH` | `lexgenius_pipeline.db` | SQLite file path (SQLite only) | — |
| `LGP_DB_URL` | _(empty)_ | Full async DB URL, e.g. `postgresql+asyncpg://user:pass@host:5432/db` | `RDS_DATABASE_URL` |

### Compute

| Variable | Default | Description |
|---|---|---|
| `LGP_COMPUTE_BACKEND` | `local` | Execution context: `local` or `lambda` |
| `LGP_MAX_CONCURRENT_CONNECTORS` | `5` | Max parallel connector runs in `IngestionRunner` |

### LLM

| Variable | Default | Description | Fallback |
|---|---|---|---|
| `LGP_LLM_PROVIDER` | `openai` | Provider: `openai`, `anthropic`, or `fixture` | — |
| `LGP_LLM_MODEL` | `gpt-4o-mini` | Model identifier passed to the provider | — |
| `LGP_LLM_API_KEY` | _(empty)_ | API key for the LLM provider | `ANTHROPIC_API_KEY` |

### API Keys

| Variable | Default | Description | Fallback |
|---|---|---|---|
| `LGP_FDA_API_KEY` | _(empty)_ | FDA openFDA API key (optional; unauthenticated rate limit applies) | — |
| `LGP_EXA_API_KEY` | _(empty)_ | Exa.ai research API key | `EXA_API_KEY` |
| `LGP_COMPTOX_API_KEY` | _(empty)_ | EPA CompTox dashboard API key | `CTX_API_KEY` |
| `LGP_CONGRESS_API_KEY` | _(empty)_ | Congress.gov / data.gov API key (required for legislation connector) | `DATA_GOV_API_KEY` |
| `LGP_PUBMED_API_KEY` | _(empty)_ | NCBI/PubMed E-utilities API key (optional; increases rate limit) | `PUBMED_API_KEY` |
| `LGP_REGULATIONS_GOV_API_KEY` | _(empty)_ | Regulations.gov API key (required) | `REGULATIONS_GOV_API_KEY` |
| `LGP_COURTLISTENER_API_KEY` | _(empty)_ | CourtListener token (optional; increases rate limit) | `COURTLISTENER_API_TOKEN` |
| `LGP_EPA_API_KEY` | _(empty)_ | EPA ECHO enforcement API key | `EPA_API_KEY` |
| `LGP_PACER_USERNAME` | _(empty)_ | PACER login username | — |
| `LGP_PACER_PASSWORD` | _(empty)_ | PACER login password | — |

### Logging

| Variable | Default | Description |
|---|---|---|
| `LGP_LOG_LEVEL` | `INFO` | Log level: `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `LGP_LOG_FORMAT` | `console` | Log format: `console` (human-readable) or `json` (structured) |

---

## Switching from SQLite to PostgreSQL

### Step 1: Start a PostgreSQL Instance

```bash
docker run -d \
  --name lexgenius-pg \
  -e POSTGRES_USER=lexgenius \
  -e POSTGRES_PASSWORD=secret \
  -e POSTGRES_DB=lexgenius \
  -p 5432:5432 \
  postgres:16-alpine
```

### Step 2: Install the PostgreSQL Driver

```bash
pip install -e ".[postgresql]"
# or: pip install "asyncpg>=0.29"
```

### Step 3: Update .env

```dotenv
LGP_DB_BACKEND=postgresql
LGP_DB_URL=postgresql+asyncpg://lexgenius:secret@localhost:5432/lexgenius
```

### Step 4: Apply Migrations

```bash
alembic upgrade head
```

---

## AWS Lambda Deployment (SAM)

### Prerequisites

- [AWS SAM CLI](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html)
- An RDS PostgreSQL or Aurora Serverless v2 instance in the same VPC as the Lambda functions
- AWS credentials configured (`aws configure` or environment variables)

### Lambda Handler Reference

Three Lambda handlers are provided in the `deploy/` directory:

| Handler | Function | Trigger |
|---|---|---|
| `ingestion` | Runs all registered connectors for a given query | EventBridge schedule or SQS |
| `daily_report` | Executes `DailyReportPipeline` for the current date | EventBridge daily schedule |
| `investigation` | Executes `DrugInvestigationPipeline` for a named drug | On-demand invoke or SQS |

Each handler reads settings from environment variables and uses `NullPool` automatically when `LGP_COMPUTE_BACKEND=lambda`.

### Environment Variables for Lambda

Set these in your SAM template (`template.yaml`) or in AWS Systems Manager Parameter Store. Sensitive values should be stored in AWS Secrets Manager and injected at runtime.

```dotenv
LGP_DB_BACKEND=postgresql
LGP_COMPUTE_BACKEND=lambda

# Use LGP_DB_URL or the fallback RDS_DATABASE_URL
RDS_DATABASE_URL=postgresql+asyncpg://user:pass@rds-host.us-east-1.rds.amazonaws.com:5432/lexgenius

LGP_LLM_PROVIDER=anthropic
LGP_LLM_API_KEY=sk-ant-...

LGP_FDA_API_KEY=...
LGP_CONGRESS_API_KEY=...
LGP_COURTLISTENER_API_KEY=...
```

### Connection Pooling Note

When `LGP_COMPUTE_BACKEND=lambda`, the engine factory uses SQLAlchemy `NullPool`. Each Lambda invocation opens a fresh database connection and closes it when the handler returns. This prevents RDS `max_connections` exhaustion across concurrent invocations.

For sustained high-throughput workloads (hundreds of concurrent invocations), place **RDS Proxy** in front of the database. RDS Proxy maintains a persistent pool on the proxy side and multiplexes Lambda connections onto it, dramatically reducing the connection count seen by RDS.

### Build and Deploy

```bash
# Build the Lambda deployment package
sam build

# First deploy — interactive, saves samconfig.toml
sam deploy --guided

# Subsequent deploys
sam deploy
```

### VPC and Security Group Configuration

Lambda functions that access RDS must run inside the same VPC:

1. Place both the Lambda functions and the RDS instance in the same VPC.
2. Create a security group for Lambda and a security group for RDS.
3. Add an inbound rule on the **RDS security group** allowing TCP 5432 from the **Lambda security group**.
4. Configure the Lambda functions with:
   - At least two private subnets (for AZ redundancy)
   - A NAT Gateway (or VPC endpoints) to allow outbound internet access for external API calls

### Running Alembic Migrations Against RDS

Alembic migrations must be run from a host with network access to RDS — not from within the Lambda function.

Suitable runners:
- A CI/CD pipeline with VPC access (e.g. GitHub Actions self-hosted runner, AWS CodeBuild)
- A bastion host / EC2 instance in the same VPC
- A developer machine with a VPN or SSH tunnel to the VPC

```bash
export LGP_DB_BACKEND=postgresql
export LGP_DB_URL=postgresql+asyncpg://user:pass@rds-host.us-east-1.rds.amazonaws.com:5432/lexgenius
pip install "asyncpg>=0.29"

# Apply all pending migrations
alembic upgrade head

# Generate a new migration after model changes
alembic revision --autogenerate -m "describe your change"
alembic upgrade head
```

### RDS Configuration Recommendations

| Setting | Recommended Value | Reason |
|---|---|---|
| Engine | PostgreSQL 16 or Aurora Serverless v2 | Aurora scales to zero when idle |
| Instance class | `db.t4g.medium` (small workloads) | Cost-effective; upgrade as query volume grows |
| Multi-AZ | Enabled for production | Automatic failover |
| Storage | GP3, 20 GB minimum | Adjust based on record growth |
| `max_connections` | Default (varies by instance class) | Use RDS Proxy if Lambda concurrency > 50 |
| Automated backups | 7 days | Allows point-in-time restore |
| Enhanced monitoring | Enabled | Surfaces wait events and slow queries |
