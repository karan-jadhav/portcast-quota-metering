from datetime import UTC, datetime, timedelta
from typing import TypedDict
from uuid import UUID

from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from app.quota import repository
from app.quota.period import get_cycle_month


class QuotaExceededError(Exception):
    pass


class ReservationError(Exception):
    pass


class FeatureUsage(TypedDict):
    limit_units: int
    used_units: int
    reserved_units: int
    available_units: int
    next_reset_at: datetime


async def configure_quota(
    db: AsyncSession,
    org_id: UUID,
    feature: str,
    limit_units: int,
):
    if limit_units < 0:
        raise ValueError("limit_units cannot be negative")

    async with db.begin():
        return await repository.upsert_quota_limit(db, org_id, feature, limit_units)


async def get_feature_usage(
    db: AsyncSession,
    org_id: UUID,
    feature: str,
) -> FeatureUsage:
    now = datetime.now(UTC)
    period = get_cycle_month(now)
    usage = await repository.get_feature_usage(db, org_id, feature, period.start)

    if usage is None:
        raise ValueError("quota is not configured for this organization and feature")

    return {
        "limit_units": usage["limit_units"],
        "used_units": usage["used_units"],
        "reserved_units": usage["reserved_units"],
        "available_units": usage["available_units"],
        "next_reset_at": period.next_reset_at,
    }


async def reserve_quota(
    db: AsyncSession,
    org_id: UUID,
    feature: str,
    units: int,
    idempotency_key: str,
    now: datetime,
) -> tuple[RowMapping, bool]:
    if units <= 0:
        raise ValueError("units must be greater than zero")
    if not idempotency_key:
        raise ValueError("idempotency_key is required")

    period = get_cycle_month(now)
    expires_at = now.astimezone(UTC) + timedelta(minutes=5)

    async with db.begin():
        await repository.create_monthly_counter(
            db, org_id, feature, period.start, period.end
        )

        reservation = await repository.create_reservation(
            db,
            org_id,
            feature,
            period.start,
            idempotency_key,
            units,
            expires_at,
        )

        if reservation is None:
            existing = await repository.get_reservation_by_key(
                db, org_id, feature, period.start, idempotency_key
            )
            if existing is None:
                raise ValueError(
                    "quota is not configured for this organization and feature"
                )
            if existing["units"] != units:
                raise ValueError("idempotency key already used with different units")
            return existing, False

        counter = await repository.reserve_units(
            db, org_id, feature, period.start, units
        )
        if counter is None:
            raise QuotaExceededError("not enough quota available")

        return reservation, True


async def commit_reservation(db: AsyncSession, reservation_id: UUID):
    async with db.begin():
        reservation = await repository.commit_reservation(db, reservation_id)
        if reservation is not None:
            return reservation

        existing = await repository.get_reservation_by_id(db, reservation_id)
        if existing is None:
            raise ReservationError("reservation not found")
        if existing["status"] != "committed":
            raise ReservationError(f"cannot commit a {existing['status']} reservation")
        return existing


async def release_reservation(db: AsyncSession, reservation_id: UUID):
    async with db.begin():
        reservation = await repository.release_reservation(db, reservation_id)
        if reservation is not None:
            return reservation

        existing = await repository.get_reservation_by_id(db, reservation_id)
        if existing is None:
            raise ReservationError("reservation not found")
        if existing["status"] != "released":
            raise ReservationError(f"cannot release a {existing['status']} reservation")
        return existing
