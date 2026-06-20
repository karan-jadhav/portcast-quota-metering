from datetime import UTC, datetime, timedelta, timezone

import pytest

from app.quota.period import get_cycle_month


def test_returns_current_month_in_utc() -> None:
    period = get_cycle_month(datetime(2026, 6, 20, 12, 30, tzinfo=UTC))

    assert period.start == datetime(2026, 6, 1, tzinfo=UTC)
    assert period.end == datetime(2026, 7, 1, tzinfo=UTC)
    assert period.next_reset_at == period.end


def test_converts_offset_before_selecting_month() -> None:
    india = timezone(timedelta(hours=5, minutes=30))

    period = get_cycle_month(datetime(2026, 7, 1, 1, 0, tzinfo=india))

    assert period.start == datetime(2026, 6, 1, tzinfo=UTC)
    assert period.end == datetime(2026, 7, 1, tzinfo=UTC)


def test_rolls_december_into_next_year() -> None:
    period = get_cycle_month(datetime(2026, 12, 31, 23, 59, tzinfo=UTC))

    assert period.start == datetime(2026, 12, 1, tzinfo=UTC)
    assert period.end == datetime(2027, 1, 1, tzinfo=UTC)


def test_rejects_naive_datetime() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        get_cycle_month(datetime(2026, 6, 20))
