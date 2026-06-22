# LIS — Log Ingestor Service

A lightweight, high-throughput microservice for collecting structured log events from any number of applications and persisting them to PostgreSQL. Built with FastAPI and asyncpg.

---

## What it does

LIS receives structured log events over HTTP, buffers them in-memory, and flushes them to a PostgreSQL table in batches. It is designed to be the single place all your services send logs to, regardless of language or platform.

- Accepts single events or batches of up to 500 events per request
- Buffers events in an async queue and flushes on size (default 500) or time (default every 2 s)
- Persists to PostgreSQL with full ACID atomicity per batch
- Routes failed batches to a dead-letter table (`failed_batches`) for later inspection or replay
- Emits structured JSON logs to stdout for easy ingestion by log aggregators
- Retries DB connection on startup with exponential backoff (up to 5 attempts)
- Bearer token authentication on all ingest endpoints

---

## API endpoints

| Method | Path | Auth | Description |
| ------ | ---- | ---- | ----------- |
| `GET` | `/health` | No | Liveness probe — always returns `200 ok` |
| `GET` | `/ready` | No | Readiness probe — returns `503` if DB is unreachable |
| `POST` | `/v1/logs` | Yes | Ingest a single log event |
| `POST` | `/v1/logs/batch` | Yes | Ingest up to 500 log events in one call |
| `GET` | `/internal/batcher` | No | Live batcher stats (queued, flushed, errors) |

Interactive docs are available at `/docs` when the service is running.

---

## Log event shape

Every event must include these fields:

| Field | Type | Description |
| ----- | ---- | ----------- |
| `tenantId` | string | Which tenant/customer this log belongs to |
| `source` | string | Which service or app emitted it |
| `environment` | `dev` \| `staging` \| `prod` | Deployment environment |
| `level` | `debug` \| `info` \| `warn` \| `error` \| `fatal` | Severity |
| `type` | `app` \| `access` \| `audit` \| `ui` | Log category |
| `message` | string | Human-readable description of what happened |

Optional fields for richer context:

| Field | Description |
| ----- | ----------- |
| `occurredAt` | UTC timestamp of when the event happened at the source |
| `traceId`, `spanId`, `correlationId`, `requestId` | Distributed tracing identifiers |
| `userId` | The acting user |
| `path`, `method`, `statusCode`, `durationMs` | HTTP access log fields |
| `exception` | Error details: `{ name, message, stack }` |
| `properties` | Any extra JSON metadata you want to attach |

**Example payload:**

```json
{
  "tenantId": "acme",
  "source": "auth-service",
  "environment": "prod",
  "level": "error",
  "type": "app",
  "message": "Login failed: invalid password",
  "traceId": "a1b2c3d4",
  "userId": "user-42",
  "properties": { "ip": "10.0.0.10" }
}
```

---

## Where it fits

LIS is a backend ingest sink. Any service that can make an HTTP POST can send logs to it.

- **Backend services** (Node, Python, Go, Java, .NET) — send app, audit, and access logs
- **Frontend / browser apps** — send UI errors, unhandled promise rejections, user action trails
- **Mobile apps** — send crash reports and usage events via a thin SDK wrapper
- **API gateways / proxies** — forward access logs in bulk using the batch endpoint
- **CI/CD pipelines** — emit audit events on deployments, releases, and config changes

---

## Why use it

**Centralised observability.** Instead of every team writing logs to different places in different formats, everything flows through one schema-validated endpoint into one queryable table.

**Low-impact on callers.** The service responds `202 Accepted` immediately. Callers do not wait for the DB write — the batcher handles that asynchronously in the background.

**Resilient by default.** If the DB is temporarily unavailable, failed batches are preserved in the dead-letter table rather than silently dropped. The DB connection retries automatically on startup.

**Multi-tenant ready.** Every event carries a `tenantId`. The schema is designed so you can add row-level security or per-tenant API keys later without changing the ingest contract.

**Operationally simple.** One process, one database, no message broker required. Deploy it as a single Docker container.

---

## Running locally

**Prerequisites:** Docker, Python 3.12+

```bash
# 1. Start PostgreSQL
docker compose up -d postgres

# 2. Install dependencies
pip install -r requirements.txt

# 3. Copy env file and configure
cp .env.example .env

# 4. Apply migrations
psql $DATABASE_URL -f migrations/001_initial.sql
psql $DATABASE_URL -f migrations/002_dead_letter.sql

# 5. Start the service
uvicorn app.main:app --reload --port 8000
```

The service will be available at `http://localhost:8000`. Visit `/docs` for the interactive API explorer.

---

## Configuration

All configuration is via environment variables. See [.env.example](.env.example) for the full list.

| Variable | Default | Description |
| -------- | ------- | ----------- |
| `DATABASE_URL` | — | PostgreSQL connection string (required) |
| `INGEST_TOKEN` | — | Bearer token for auth (required outside `dev`) |
| `ENV` | `dev` | `dev` \| `staging` \| `prod` |
| `BATCH_MAX` | `500` | Flush when buffer reaches this many events |
| `BATCH_FLUSH_SEC` | `2` | Also flush every N seconds regardless of size |
| `QUEUE_MAX` | `20000` | Max in-memory events before backpressure (`503`) |
| `DB_POOL_MIN` / `DB_POOL_MAX` | `1` / `10` | DB connection pool size |

---

## Running tests

```bash
pip install -r requirements-dev.txt
docker compose up -d postgres
pytest
```

The test suite uses a real PostgreSQL database (`lis_test`) and covers ingest endpoints, batcher flush behaviour, dead-letter routing, and repository atomicity — 24 tests in total.

---

## Sending a log event

```bash
curl -X POST http://localhost:8000/v1/logs \
  -H "Authorization: Bearer your-token" \
  -H "Content-Type: application/json" \
  -d '{
    "tenantId": "acme",
    "source": "my-service",
    "environment": "dev",
    "level": "info",
    "type": "app",
    "message": "User signed in"
  }'
```

Response: `202 Accepted`

```json
{ "accepted": true }
```
