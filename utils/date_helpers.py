from datetime import datetime, date, timedelta
from typing import Optional, Union

def get_today_date() -> date:
    """Returns today's date."""
    return datetime.now().date()

def get_today_str(with_weekday: bool = False) -> str:
    """Returns today's date formatted as YYYY-MM-DD or YYYY-MM-DD (Weekday)."""
    fmt = "%Y-%m-%d (%A)" if with_weekday else "%Y-%m-%d"
    return datetime.now().strftime(fmt)

def get_past_date_str(days: int = 14) -> str:
    """Returns a date string (YYYY-MM-DD) for N days in the past."""
    return (get_today_date() - timedelta(days=days)).strftime("%Y-%m-%d")

def parse_date(date_input: Union[str, date, datetime, None]) -> Optional[date]:
    """Safely parses a date string, date, or datetime into a date object."""
    if date_input is None:
        return None
    if isinstance(date_input, datetime):
        return date_input.date()
    if isinstance(date_input, date):
        return date_input
    
    date_str = str(date_input).strip()
    if not date_str:
        return None
        
    # Clean timestamp ISO or space separator
    clean_str = date_str[:10]
    try:
        return datetime.strptime(clean_str, "%Y-%m-%d").date()
    except Exception:
        pass
        
    try:
        if "T" in date_str or " " in date_str:
            clean_ts = date_str.replace(" ", "T").split(".")[0]
            return datetime.strptime(clean_ts, "%Y-%m-%dT%H:%M:%S").date()
    except Exception:
        pass
        
    return None

def parse_iso_timestamp(timestamp_str: Optional[str]) -> Optional[datetime]:
    """Safely parses an ISO timestamp string into a datetime object."""
    if not timestamp_str:
        return None
    ts = str(timestamp_str).strip().replace(" ", "T").split(".")[0]
    try:
        if "T" in ts:
            return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S")
        else:
            return datetime.strptime(ts[:10], "%Y-%m-%d")
    except Exception:
        return None

def format_display_date(date_input: Union[str, date, datetime, None]) -> str:
    """Formats a date into 'Friday, Aug 07, 2026' or returns raw string on fallback."""
    if date_input is None:
        return ""
    if isinstance(date_input, (datetime, date)):
        return date_input.strftime("%A, %b %d, %Y")
        
    d_str = str(date_input).strip()
    parsed_dt = parse_iso_timestamp(d_str)
    if parsed_dt:
        if "T" in d_str and len(d_str) > 10:
            return parsed_dt.strftime("%A, %b %d, %Y at %H:%M:%S")
        return parsed_dt.strftime("%A, %b %d, %Y")
    return d_str

def calculate_age(dob_input: Union[str, date, datetime, None]) -> Optional[str]:
    """Accurately calculates age in years taking calendar month and day into account."""
    dob = parse_date(dob_input)
    if not dob:
        return None
    today = get_today_date()
    # Correct calendar age accounting for leap years and exact birth month/day
    age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
    return str(max(0, age))
