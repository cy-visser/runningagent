from running_coach.utils.status_summary import (
    compile_checkin_summary,
    format_calendar_notes,
    format_completed_workouts,
    format_fitness_pmc,
    format_nutrition_context_summary,
    format_planned_workouts,
    format_recovery_metrics,
    format_schedule_audit_summary,
)


class TestFormatCompletedWorkouts:
    def test_renders_core_session_fields(self):
        out = format_completed_workouts([{
            "sport": "Run",
            "id": "w1",
            "title": "Morning Easy",
            "start_time": "2026-09-10T07:00:00",
            "distance_actual_km": 10.42,
            "tss_actual": 55,
        }])
        assert "[Run] 'Morning Easy' [w1]" in out
        assert "10.4km" in out
        assert "TSS: 55" in out

    def test_embeds_real_weather_conditions(self):
        """Regression: the check-in previously injected a placeholder instead of real data."""
        workouts = [{"sport": "Run", "start_time": "2026-09-10T07:00:00", "distance_actual_km": 10}]
        weather_map = {"2026-09-10T07:00:00": "18.2°C (feels 17.9°C), 71% hum, 9km/h wind"}
        out = format_completed_workouts(workouts, weather_map)
        assert "[Weather: 18.2°C (feels 17.9°C), 71% hum, 9km/h wind]" in out
        assert "Recorded conditions on" not in out

    def test_matches_weather_by_date_when_timestamp_differs(self):
        workouts = [{"sport": "Run", "start_time": "2026-09-10T07:00:00"}]
        out = format_completed_workouts(workouts, {"2026-09-10": "12°C, dry"})
        assert "[Weather: 12°C, dry]" in out

    def test_omits_weather_when_unavailable(self):
        out = format_completed_workouts([{"sport": "Run", "date": "2026-09-10"}], {})
        assert "Weather" not in out

    def test_empty_list_reports_no_sessions(self):
        assert format_completed_workouts([]) == "No completed sessions found."

    def test_none_renders_nothing(self):
        assert format_completed_workouts(None) == ""


class TestFormatPlannedWorkouts:
    def test_renders_planned_load(self):
        out = format_planned_workouts([{
            "sport": "Run", "id": "p1", "title": "Threshold",
            "date": "2026-09-20", "distance_planned_km": 12.0, "tss_planned": 80,
        }])
        assert "[Run] 'Threshold' [p1]" in out
        assert "12.0km" in out
        assert "Planned TSS: 80" in out

    def test_empty_list_reports_nothing_planned(self):
        assert format_planned_workouts([]) == "No upcoming workouts planned."


class TestFormatRecoveryMetrics:
    def test_averages_sleep_and_shows_latest_values(self):
        out = format_recovery_metrics({"sleep": [7.0, 8.0], "hrv": [45, 48], "rhr": [50, 52]})
        assert "Avg 7.5 hrs/night" in out
        assert "Latest: 48 ms" in out
        assert "Latest: 52 bpm" in out

    def test_reports_na_for_missing_series(self):
        out = format_recovery_metrics({"sleep": [], "hrv": [], "rhr": []})
        assert out.count("N/A") >= 3


class TestFormatFitnessPmc:
    def _fitness(self, **overrides):
        data = {
            "ctl_end": 40.0, "atl_end": 50.0, "tsb_end": -10.0,
            "trajectory_info": {
                "target_peak_ctl": 80.0,
                "reference_range": [75.0, 90.0],
                "required_ramp_rate": 4.0,
                "weeks_remaining": 12.0,
            },
        }
        data.update(overrides)
        return data

    def test_renders_progress_bar_and_percentage(self):
        out = format_fitness_pmc(self._fitness())
        assert "**50%**" in out
        assert "█████░░░░░" in out

    def test_drops_atl_and_tsb_rows_but_keeps_load_context(self):
        out = format_fitness_pmc(self._fitness())
        assert "ATL (Fatigue)" not in out
        assert "TSB (Form)" not in out
        assert "Load context (analysis only, not displayed): ATL `50.0` | TSB `-10.0`" in out

    def test_projection_row_sits_directly_under_ctl(self):
        projection = {
            "goal_label": "Marathon",
            "projection": {
                "goal_label": "Marathon", "today_s": 13500, "race_day_s": 13230,
                "goal_s": 12600, "gap_s": 630, "range_s": (13100, 13900),
                "confidence": "Medium", "stale": False, "readiness": "🟢",
                "drivers": [("Threshold anchor", "29' of threshold laps", "5:10/km (×0.91)")],
            },
        }
        lines = format_fitness_pmc(self._fitness(), projection).splitlines()
        ctl_idx = next(i for i, l in enumerate(lines) if "CTL (Fitness)" in l)
        row = lines[ctl_idx + 1]
        assert row.startswith("| **Projected Marathon** | Today `3:45:00` → Race day `3:40:30` | Goal: `3:30:00` (12.0w out)")
        assert "Gap (race day): `+10:30`" in row
        assert "Confidence: Medium" in row
        # Drivers table follows the metrics table after a blank line.
        assert lines[ctl_idx + 2] == ""
        assert lines[ctl_idx + 3] == "**Projection drivers:**"
        assert "| Threshold anchor | 29' of threshold laps | 5:10/km (×0.91) |" in lines

    def test_projection_row_reports_missing_goal_distance(self):
        out = format_fitness_pmc(self._fitness(), {"goal_label": None, "projection": None})
        assert "No race distance in goal" in out

    def test_caps_progress_at_one_hundred_percent(self):
        out = format_fitness_pmc(self._fitness(ctl_end=120.0))
        assert "**100%**" in out

    def test_none_renders_nothing(self):
        assert format_fitness_pmc(None) == ""


class TestCompileCheckinSummary:
    def test_omits_sections_with_no_data(self):
        out = compile_checkin_summary(
            lookback_days=14, lookahead_days=7,
            workouts_past=[], workouts_future=None,
            metrics_data=None, fitness_data=None, notes_list=None,
        )
        assert "Completed Workouts" in out
        assert "Fitness PMC Trends" not in out
        assert "Upcoming Scheduled Workouts" not in out

    def test_includes_every_populated_section(self):
        out = compile_checkin_summary(
            lookback_days=14, lookahead_days=7,
            workouts_past=[{"sport": "Run", "date": "2026-09-10"}],
            workouts_future=[{"sport": "Run", "date": "2026-09-20"}],
            metrics_data={"sleep": [7.0], "hrv": [45], "rhr": [50]},
            fitness_data={"ctl_end": 40.0, "atl_end": 45.0, "tsb_end": -5.0, "trajectory_info": {}},
            notes_list=[{"date": "2026-09-12", "title": "Travel"}],
        )
        for heading in ("Fitness PMC", "Recovery Trends", "Completed Workouts",
                        "Calendar & Travel Notes", "Upcoming Scheduled Workouts"):
            assert heading in out


class TestFormatScheduleAuditSummary:
    def test_summarises_volume_and_intensity_split(self):
        out = format_schedule_audit_summary([{
            "date_range": "Sep 14 - Sep 20, 2026",
            "total_distance_km": 52.345, "total_tss": 310.0,
            "easy_count": 4, "quality_count": 2, "bike_count": 1,
            "strength_count": 1, "other_sport_count": 0,
            "sessions": ["[Run] 'Easy' on Monday"], "travel_note": "Trip to Milan",
        }])
        assert "52.3 km (6 runs: 4 easy, 2 quality" in out
        assert "1 bike, 1 strength" in out
        assert "Planned TSS: 310.0" in out
        assert "Travel: Trip to Milan" in out

    def test_handles_an_empty_schedule(self):
        assert "Training Schedule Audit" in format_schedule_audit_summary([])


class TestFormatNutritionContextSummary:
    def test_includes_biometrics_and_upcoming_sessions(self):
        out = format_nutrition_context_summary(
            profile={"weight": "72kg", "age": "41", "training_goal": "Marathon", "timeline": "2026-11-01"},
            upcoming_workouts=[{"sport": "Run", "title": "Long Run", "date": "2026-09-16", "tss_planned": 120}],
            weather_forecast="- 2026-09-16: 22°C",
        )
        assert "Weight: 72kg" in out
        assert "'Long Run'" in out
        assert "22°C" in out

    def test_reports_when_nothing_is_scheduled(self):
        out = format_nutrition_context_summary(profile={}, upcoming_workouts=[])
        assert "No planned sessions in the next 3 days." in out


def test_format_calendar_notes_reports_empty_state():
    assert format_calendar_notes([]) == "No calendar notes."
