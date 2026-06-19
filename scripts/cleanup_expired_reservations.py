import asyncio

from sqlalchemy import text

from app.db import AsyncSessionLocal


BATCH_SIZE = 500


async def expire_batch(db) -> int:
    async with db.begin():
        result = await db.execute(
            text(
                """
                WITH candidates AS (
                    SELECT reservation_id
                    FROM quota_reservations
                    WHERE status = 'reserved'
                      AND expires_at <= now()
                    ORDER BY expires_at
                    LIMIT :batch_size
                    FOR UPDATE SKIP LOCKED
                ),
                expired AS (
                    UPDATE quota_reservations AS reservation
                    SET status = 'expired', updated_at = now()
                    FROM candidates
                    WHERE reservation.reservation_id = candidates.reservation_id
                      AND reservation.status = 'reserved'
                    RETURNING reservation.org_id,
                              reservation.feature,
                              reservation.period_start,
                              reservation.units
                ),
                totals AS (
                    SELECT org_id,
                           feature,
                           period_start,
                           SUM(units)::integer AS units
                    FROM expired
                    GROUP BY org_id, feature, period_start
                ),
                updated_counters AS (
                    UPDATE quota_counters AS counter
                    SET reserved_units = counter.reserved_units - totals.units,
                        updated_at = now()
                    FROM totals
                    WHERE counter.org_id = totals.org_id
                      AND counter.feature = totals.feature
                      AND counter.period_start = totals.period_start
                    RETURNING counter.org_id
                )
                SELECT COUNT(*)::integer
                FROM expired
                """
            ),
            {"batch_size": BATCH_SIZE},
        )
        return result.scalar_one()


async def main() -> None:
    total = 0

    async with AsyncSessionLocal() as db:
        while True:
            expired = await expire_batch(db)
            total += expired

            if expired < BATCH_SIZE:
                break

    print(f"Expired {total} reservation(s).")


if __name__ == "__main__":
    asyncio.run(main())
