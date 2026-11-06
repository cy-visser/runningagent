from ..shared import dates as _dates
from ..shared.dates import (
    ISO_DATE_FMT,
    ISO_DATETIME_FMT,
    ISO_DATETIME_NO_SECONDS_FMT,
    DateLike,
    format_display_date,
    iso_week_key,
    parse_date,
    parse_iso_timestamp,
)

_now = _dates._now


def get_today_date():
    return _dates.get_today_date()


def get_today_str(with_weekday: bool = False) -> str:
    return _dates.get_today_str(with_weekday=with_weekday)
