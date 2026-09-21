from datetime import date, datetime, timedelta
from typing import Optional, Union

DateLike = Union[str, date, datetime, None]

ISO_DATE_FMT = "%Y-%m-%d"
ISO_DATETIME_FMT = "%Y-%m-%dT%H:%M:%S"
ISO_DATETIME_NO_SECONDS_FMT = "%Y-%m-%dT%H:%M"


def get_today_date() -> date:
    """Returns today's date."""
    return datetime.now().date()


def get_today_str(with_weekday: bool = False) -> str:
    """Returns today's date formatted as YYYY-MM-DD or YYYY-MM-DD (Weekday)."""
    fmt = "%Y-%m-%d (%A)" if with_weekday else ISO_DATE_FMT
    return datetime.now().strftime(fmt)


def get_past_date_str(days: int = 14) -> str:
    """Returns a date string (YYYY-MM-DD) for N days in the past."""
    return (get_today_date() - timedelta(days=days)).strftime(ISO_DATE_FMT)


def parse_iso_timestamp(timestamp_input: DateLike) -> Optional[datetime]:
    """Safely parses an ISO date or timestamp into a datetime object.

    Accepts 'YYYY-MM-DD', 'YYYY-MM-DDTHH:MM[:SS]', space-separated timestamps,
    and fractional seconds. Returns None if nothing parseable is found.
    """
    if timestamp_input is None:
        return None
    if isinstance(timestamp_input, datetime):
        return timestamp_input
    if isinstance(timestamp_input, date):
        return datetime(timestamp_input.year, timestamp_input.month, timestamp_input.day)

    raw = str(timestamp_input).strip()
    if not raw:
        return None

    # Normalise separators and drop fractional seconds / timezone suffixes.
    ts = raw.replace(" ", "T").split(".")[0]
    for fmt in (ISO_DATETIME_FMT, ISO_DATETIME_NO_SECONDS_FMT):
        try:
            return datetime.strptime(ts, fmt)
        except ValueError:
            continue

    # Fall back to the leading date component (e.g. '2026-09-15T14:30:00+02:00').
    try:
        return datetime.strptime(ts[:10], ISO_DATE_FMT)
    except ValueError:
        return None


def parse_date(date_input: DateLike) -> Optional[date]:
    """Safely parses a date string, date, or datetime into a date object."""
    if isinstance(date_input, datetime):
        return date_input.date()
    if isinstance(date_input, date):
        return date_input
    parsed = parse_iso_timestamp(date_input)
    return parsed.date() if parsed else None


def format_display_date(date_input: DateLike) -> str:
    """Formats a date into 'Friday, Aug 07, 2026' or returns the raw string on fallback."""
    if date_input is None:
        return ""
    if isinstance(date_input, (datetime, date)):
        return date_input.strftime("%A, %b %d, %Y")

    d_str = str(date_input).strip()
    parsed_dt = parse_iso_timestamp(d_str)
    if not parsed_dt:
        return d_str
    # Only surface the time component when the input actually carried one.
    if len(d_str) > 10 and ("T" in d_str or " " in d_str):
        return parsed_dt.strftime("%A, %b %d, %Y at %H:%M:%S")
    return parsed_dt.strftime("%A, %b %d, %Y")


def iso_week_key(date_input: DateLike) -> Optional[str]:
    """Returns the canonical ISO week bucket key for a date, e.g. '2026-W37'."""
    d = parse_date(date_input)
    if not d:
        return None
    iso_year, iso_week, _ = d.isocalendar()
    return f"{iso_year}-W{iso_week:02d}"


def calculate_age(dob_input: DateLike) -> Optional[str]:
    """Accurately calculates age in years taking calendar month and day into account."""
    dob = parse_date(dob_input)
    if not dob:
        return None
    today = get_today_date()
    # Correct calendar age accounting for leap years and exact birth month/day
    age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
    return str(max(0, age))
