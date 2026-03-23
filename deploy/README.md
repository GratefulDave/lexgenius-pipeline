# LexGenius Pipeline — Deployment Guide

## Local Development

### Setup

```bash
# Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate

# Install with dev dependencies
pip install -e ".[dev]"

# Copy and configure environment variables
cp .env.example .env
# Edit .env — defaults use SQLite, no further DB config needed for local dev

# Apply database migrations
alembic upgrade head

# Run the CLI
lexgenius --help
```

### Running Tests

```bash
.venv/bin/python -m pytest tests/unit/ -v --tb=short
```

---

## Switching from SQLite to PostgreSQL

1. Start a local PostgreSQL instance (e.g. via Docker):

```bash
docker run -d \
  --name lexgenius-pg \
  -e POSTGRES_USER=lexgenius \
  -e POSTGRES_PASSWORD=secret \
  -e POSTGRES_DB=lexgenius \
  -p 5432:5432 \
  postgres:16-alpine
```

2. Install the PostgreSQL driver:

```bash
pip install -e ".[postgresql]"
```

3. Update `.env`:

```dotenv
LGP_DB_BACKEND=postgresql
LGP_DB_URL=postgresql+asyncpg://lexgenius:secret@localhost:5432/lexgenius
```

4. Run migrations:

```bash
alembic upgrade head
```

---

## AWS Lambda Deployment (SAM)

### Prerequisites

- [AWS SAM CLI](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html)
- An RDS PostgreSQL instance (or Aurora Serverless v2) in the same VPC as the Lambda functions
- AWS credentials configured (`aws configure` or environment variables)

### Environment Variables for Lambda

Set these in your SAM template or AWS Console / Parameter Store:

```dotenv
LGP_DB_BACKEND=postgresql
LGP_COMPUTE_BACKEND=lambda
# Use RDS_DATABASE_URL (picked up as fallback) or LGP_DB_URL
RDS_DATABASE_URL=postgresql+asyncpg://user:pass@rds-host.us-east-1.rds.amazonaws.com:5432/lexgenius
LGP_LLM_PROVIDER=anthropic
LGP_LLM_API_KEY=sk-ant-...
```

> **Connection pooling note**: When `LGP_COMPUTE_BACKEND=lambda`, the engine uses
> `NullPool` — each invocation opens a fresh connection and closes it on exit.
> This avoids exhausting RDS `max_connections` across concurrent Lambda instances.
> For sustained high-throughput workloads consider using RDS Proxy in front of your
> database to manage connection pooling at the proxy layer.

### Build and Deploy

```bash
# Build the deployment package
sam build

# Deploy (interactive first time — saves samconfig.toml for subsequent runs)
sam deploy --guided

# Subsequent deploys
sam deploy
```

### Running Alembic Migrations Against RDS

Migrations should be run from a machine (CI/CD runner, bastion host, or local dev)
that has network access to the RDS instance — **not** from the Lambda function itself.

```bash
# Set your RDS URL
export LGP_DB_BACKEND=postgresql
export LGP_DB_URL=postgresql+asyncpg://user:pass@rds-host.us-east-1.rds.amazonaws.com:5432/lexgenius

# Install the PostgreSQL driver if not already installed
pip install "asyncpg>=0.29"

# Apply all pending migrations
alembic upgrade head

# Generate a migration after model changes
alembic revision --autogenerate -m "describe your change"
alembic upgrade head
```

### VPC / Security Group Configuration

- Place the Lambda functions and RDS instance in the same VPC.
- Add an inbound rule on the RDS security group allowing TCP 5432 from the Lambda security group.
- Lambda requires a VPC config with at least two private subnets and a NAT Gateway (or VPC endpoints) for outbound internet access.

---

## Environment Variable Reference

| Variable | Default | Description |
|---|---|---|
| `LGP_DB_BACKEND` | `sqlite` | `sqlite` or `postgresql` |
| `LGP_DB_PATH` | `lexgenius_pipeline.db` | SQLite file path (sqlite only) |
| `LGP_DB_URL` | _(empty)_ | Full async DB URL (required for postgresql) |
| `RDS_DATABASE_URL` | _(empty)_ | Fallback DB URL (AWS convention) |
| `LGP_COMPUTE_BACKEND` | `local` | `local` or `lambda` |
| `LGP_LLM_PROVIDER` | `openai` | `openai`, `anthropic`, or `fixture` |
| `LGP_LLM_MODEL` | `gpt-4o-mini` | Model identifier |
| `LGP_LLM_API_KEY` | _(empty)_ | API key for the LLM provider |
| `LGP_LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `LGP_LOG_FORMAT` | `console` | `console` or `json` |
