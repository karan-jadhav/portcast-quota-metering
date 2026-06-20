import asyncio
import math
from time import perf_counter
from uuid import UUID, uuid4

import httpx
import typer
from rich.console import Console
from rich.table import Table
from sqlalchemy import text

from app.db import AsyncSessionLocal
from app.quota.service import configure_quota


FEATURE = "benchmark-feature"
console = Console(width=120)


def percentile(values: list[float], percentage: int) -> float:
    values = sorted(values)
    index = math.ceil(len(values) * percentage / 100) - 1
    return values[max(index, 0)]


async def cleanup(org_ids: list[UUID]) -> None:
    async with AsyncSessionLocal() as db:
        async with db.begin():
            for table in ("quota_reservations", "quota_counters", "quota_limits"):
                await db.execute(
                    text(
                        f"DELETE FROM {table} "
                        "WHERE org_id = ANY(CAST(:org_ids AS uuid[]))"
                    ),
                    {"org_ids": org_ids},
                )


async def run(
    rate: int, duration: int, concurrency: int, organizations: int
) -> None:
    requests = rate * duration
    org_ids = [uuid4() for _ in range(organizations)]

    for org_id in org_ids:
        async with AsyncSessionLocal() as db:
            await configure_quota(
                db, org_id, FEATURE, math.ceil(requests / organizations) + 1
            )

    limits = httpx.Limits(max_connections=concurrency)
    async with httpx.AsyncClient(
        base_url="http://127.0.0.1:8000",
        limits=limits,
        timeout=30,
    ) as client:
        semaphore = asyncio.Semaphore(concurrency)
        results: list[tuple[str, float]] = []

        async def consume(index: int) -> None:
            async with semaphore:
                started = perf_counter()
                response = await client.post(
                    f"/user/orgs/{org_ids[index % organizations]}"
                    f"/features/{FEATURE}/items",
                    headers={"Idempotency-Key": f"benchmark-{index}"},
                    json={"items": [f"item-{index}"]},
                )
                outcome = "accepted" if response.status_code == 200 else "error"
                results.append((outcome, (perf_counter() - started) * 1000))

        try:
            console.print(
                f"Running {requests:,} consumer requests at {rate:,}/s "
                f"across {organizations} organization(s)..."
            )
            started = perf_counter()
            tasks = []
            for index in range(requests):
                delay = started + index / rate - perf_counter()
                if delay > 0:
                    await asyncio.sleep(delay)
                tasks.append(asyncio.create_task(consume(index)))

            await asyncio.gather(*tasks)
            elapsed = perf_counter() - started

            outcomes = [outcome for outcome, _ in results]
            latencies = [latency for _, latency in results]
            table = Table(title="consumer API benchmark")
            columns = (
                "Target/s",
                "Achieved/s",
                "Accepted",
                "Errors",
                "p50 ms",
                "p95 ms",
                "p99 ms",
            )
            for column in columns:
                table.add_column(column, justify="right")
            table.add_row(
                str(rate),
                f"{len(results) / elapsed:.0f}",
                str(outcomes.count("accepted")),
                str(outcomes.count("error")),
                f"{percentile(latencies, 50):.2f}",
                f"{percentile(latencies, 95):.2f}",
                f"{percentile(latencies, 99):.2f}",
            )
            console.print(table)
        finally:
            await cleanup(org_ids)


def main(
    rate: int = typer.Option(50, min=1),
    duration: int = typer.Option(10, min=1),
    concurrency: int = typer.Option(10, min=1),
    organizations: int = typer.Option(100, min=1),
) -> None:
    asyncio.run(run(rate, duration, concurrency, organizations))


if __name__ == "__main__":
    typer.run(main)
