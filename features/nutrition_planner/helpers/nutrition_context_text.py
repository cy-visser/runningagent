"""Formats athlete biometrics, upcoming training demands and weather forecast for nutrition planning."""

from typing import Optional

from ....shared.dates import format_display_date


def format_nutrition_context_summary(
    profile: dict,
    upcoming_workouts: list[dict],
    weather_forecast: Optional[str] = None,
    days_forward: int = 3,
    goal: Optional[dict] = None,
) -> str:
    """Formats athlete biometrics, upcoming training demands, and forecasted climate for nutrition planning.

    goal: the current goal (shared.goal_plan.current_goal); defaults to the profile's single-goal fields.
    """
    lines = ["### Athlete Nutrition & Fueling Context\n"]
    goal = goal or {"training_goal": profile.get("training_goal"), "timeline": profile.get("timeline")}

    lines.append("**1. Runner Biometrics & Target:**")
    weight = profile.get("weight") or "Not recorded"
    age = profile.get("age") or "Not recorded"
    goal_text = goal.get("training_goal") or "Not set"
    timeline = goal.get("timeline") or "Not set"
    lines.append(f"- Weight: {weight} | Age: {age}")
    lines.append(f"- Training Goal: {goal_text} (Target Date: {timeline})\n")

    lines.append(f"**2. Upcoming Training Sessions (Next {days_forward} Days):**")
    if upcoming_workouts:
        for w in upcoming_workouts:
            sport = w.get("sport", "Run")
            title = w.get("title") or sport
            date_str = format_display_date(w.get("date") or w.get("start_time"))
            dist = w.get("distance_planned_km") or 0.0
            hours = w.get("duration_planned")
            dur_str = f"{round(float(hours) * 60)} min" if isinstance(hours, (int, float)) and hours > 0 else "n/a"
            tss = w.get("tss_planned") or 0
            lines.append(f"- [{sport}] '{title}' on {date_str} | Distance: {dist}km | Duration: {dur_str} | Planned TSS: {tss}")
    else:
        lines.append(f"No planned sessions in the next {days_forward} days.")
    lines.append("")

    if weather_forecast:
        lines.append(f"**3. Local Climate & Weather Forecast:**\n{weather_forecast}\n")

    return "\n".join(lines)
