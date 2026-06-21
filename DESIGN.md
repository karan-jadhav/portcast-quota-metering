# Design

This implementation uses PostgreSQL-backed monthly counters and reservations. Quota is reserved with an atomic conditional update, then committed or released after the consumer operation finishes.

## Integration

I implemented the quota logic as a small application component used by a FastAPI service.

The demo consumer endpoint simulates a quota-consuming API operation. It calculates the required units from the number of items, asks the quota component to reserve those units before doing work, then commits or releases the reservation depending on whether the work succeeds. The client does not provide the unit count directly.

Features are strings rather than a fixed list, so the component is not tied to the demo operation.

PostgreSQL is used as the shared state store. This avoids per-instance counters, which would be incorrect with horizontally scaled API instances.

## Data model

There are three tables.

`quota_limits` stores the configured monthly limit for each organization and feature.

`quota_counters` stores the monthly aggregate state for one organization, feature, and period. It has `used_units` and `reserved_units`.

`quota_reservations` stores per-request reservation records. These records are used for idempotency, commit/release, and recovery from abandoned in-flight requests.

I keep `reserved_units` in `quota_counters` even though reservation rows also exist. This is intentional. The counter row is the fast aggregate used for enforcement. The reservation table is the per-request ledger. Calculating reserved quota by summing reservation rows on every request would make the hot path slower and harder to reason about under load.

## Monthly periods

A quota period is a calendar month in UTC.

For example, June 2026 starts at `2026-06-01T00:00:00Z` and ends at `2026-07-01T00:00:00Z`.

I use lazy reset. There is no destructive monthly reset job. A new `quota_counters` row is created for the current period when needed. Old period rows remain available for historical reporting.

The monthly limit is copied from `quota_limits` into `quota_counters` when the period row is created. I treat that value as a snapshot: later configuration changes do not modify an existing counter. The new limit applies the next time a counter is created, which may still be the current month if that feature has not been used yet.

This keeps the limit stable during an active period and avoids having to define what happens when a new limit is lower than units already used or reserved. The tradeoff is that a mid-month increase or decrease does not affect a counter that already exists.

## Concurrent correctness

The core quota check is a single conditional PostgreSQL update:

```sql
UPDATE quota_counters
SET reserved_units = reserved_units + :units,
    updated_at = now()
WHERE org_id = :org_id
  AND feature = :feature
  AND period_start = :period_start
  AND limit_units - used_units - reserved_units >= :units
RETURNING limit_units,
          used_units,
          reserved_units,
          limit_units - used_units - reserved_units AS available_units;
```

This avoids a read-then-write race.

PostgreSQL locks the updated counter row. Concurrent updates for the same organization, feature, and period serialize on that row. The condition is checked as part of the update, so only requests that fit within the remaining quota can reserve units.

If the update returns no row, the reservation transaction is rolled back. The database also has a check constraint that prevents `used_units + reserved_units` from exceeding the limit.

This is the main correctness guarantee.

The tradeoff is that a single very hot organization and feature becomes limited by one database row. I accept that tradeoff because strict quota enforcement requires serialization somewhere for that key.

## Batch behavior

Batch requests are all-or-nothing.

If a request asks for 100 units and only 60 are available, the whole request is rejected. The system does not partially reserve 60 units.

I chose this because partial fulfillment makes API behavior harder for clients and complicates downstream rollback. This keeps quota behavior aligned with the consumer operation: either the complete batch is accepted, or none of it is processed.

## Reservation lifecycle

A quota-consuming request follows this lifecycle:

1. Reserve quota.
2. Run the downstream operation.
3. Commit the reservation if the operation succeeds.
4. Release the reservation if the operation fails.

On reserve:

```text
quota_counters.reserved_units += units
quota_reservations.status = 'reserved'
```

On success:

```text
quota_counters.reserved_units -= units
quota_counters.used_units += units
quota_reservations.status = 'committed'
```

On failure:

```text
quota_counters.reserved_units -= units
quota_reservations.status = 'released'
```

The database transaction for reserving quota is short. I do not keep a transaction open while downstream work runs.

## Retries and idempotency

Each quota-consuming request includes an idempotency key.

`quota_reservations` has a unique constraint on:

```text
org_id, feature, period_start, idempotency_key
```

If the same request is retried with the same key, the existing reservation is returned instead of reserving quota again. If it is still reserved, the consumer returns `409 Conflict` and does not run the downstream operation again. A committed reservation returns the previous success. A retry using the same key with a different unit count is rejected.

Commit and release operations only apply to reservations still in `reserved` status. This prevents double-commit or double-release.

## Expired reservations

A request can reserve quota and then crash before commit or release. To avoid holding quota forever, each reservation has an `expires_at` timestamp.

Expired reservations are moved from `reserved` to `expired`, and their units are removed from `quota_counters.reserved_units`.

For this take-home, expiration is implemented as a cleanup script that processes reservations in batches of 500. It uses `FOR UPDATE SKIP LOCKED`, so multiple cleanup workers can run without processing the same reservation. In production, I would run this periodically as a scheduled job.

## Reporting

The usage endpoint returns the current period usage for an organization and feature:

```json
{
  "limit_units": 500,
  "used_units": 300,
  "reserved_units": 20,
  "available_units": 180,
  "next_reset_at": "2026-07-01T00:00:00Z"
}
```

`reserved_units` shows quota held by in-flight work. `available_units` excludes these reservations as well as committed usage.

## Load test results

The benchmarks were run locally with one application process and one PostgreSQL instance. I measured the direct quota component and the HTTP demo endpoint separately because the assignment's latency target applies to the quota operation in the request path.

These numbers are local benchmark results, not a production capacity claim. In production, I would repeat the same tests with the real deployment topology, database size, connection pool settings, and eight application instances sharing the same database.

### Hot organization correctness

The concurrency test sends 1,000 reservation attempts to the same organization and feature with a quota limit of 100.

Results:

```text
accepted: 100
rejected: 900
final used_units: 0
final reserved_units: 100
final available_units: 0
quota violations: 0
```

This test exercises reservation only, so the accepted units remain in `reserved_units` rather than `used_units`.

The final counter matched the configured limit exactly. A second concurrency test sends 50 requests with the same idempotency key and verifies that only one reservation and one unit are recorded.

### Distributed quota traffic

This benchmark calls the quota reservation component directly and spreads requests across 100 organizations.

I used 250 operations per second as a reproducible local target for measuring the single-process quota path.

The script first sends 200 unmeasured requests. This creates the monthly counters and warms the database connection pool before the measured requests begin.

```bash
python -m scripts.benchmark_quota \
  --rate 250 --duration 10 --concurrency 30 --organizations 100 --warmup 200
```

| Metric              |  Cold run | Warm run |
| ------------------- | --------: | -------: |
| Achieved throughput |     250/s |    250/s |
| Accepted            |     2,500 |    2,500 |
| Rejected            |         0 |        0 |
| Errors              |         0 |        0 |
| p50 latency         |   4.74 ms |  4.79 ms |
| p95 latency         |  36.16 ms |  6.99 ms |
| p99 latency         | 561.71 ms | 16.67 ms |
| Max latency         | 679.86 ms | 29.31 ms |

The cold run used `--warmup 0` and included counter creation and connection-pool startup. Once those were removed from the measured phase, the benchmark sustained 250 operations per second with p50 and p95 below 10 ms. The p99 result was 16.67 ms.

### Consumer API traffic

This benchmark sends requests through the demo consumer endpoint. It includes HTTP handling, request validation, quota reserve, the demo operation, and quota commit, so it is not directly comparable to the direct quota-operation benchmark.

This script also sends 200 unmeasured warmup requests before collecting results.

```bash
python -m scripts.benchmark_api \
  --rate 200 --duration 10 --concurrency 30 --organizations 100 --warmup 200
```

| Metric              |    Cold run |  Warm run |
| ------------------- | ----------: | --------: |
| Achieved throughput |       166/s |     200/s |
| Accepted            |       2,000 |     2,000 |
| Errors              |           0 |         0 |
| p50 latency         |   123.84 ms |  15.24 ms |
| p95 latency         |   623.81 ms | 142.03 ms |
| p99 latency         |   960.16 ms | 311.55 ms |
| Max latency         | 1,577.97 ms | 505.06 ms |

After warmup, the consumer endpoint sustained the requested 200 requests per second with no errors. The API benchmark is more sensitive to client scheduling, HTTP connection reuse, FastAPI validation, and the fact that each successful request performs both reserve and commit.

I use the direct quota benchmark as the main measurement for quota-operation overhead, and the API benchmark as an end-to-end smoke test of the demo consumer.

## Limits

The main bottleneck is a hot organization and feature. Strict enforcement means all updates for that organization, feature, and period must serialize somewhere. In this implementation, they serialize on the PostgreSQL counter row.

At larger scale, I would watch for:

* hot organizations creating row-lock contention
* database connection-pool saturation
* reservation table growth
* slow cleanup of expired reservations

With 50,000 organizations and 30 features, there can be up to 1.5 million active organization-feature combinations. PostgreSQL can store this volume, but counter and reservation history will continue to grow. I would consider time-based partitioning and retention rules once that history becomes large enough to affect maintenance or queries.

Connection pools must be budgeted across all application instances rather than sized independently. PgBouncer could be added if connection management becomes a bottleneck. Monthly counters could also be created before the next period to remove one statement from the normal reservation path, while keeping lazy creation as a fallback.

I would not shard counters unless the product could tolerate softer enforcement. For strict quotas, a single authoritative counter per organization, feature, and period is the simpler and safer design.

## Alternatives considered

### In-memory counters

Rejected because they are not shared across service instances. They would over-serve when multiple instances handle requests for the same organization.

### Read then write

Rejected because it has a race condition. Two requests can both read the same remaining quota and both deduct from it.

### Redis-only counter

Redis with Lua could enforce atomic counters, but PostgreSQL gives durable reservation records, idempotency, reporting, and transactional commit/release in one system. For this assessment, PostgreSQL is simpler to operate and verify.

### Distributed locks

Rejected because PostgreSQL row-level locking already gives the required serialization for the counter row. Adding a separate lock system would add complexity without improving correctness.

## AI assistance

I used AI assistance for design discussion, implementation suggestions, test and benchmark review, and wording help. I reviewed and changed the suggestions, ran the code and benchmarks locally, and made the final decisions about the submitted design and tradeoffs.
