from running_coach.utils.status_summary import (
    compile_checkin_summary,
    format_completed_workouts,
    format_fitness_pmc,
)


class TestFormatCompletedWorkouts:
    def test_renders_core_session_fields_and_empty_states(self):
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
        assert format_completed_workouts([]) == "No completed sessions found."
        assert format_completed_workouts(None) == ""


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

    def test_progress_bar_load_context_and_cap(self):
        out = format_fitness_pmc(self._fitness())
        assert "**50%**" in out
        assert "█████░░░░░" in out
        assert "ATL (Fatigue)" not in out
        assert "TSB (Form)" not in out
        assert "Load context (analysis only, not displayed): ATL `50.0` | TSB `-10.0`" in out
        assert "**100%**" in format_fitness_pmc(self._fitness(ctl_end=120.0))
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
            recovery_baseline="HRV -6% vs 28d, RHR +2 bpm, sleep 7.1h (-15 min)",
        )
        for heading in ("Fitness PMC", "Recovery Trends", "Completed Workouts",
                        "Calendar & Travel Notes", "Upcoming Scheduled Workouts"):
            assert heading in out
        assert "- 5-day vs 28-day baseline (pre-computed): HRV -6% vs 28d, RHR +2 bpm" in out
