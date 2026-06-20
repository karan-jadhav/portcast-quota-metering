# Portcast Quota Metering Assessment

This repository contains my implementation of the Portcast per-customer quota metering take-home assignment. It uses PostgreSQL-backed monthly counters and reservations to handle concurrent requests, retries, and downstream failures.

The design decisions, load-test results, and known limits are documented in [DESIGN.md](DESIGN.md).

## Run with Docker

Docker is the only prerequisite.

```bash
docker compose up --build
```

This starts PostgreSQL, applies the SQL migrations and seed data on first startup, then starts the API on port 8000.

Open the API documentation at [http://localhost:8000/docs](http://localhost:8000/docs).

The database is stored in a Docker volume. To stop the services:

```bash
docker compose down
```

To remove the database and recreate it from the seed data on the next start:

```bash
docker compose down -v
```

## API

| Method | Path | Purpose |
| --- | --- | --- |
| `PUT` | `/admin/orgs/{org_id}/features/{feature}/quota` | Configure a monthly limit |
| `POST` | `/user/orgs/{org_id}/features/{feature}/items` | Process items using quota |
| `GET` | `/quota/orgs/{org_id}/features/{feature}` | Read current usage and reset time |

The consumer endpoint requires an `Idempotency-Key` header. It calculates quota units from the number of items in the request.

Example request:

```bash
curl -X POST \
  http://localhost:8000/user/orgs/00000000-0000-0000-0000-000000000001/features/container-tracking/items \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: example-request-1' \
  -d '{"items":["container-1","container-2"]}'
```

The seed data includes `container-tracking` and `sailing-schedule` limits for three example organizations. See `migrations/002_seed.sql` for their IDs and limits.

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

## Benchmarks

Measure the quota reservation path directly:

```bash
python -m scripts.benchmark_quota
```

With the API running, measure the complete consumer request:

```bash
python -m scripts.benchmark_api
```

Both scripts use low local defaults and accept options for rate, duration, concurrency, and organization count.

## Expired Reservations

Reservations that are not committed or released expire after five minutes. Run the cleanup script with:

```bash
python -m scripts.cleanup_expired_reservations
```
