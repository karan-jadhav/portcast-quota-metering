import asyncio
from datetime import UTC, datetime

from sqlalchemy import text

from app.db import AsyncSessionLocal
from app.quota.service import QuotaExceededError, reserve_quota


async def test_concurrent_requests_never_exceed_limit(quota_factory) -> None:
    org_id, feature = await quota_factory(100)

    async def attempt(index: int) -> bool:
        async with AsyncSessionLocal() as db:
            try:
                await reserve_quota(
                    db,
                    org_id,
                    feature,
                    1,
                    f"request-{index}",
                    datetime.now(UTC),
                )
                return True
            except QuotaExceededError:
                return False

    results = await asyncio.gather(*(attempt(i) for i in range(1000)))

    async with AsyncSessionLocal() as db:
        counter = (
            (
                await db.execute(
                    text(
                        """
                    SELECT used_units, reserved_units,
                           limit_units - used_units - reserved_units AS available_units
                    FROM quota_counters
                    WHERE org_id = :org_id AND feature = :feature
                    """
                    ),
                    {"org_id": org_id, "feature": feature},
                )
            )
            .mappings()
            .one()
        )

    assert sum(results) == 100
    assert counter["used_units"] + counter["reserved_units"] == 100
    assert counter["available_units"] == 0


async def test_concurrent_retry_reserves_once(quota_factory) -> None:
    org_id, feature = await quota_factory(10)

    async def retry():
        async with AsyncSessionLocal() as db:
            return await reserve_quota(
                db,
                org_id,
                feature,
                1,
                "same-key",
                datetime.now(UTC),
            )

    reservations = await asyncio.gather(*(retry() for _ in range(50)))

    async with AsyncSessionLocal() as db:
        row = (
            (
                await db.execute(
                    text(
                        """
                    SELECT counter.reserved_units,
                           COUNT(reservation.reservation_id) AS reservations
                    FROM quota_counters AS counter
                    LEFT JOIN quota_reservations AS reservation
                      ON reservation.org_id = counter.org_id
                     AND reservation.feature = counter.feature
                     AND reservation.period_start = counter.period_start
                    WHERE counter.org_id = :org_id AND counter.feature = :feature
                    GROUP BY counter.reserved_units
                    """
                    ),
                    {"org_id": org_id, "feature": feature},
                )
            )
            .mappings()
            .one()
        )

    assert len({item["reservation_id"] for item in reservations}) == 1
    assert row["reserved_units"] == 1
    assert row["reservations"] == 1
