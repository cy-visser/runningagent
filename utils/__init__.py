"""Pure helper functions shared across the running coach agent.

Only symbols with callers outside this package are re-exported here; everything
else stays private to its own module.
"""

from .date_helpers import (
    calculate_age,
    format_display_date,
    get_past_date_str,
    get_today_date,
    get_today_str,
    iso_week_key,
    parse_date,
    parse_iso_timestamp,
)
from .metrics import (
    coerce_mcp_payload,
    extract_health_metrics,
    parse_mcp_response,
)
from .profile_helpers import (
    get_user_id,
    merge_profile_data,
    parse_runner_name,
    sync_profile_to_state,
)
from .status_summary import (
    compile_checkin_summary,
    format_nutrition_context_summary,
    format_recovery_metrics,
    format_schedule_audit_summary,
)
from .trajectory import evaluate_goal_trajectory
from .workouts import (
    format_workout_analysis,
    is_workout_completed,
    partition_workouts_by_date,
)

__all__ = [
    # Date helpers
    "calculate_age",
    "format_display_date",
    "get_past_date_str",
    "get_today_date",
    "get_today_str",
    "iso_week_key",
    "parse_date",
    "parse_iso_timestamp",
    # MCP / metrics helpers
    "coerce_mcp_payload",
    "extract_health_metrics",
    "parse_mcp_response",
    # Profile helpers
    "get_user_id",
    "merge_profile_data",
    "parse_runner_name",
    "sync_profile_to_state",
    # Status summary formatters
    "compile_checkin_summary",
    "format_nutrition_context_summary",
    "format_recovery_metrics",
    "format_schedule_audit_summary",
    # Trajectory
    "evaluate_goal_trajectory",
    # Workouts
    "format_workout_analysis",
    "is_workout_completed",
    "partition_workouts_by_date",
]
