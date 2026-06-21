# Portcast Assessment

This repository contains my implementation of the Portcast per-customer quota metering take-home assignment. It uses PostgreSQL-backed monthly counters and reservations to handle concurrent requests, retries, and downstream failures.

The design decisions, load-test results, and known limits are documented in [DESIGN.md](DESIGN.md).

## Run with Docker

Docker is the only prerequisite.

```bash
docker compose up --build -d
```

This starts PostgreSQL, applies the SQL migrations and seed data on first startup, then starts the API on port 8000.

Open the API documentation at [http://localhost:8000/docs](http://localhost:8000/docs).

## API

| Method | Path | Purpose |
| --- | --- | --- |
| `PUT` | `/admin/orgs/{org_id}/features/{feature}/quota` | Create or update a monthly quota limit |
| `POST` | `/user/orgs/{org_id}/features/{feature}/items` | Process items using quota |
| `GET` | `/quota/orgs/{org_id}/features/{feature}` | Read current usage and reset time |

## Project Structure

```text
app/
  api/          FastAPI routes
  quota/        Quota service, repository, and monthly period logic
  config.py     Application settings
  db.py         Database engine and sessions
  main.py       FastAPI application

migrations/     PostgreSQL schema and seed data
scripts/        Load tests and expired-reservation cleanup
tests/          API, integration, period, and concurrency tests
```

The consumer endpoint requires an `Idempotency-Key` header. It calculates quota units from the number of items in the request.

Example request:

```bash
curl -X POST \
  http://localhost:8000/user/orgs/00000000-0000-0000-0000-000000000001/features/container-tracking/items \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: example-request-1' \
  -d '{"items":["container-1","container-2"]}'
```

The seed data includes four features with different limits across ten example organizations. See `migrations/002_seed.sql` for their IDs and limits.

## Local Python Setup

Python 3.13 and PostgreSQL 18 are used by the project.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export DATABASE_URL=postgresql://portcast:portcast@localhost:5432/portcast
```

PostgreSQL can be started separately with:

```bash
docker compose up -d db
```

Start the API locally:

```bash
python -m uvicorn app.main:app --reload
```

## Tests

With PostgreSQL running:

```bash
python -m pytest
```

The test suite includes concurrent requests against the same quota bucket and verifies that accepted units never exceed the configured limit.

## Load Tests

Measure the quota reservation path directly:

```bash
docker compose exec app python -m scripts.load_test_quota \
  --rate 250 --duration 10 --concurrency 30 --organizations 100 --warmup 200
```

Measure the complete consumer request:

```bash
docker compose exec app python -m scripts.load_test_api \
  --rate 200 --duration 10 --concurrency 30 --organizations 100 --warmup 200
```

Both scripts run inside the application container. They accept options for rate, duration, concurrency, organization count, and warmup requests.

## Expired Reservations

Reservations that are not committed or released expire after five minutes. Run the cleanup script with:

```bash
docker compose exec app python -m scripts.cleanup_expired_reservations
```
