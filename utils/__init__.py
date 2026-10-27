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
from .goals import (
    KIND_NORTH_STAR,
    KIND_SUB_GOAL,
    current_goal,
    final_race_passed,
    format_gap,
    format_goal_plan,
    format_projection_vs_north_star,
    format_workout_goal_context,
    goal_target_s,
    is_plan,
    next_block,
    north_star,
    north_star_equivalent,
    race_duration_s,
    race_result_update,
    sub_goal_for_date,
    sub_goals_missing_result,
)
from .metrics import (
    coerce_mcp_payload,
    extract_health_metrics,
    extract_health_metrics_dated,
    parse_mcp_response,
)
from .profile_helpers import (
    RUNNER_ID_STATE_KEY,
    format_profile_summary,
    get_user_id,
    merge_profile_data,
    onboarding_prefill,
    parse_runner_name,
    profile_user_id,
    sync_profile_to_state,
)
from .race_readiness import (
    ANALYSIS_SCHEMA_VERSION,
    PROJECTION_WINDOW_DAYS,
    completed_runs,
    extract_thresholds,
    project_race,
    select_for_analysis,
    summarize_analysis,
)
from .status_summary import (
    compile_checkin_summary,
    format_nutrition_context_summary,
    format_recovery_metrics,
    format_schedule_audit_summary,
)
from .trajectory import (
    evaluate_goal_trajectory,
    parse_target_time_minutes,
    resolve_goal_distance,
)
from .workouts import (
    format_workout_analysis,
    is_workout_completed,
    select_primary_workout,
    format_other_sessions,
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
    # Goal plans
    "KIND_NORTH_STAR",
    "KIND_SUB_GOAL",
    "current_goal",
    "final_race_passed",
    "format_gap",
    "format_goal_plan",
    "format_projection_vs_north_star",
    "format_workout_goal_context",
    "goal_target_s",
    "is_plan",
    "next_block",
    "north_star",
    "north_star_equivalent",
    "race_duration_s",
    "race_result_update",
    "sub_goal_for_date",
    "sub_goals_missing_result",
    # MCP / metrics helpers
    "coerce_mcp_payload",
    "extract_health_metrics",
    "extract_health_metrics_dated",
    "parse_mcp_response",
    # Profile helpers
    "RUNNER_ID_STATE_KEY",
    "format_profile_summary",
    "get_user_id",
    "merge_profile_data",
    "onboarding_prefill",
    "parse_runner_name",
    "profile_user_id",
    "sync_profile_to_state",
    # Race readiness projection
    "ANALYSIS_SCHEMA_VERSION",
    "PROJECTION_WINDOW_DAYS",
    "completed_runs",
    "extract_thresholds",
    "project_race",
    "select_for_analysis",
    "summarize_analysis",
    # Status summary formatters
    "compile_checkin_summary",
    "format_nutrition_context_summary",
    "format_recovery_metrics",
    "format_schedule_audit_summary",
    # Trajectory
    "evaluate_goal_trajectory",
    "parse_target_time_minutes",
    "resolve_goal_distance",
    # Workouts
    "format_workout_analysis",
    "is_workout_completed",
    "select_primary_workout",
    "format_other_sessions",
    "partition_workouts_by_date",
]
