from datetime import date, datetime

from running_coach.utils.date_helpers import (
    calculate_age,
    get_today_date,
    parse_date,
    parse_iso_timestamp,
)


def test_parse_iso_timestamp():
    for raw, expected in [
        ("2026-09-15", datetime(2026, 9, 15, 0, 0, 0)),
        ("2026-09-15T14:30:00", datetime(2026, 9, 15, 14, 30, 0)),
        ("2026-09-15 14:30:00", datetime(2026, 9, 15, 14, 30, 0)),
        ("2026-09-15T14:30:00.123456", datetime(2026, 9, 15, 14, 30, 0)),
        ("2026-09-15T14:30", datetime(2026, 9, 15, 14, 30, 0)),  # no seconds component
        ("2026-09-15T14:30:00+02:00", datetime(2026, 9, 15, 0, 0, 0)),  # tz falls back to the date part
        (date(2026, 1, 2), datetime(2026, 1, 2)),
        # Unparseable, and strict about free-text month names.
        (None, None), ("   ", None), ("15/09/2026", None), ("November 1st, 2026", None),
    ]:
        assert parse_iso_timestamp(raw) == expected, raw
    dt = datetime(2026, 1, 2, 3, 4, 5)
    assert parse_iso_timestamp(dt) is dt


def test_parse_date():
    for raw in ["2026-09-15", "2026-09-15T14:30:00", "2026-09-15 14:30:00",
                datetime(2026, 9, 15, 8, 0), date(2026, 9, 15)]:
        assert parse_date(raw) == date(2026, 9, 15), raw
    for raw in [None, "", "garbage"]:
        assert parse_date(raw) is None, raw


def test_calculate_age():
    today = get_today_date()
    for month, day in [(12, 31), (1, 1)]:  # birthday not yet reached / already passed
        expected = 30 if (today.month, today.day) >= (month, day) else 29
        assert calculate_age(date(today.year - 30, month, day).isoformat()) == str(expected)
    assert calculate_age(None) is None
    assert calculate_age(date(today.year + 5, 1, 1).isoformat()) == "0"
