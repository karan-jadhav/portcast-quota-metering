from datetime import UTC, datetime

import pytest
from sqlalchemy import text

from app.db import AsyncSessionLocal
from app.quota.service import (
    QuotaExceededError,
    commit_reservation,
    get_feature_usage,
    release_reservation,
    reserve_quota,
)
from scripts.cleanup_expired_reservations import expire_batch


async def test_reserve_commit_and_release(quota_factory) -> None:
    org_id, feature = await quota_factory(10)

    async with AsyncSessionLocal() as db:
        committed, _ = await reserve_quota(
            db, org_id, feature, 4, "commit-request", datetime.now(UTC)
        )
    async with AsyncSessionLocal() as db:
        await commit_reservation(db, committed["reservation_id"])

    async with AsyncSessionLocal() as db:
        released, _ = await reserve_quota(
            db, org_id, feature, 3, "release-request", datetime.now(UTC)
        )
    async with AsyncSessionLocal() as db:
        await release_reservation(db, released["reservation_id"])

    async with AsyncSessionLocal() as db:
        usage = await get_feature_usage(db, org_id, feature)

    assert usage["used_units"] == 4
    assert usage["available_units"] == 6


async def test_idempotency_does_not_reserve_twice(quota_factory) -> None:
    org_id, feature = await quota_factory(10)

    async with AsyncSessionLocal() as db:
        first, first_created = await reserve_quota(
            db, org_id, feature, 3, "same-key", datetime.now(UTC)
        )
    async with AsyncSessionLocal() as db:
        retry, retry_created = await reserve_quota(
            db, org_id, feature, 3, "same-key", datetime.now(UTC)
        )

    async with AsyncSessionLocal() as db:
        counter = (
            await db.execute(
                text(
                    """
                    SELECT reserved_units
                    FROM quota_counters
                    WHERE org_id = :org_id AND feature = :feature
                    """
                ),
                {"org_id": org_id, "feature": feature},
            )
        ).scalar_one()

    assert first["reservation_id"] == retry["reservation_id"]
    assert first_created is True
    assert retry_created is False
    assert counter == 3


async def test_batch_is_all_or_nothing(quota_factory) -> None:
    org_id, feature = await quota_factory(10)

    async with AsyncSessionLocal() as db:
        await reserve_quota(db, org_id, feature, 8, "accepted", datetime.now(UTC))

    with pytest.raises(QuotaExceededError):
        async with AsyncSessionLocal() as db:
            await reserve_quota(db, org_id, feature, 3, "rejected", datetime.now(UTC))

    async with AsyncSessionLocal() as db:
        row = (
            (
                await db.execute(
                    text(
                        """
                    SELECT reserved_units,
                           (SELECT COUNT(*) FROM quota_reservations
                            WHERE org_id = :org_id
                              AND idempotency_key = 'rejected') AS rejected_rows
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

    assert row["reserved_units"] == 8
    assert row["rejected_rows"] == 0


async def test_expired_reservation_returns_capacity(quota_factory) -> None:
    org_id, feature = await quota_factory(10)

    async with AsyncSessionLocal() as db:
        reservation, _ = await reserve_quota(
            db, org_id, feature, 2, "expired", datetime.now(UTC)
        )

    async with AsyncSessionLocal() as db:
        async with db.begin():
            await db.execute(
                text(
                    """
                    UPDATE quota_reservations
                    SET expires_at = now() - interval '1 minute'
                    WHERE reservation_id = :reservation_id
                    """
                ),
                {"reservation_id": reservation["reservation_id"]},
            )

    async with AsyncSessionLocal() as db:
        assert await expire_batch(db) == 1

    async with AsyncSessionLocal() as db:
        row = (
            (
                await db.execute(
                    text(
                        """
                    SELECT reservation.status, counter.reserved_units
                    FROM quota_reservations AS reservation
                    JOIN quota_counters AS counter
                      ON counter.org_id = reservation.org_id
                     AND counter.feature = reservation.feature
                     AND counter.period_start = reservation.period_start
                    WHERE reservation.reservation_id = :reservation_id
                    """
                    ),
                    {"reservation_id": reservation["reservation_id"]},
                )
            )
            .mappings()
            .one()
        )

    assert row["status"] == "expired"
    assert row["reserved_units"] == 0
