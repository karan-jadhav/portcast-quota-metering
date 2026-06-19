from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass(frozen=True)
class QuotaPeriod:
    start: datetime
    end: datetime

    @property
    def next_reset_at(self) -> datetime:
        return self.end


def get_cycle_month(now: datetime) -> QuotaPeriod:
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")

    now = now.astimezone(UTC)

    start = datetime(now.year, now.month, 1, tzinfo=UTC)

    if now.month == 12:
        end = datetime(now.year + 1, 1, 1, tzinfo=UTC)
    else:
        end = datetime(now.year, now.month + 1, 1, tzinfo=UTC)

    return QuotaPeriod(start=start, end=end)
