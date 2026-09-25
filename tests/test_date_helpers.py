from datetime import date, datetime

import pytest

from running_coach.utils.date_helpers import (
    calculate_age,
    format_display_date,
    get_past_date_str,
    get_today_date,
    iso_week_key,
    parse_date,
    parse_iso_timestamp,
)


class TestParseIsoTimestamp:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("2026-09-15", datetime(2026, 9, 15, 0, 0, 0)),
            ("2026-09-15T14:30:00", datetime(2026, 9, 15, 14, 30, 0)),
            ("2026-09-15 14:30:00", datetime(2026, 9, 15, 14, 30, 0)),
            ("2026-09-15T14:30:00.123456", datetime(2026, 9, 15, 14, 30, 0)),
            # No seconds component: regression guard for the refactor.
            ("2026-09-15T14:30", datetime(2026, 9, 15, 14, 30, 0)),
            # Trailing timezone falls back to the leading date component.
            ("2026-09-15T14:30:00+02:00", datetime(2026, 9, 15, 0, 0, 0)),
        ],
    )
    def test_parses_supported_formats(self, raw, expected):
        assert parse_iso_timestamp(raw) == expected

    @pytest.mark.parametrize("raw", [None, "", "   ", "not-a-date", "15/09/2026"])
    def test_returns_none_for_unparseable(self, raw):
        assert parse_iso_timestamp(raw) is None

    def test_passes_through_datetime(self):
        dt = datetime(2026, 1, 2, 3, 4, 5)
        assert parse_iso_timestamp(dt) is dt

    def test_promotes_date_to_datetime(self):
        assert parse_iso_timestamp(date(2026, 1, 2)) == datetime(2026, 1, 2)


class TestParseDate:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("2026-09-15", date(2026, 9, 15)),
            ("2026-09-15T14:30:00", date(2026, 9, 15)),
            ("2026-09-15 14:30:00", date(2026, 9, 15)),
            (datetime(2026, 9, 15, 8, 0), date(2026, 9, 15)),
            (date(2026, 9, 15), date(2026, 9, 15)),
        ],
    )
    def test_parses_supported_inputs(self, raw, expected):
        assert parse_date(raw) == expected

    @pytest.mark.parametrize("raw", [None, "", "garbage"])
    def test_returns_none_for_unparseable(self, raw):
        assert parse_date(raw) is None


class TestFormatDisplayDate:
    def test_date_only_omits_time(self):
        assert format_display_date("2026-09-15") == "Tuesday, Sep 15, 2026"

    def test_timestamp_includes_time(self):
        assert format_display_date("2026-09-15T07:05:00") == "Tuesday, Sep 15, 2026 at 07:05:00"

    def test_unparseable_returns_raw_string(self):
        assert format_display_date("sometime next week") == "sometime next week"

    def test_none_returns_empty_string(self):
        assert format_display_date(None) == ""


class TestIsoWeekKey:
    def test_formats_zero_padded_week(self):
        assert iso_week_key("2026-01-05") == "2026-W02"

    def test_same_key_for_days_in_one_week(self):
        assert iso_week_key("2026-09-14") == iso_week_key("2026-09-20")

    def test_differs_across_week_boundary(self):
        assert iso_week_key("2026-09-20") != iso_week_key("2026-09-21")

    def test_returns_none_for_unparseable(self):
        assert iso_week_key("nope") is None


class TestCalculateAge:
    def test_birthday_not_yet_reached_this_year(self):
        today = get_today_date()
        dob = date(today.year - 30, 12, 31)
        expected = 30 if (today.month, today.day) >= (12, 31) else 29
        assert calculate_age(dob.isoformat()) == str(expected)

    def test_birthday_already_passed_this_year(self):
        today = get_today_date()
        dob = date(today.year - 30, 1, 1)
        expected = 30 if (today.month, today.day) >= (1, 1) else 29
        assert calculate_age(dob.isoformat()) == str(expected)

    def test_returns_none_for_missing_dob(self):
        assert calculate_age(None) is None

    def test_future_dob_clamps_to_zero(self):
        future = date(get_today_date().year + 5, 1, 1)
        assert calculate_age(future.isoformat()) == "0"


def test_get_past_date_str_is_n_days_back():
    result = parse_date(get_past_date_str(days=14))
    assert (get_today_date() - result).days == 14


class TestParseTextDate:
    @pytest.mark.parametrize(
        "raw",
        ["November 1st, 2026", "November 1, 2026", "Nov 1 2026", "Nov. 1st 2026",
         "1 November 2026", "1st Nov 2026", "  november 1ST, 2026  "],
    )
    def test_parses_month_name_dates(self, raw):
        assert parse_date(raw) == date(2026, 11, 1)

    @pytest.mark.parametrize("raw", ["15/09/2026", "01-11-2026", "next spring", "November 2026", "Nov 31 2026"])
    def test_rejects_ambiguous_or_invalid(self, raw):
        assert parse_date(raw) is None

    def test_iso_timestamp_parser_stays_strict(self):
        assert parse_iso_timestamp("November 1st, 2026") is None
