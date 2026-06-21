from datetime import datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def upsert_quota_limit(
    db: AsyncSession,
    org_id: UUID,
    feature: str,
    limit_units: int,
):
    result = await db.execute(
        text(
            """
            INSERT INTO quota_limits (org_id, feature, limit_units)
            VALUES (:org_id, :feature, :limit_units)
            ON CONFLICT (org_id, feature)
            DO UPDATE SET limit_units = EXCLUDED.limit_units,
                          updated_at = now()
            RETURNING org_id, feature, limit_units
            """
        ),
        {
            "org_id": org_id,
            "feature": feature,
            "limit_units": limit_units,
        },
    )
    return result.mappings().one()


async def get_reservation_by_key(
    db: AsyncSession,
    org_id: UUID,
    feature: str,
    period_start: datetime,
    idempotency_key: str,
):
    result = await db.execute(
        text(
            """
            SELECT *
            FROM quota_reservations
            WHERE org_id = :org_id
              AND feature = :feature
              AND period_start = :period_start
              AND idempotency_key = :idempotency_key
            """
        ),
        {
            "org_id": org_id,
            "feature": feature,
            "period_start": period_start,
            "idempotency_key": idempotency_key,
        },
    )
    return result.mappings().one_or_none()


async def create_monthly_counter(
    db: AsyncSession,
    org_id: UUID,
    feature: str,
    period_start: datetime,
    period_end: datetime,
) -> None:
    await db.execute(
        text(
            """
            INSERT INTO quota_counters (
                org_id, feature, period_start, period_end, limit_units
            )
            SELECT org_id, feature, :period_start, :period_end, limit_units
            FROM quota_limits
            WHERE org_id = :org_id AND feature = :feature
            ON CONFLICT (org_id, feature, period_start) DO NOTHING
            """
        ),
        {
            "org_id": org_id,
            "feature": feature,
            "period_start": period_start,
            "period_end": period_end,
        },
    )


async def reserve_units(
    db: AsyncSession,
    org_id: UUID,
    feature: str,
    period_start: datetime,
    units: int,
):
    result = await db.execute(
        text(
            """
            UPDATE quota_counters
            SET reserved_units = reserved_units + :units,
                updated_at = now()
            WHERE org_id = :org_id
              AND feature = :feature
              AND period_start = :period_start
              AND limit_units - used_units - reserved_units >= :units
            RETURNING *, limit_units - used_units - reserved_units AS available_units
            """
        ),
        {
            "org_id": org_id,
            "feature": feature,
            "period_start": period_start,
            "units": units,
        },
    )
    return result.mappings().one_or_none()


async def create_reservation(
    db: AsyncSession,
    org_id: UUID,
    feature: str,
    period_start: datetime,
    idempotency_key: str,
    units: int,
    expires_at: datetime,
):
    result = await db.execute(
        text(
            """
            INSERT INTO quota_reservations (
                org_id,
                feature,
                period_start,
                idempotency_key,
                units,
                status,
                expires_at
            )
            SELECT
                :org_id,
                :feature,
                :period_start,
                :idempotency_key,
                :units,
                'reserved',
                :expires_at
            FROM quota_counters
            WHERE org_id = :org_id
              AND feature = :feature
              AND period_start = :period_start
            ON CONFLICT (org_id, feature, period_start, idempotency_key)
            DO NOTHING
            RETURNING *
            """
        ),
        {
            "org_id": org_id,
            "feature": feature,
            "period_start": period_start,
            "idempotency_key": idempotency_key,
            "units": units,
            "expires_at": expires_at,
        },
    )
    return result.mappings().one_or_none()


async def get_reservation_by_id(db: AsyncSession, reservation_id: UUID):
    result = await db.execute(
        text(
            """
            SELECT reservation_id,
                   org_id,
                   feature,
                   period_start,
                   idempotency_key,
                   units,
                   status,
                   expires_at,
                   created_at,
                   updated_at
            FROM quota_reservations
            WHERE reservation_id = :reservation_id
            """
        ),
        {"reservation_id": reservation_id},
    )
    return result.mappings().one_or_none()


async def commit_reservation(db: AsyncSession, reservation_id: UUID):
    result = await db.execute(
        text(
            """
            UPDATE quota_reservations
            SET status = 'committed', updated_at = now()
            WHERE reservation_id = :reservation_id
              AND status = 'reserved'
            RETURNING *
            """
        ),
        {"reservation_id": reservation_id},
    )
    reservation = result.mappings().one_or_none()

    if reservation is None:
        return None

    await db.execute(
        text(
            """
            UPDATE quota_counters
            SET reserved_units = reserved_units - :units,
                used_units = used_units + :units,
                updated_at = now()
            WHERE org_id = :org_id
              AND feature = :feature
              AND period_start = :period_start
            """
        ),
        {
            "org_id": reservation["org_id"],
            "feature": reservation["feature"],
            "period_start": reservation["period_start"],
            "units": reservation["units"],
        },
    )
    return reservation


async def release_reservation(db: AsyncSession, reservation_id: UUID):
    result = await db.execute(
        text(
            """
            UPDATE quota_reservations
            SET status = 'released', updated_at = now()
            WHERE reservation_id = :reservation_id
              AND status = 'reserved'
            RETURNING *
            """
        ),
        {"reservation_id": reservation_id},
    )
    reservation = result.mappings().one_or_none()

    if reservation is None:
        return None

    await db.execute(
        text(
            """
            UPDATE quota_counters
            SET reserved_units = reserved_units - :units,
                updated_at = now()
            WHERE org_id = :org_id
              AND feature = :feature
              AND period_start = :period_start
            """
        ),
        {
            "org_id": reservation["org_id"],
            "feature": reservation["feature"],
            "period_start": reservation["period_start"],
            "units": reservation["units"],
        },
    )
    return reservation


async def get_feature_usage(
    db: AsyncSession,
    org_id: UUID,
    feature: str,
    period_start: datetime,
):
    result = await db.execute(
        text(
            """
            SELECT COALESCE(counter.limit_units, quota_limit.limit_units)
                       AS limit_units,
                   COALESCE(counter.used_units, 0) AS used_units,
                   COALESCE(counter.reserved_units, 0) AS reserved_units,
                   COALESCE(counter.limit_units, quota_limit.limit_units)
                   - COALESCE(counter.used_units, 0)
                   - COALESCE(counter.reserved_units, 0) AS available_units
            FROM quota_limits AS quota_limit
            LEFT JOIN quota_counters AS counter
              ON counter.org_id = quota_limit.org_id
             AND counter.feature = quota_limit.feature
             AND counter.period_start = :period_start
            WHERE quota_limit.org_id = :org_id
              AND quota_limit.feature = :feature
            """
        ),
        {
            "org_id": org_id,
            "feature": feature,
            "period_start": period_start,
        },
    )
    return result.mappings().one_or_none()
