import unittest
from datetime import date, datetime

from utils import (
    # Date helpers
    get_today_date,
    get_today_str,
    get_past_date_str,
    parse_date,
    format_display_date,
    parse_iso_timestamp,
    calculate_age,
    # Profile helpers
    parse_runner_name,
    format_profile_summary,
    merge_profile_data,
    # Metrics helpers
    parse_mcp_response,
    extract_health_metrics,
    # Workouts helpers
    is_workout_completed,
    partition_workouts_by_date,
    format_workout_analysis,
    # Trajectory helpers
    evaluate_goal_trajectory,
    get_target_peak_ctl,
    resolve_target_peak_ctl,
    parse_target_time_minutes,
    # Visualization helpers
    generate_visual_progress_table,
    # Status summary formatters
    format_completed_workouts,
    format_planned_workouts,
    format_recovery_metrics,
    format_calendar_notes,
    format_fitness_pmc,
    compile_checkin_summary,
    format_schedule_audit_summary,
    format_nutrition_context_summary,
)


class TestUtils(unittest.TestCase):

    def test_date_helpers(self):
        d = parse_date("2026-08-25")
        self.assertEqual(d, date(2026, 8, 25))

        iso_dt = parse_iso_timestamp("2026-08-25T08:30:00")
        self.assertEqual(iso_dt, datetime(2026, 8, 25, 8, 30, 0))

        display = format_display_date("2026-08-25")
        self.assertIn("Aug 25, 2026", display)

        age = calculate_age("1990-05-15")
        self.assertIsNotNone(age)
        self.assertTrue(int(age) >= 30)

        self.assertIsInstance(get_today_date(), date)
        self.assertIsInstance(get_today_str(), str)
        self.assertIsInstance(get_past_date_str(7), str)

    def test_profile_helpers(self):
        fn, ln, uid = parse_runner_name("Alex Runner")
        self.assertEqual(fn, "Alex")
        self.assertEqual(ln, "Runner")
        self.assertEqual(uid, "alex_runner")

        profile = {
            "firstname": "Alex",
            "lastname": "Runner",
            "age": "34",
            "location": "Amsterdam",
            "training_goal": "Sub-3:30 Marathon",
        }
        summary = format_profile_summary(profile)
        self.assertIn("Alex Runner", summary)
        self.assertIn("Sub-3:30 Marathon", summary)

        merged = merge_profile_data(
            answers={"training_goal": "Marathon", "age": "35"},
            temp_data={"firstname": "Jane", "lastname": "Doe"},
            sleep_avg=7.5
        )
        self.assertEqual(merged["firstname"], "Jane")
        self.assertEqual(merged["sleep_hours_2w_avg"], 7.5)

    def test_metrics_helpers(self):
        envelope = {"content": [{"text": '{"metrics": [{"details": [{"type": 6, "value": 7.8}, {"type": 60, "value": 65}, {"type": 5, "value": 48}]}]}'}]}
        extracted = extract_health_metrics(envelope)
        self.assertEqual(extracted["sleep"], [7.8])
        self.assertEqual(extracted["hrv"], [65])
        self.assertEqual(extracted["rhr"], [48])

        self.assertIsNone(parse_mcp_response(None))
        self.assertEqual(parse_mcp_response({"content": [{"text": '{"ok": true}'}]}), {"ok": True})

    def test_workouts_helpers(self):
        self.assertTrue(is_workout_completed({"completed": True}))
        self.assertTrue(is_workout_completed({"distance_actual_km": 10.0}))
        self.assertFalse(is_workout_completed({"completed": False, "distance_actual_km": 0}))

        workouts = [
            {"date": "2026-08-20", "completed": True, "title": "Past Run"},
            {"date": "2026-08-30", "completed": False, "title": "Future Run"},
        ]
        past, future = partition_workouts_by_date(workouts, date(2026, 8, 25))
        self.assertEqual(len(past), 1)
        self.assertEqual(len(future), 1)

        analysis = format_workout_analysis({
            "workoutId": "12345",
            "totals": {"Distance": 10000, "Duration": 3000, "TSS": 65},
            "lapData": [{"Name": "Lap 1", "TotalDistance": 5000, "TotalMovingTime": 1500, "AverageHeartRate": 150}]
        }, title="Tempo Run", sport="Run")
        self.assertIn("Tempo Run", analysis)
        self.assertIn("Distance: 10.0km", analysis)
        self.assertIn("TSS: 65", analysis)

    def test_trajectory_helpers(self):
        self.assertEqual(parse_target_time_minutes("Sub-3:30 Marathon"), 210)
        self.assertEqual(parse_target_time_minutes("3 hours and 15 mins"), 195)
        self.assertEqual(parse_target_time_minutes("Sub-20 5K"), 20)

        ctl_target, ctl_range = resolve_target_peak_ctl("Marathon")
        self.assertTrue(ctl_target >= 50.0)
        self.assertEqual(get_target_peak_ctl("Marathon"), ctl_target)

        traj = evaluate_goal_trajectory(
            {"training_goal": "Sub-3:30 Marathon", "timeline": "2026-11-01"},
            current_ctl=50.0,
            today_date=date(2026, 8, 25)
        )
        self.assertEqual(traj["goal_name"], "Sub-3:30 Marathon")
        self.assertIsNotNone(traj["weeks_remaining"])
        self.assertIsNotNone(traj["required_ramp_rate"])

    def test_visualization_helpers(self):
        fitness = {"ctl_end": 60.0, "atl_end": 55.0, "tsb_end": 5.0}
        traj = {"target_peak_ctl": 80.0, "reference_range": [75.0, 90.0], "required_ramp_rate": 3.2, "weeks_remaining": 8}
        table = generate_visual_progress_table(fitness, traj)
        self.assertIn("CTL (Fitness)", table)
        self.assertIn("80.0", table)
        self.assertIn("█", table)

    def test_status_summary_helpers(self):
        past_workouts = [{"sport": "Run", "id": "1", "title": "Easy Run", "date": "2026-08-24", "distance_actual_km": 8.0, "tss_actual": 45}]
        future_workouts = [{"sport": "Run", "id": "2", "title": "Long Run", "date": "2026-08-30", "distance_planned_km": 20.0, "tss_planned": 110}]
        metrics = {"sleep": [7.5, 8.0], "hrv": [60, 65], "rhr": [48, 47]}
        fitness = {"ctl_end": 50.0, "atl_end": 45.0, "tsb_end": 5.0, "trajectory_info": {"target_peak_ctl": 70.0}}

        completed_str = format_completed_workouts(past_workouts)
        self.assertIn("Easy Run", completed_str)
        self.assertIn("8.0km", completed_str)

        planned_str = format_planned_workouts(future_workouts)
        self.assertIn("Long Run", planned_str)
        self.assertIn("20.0km", planned_str)

        rec_str = format_recovery_metrics(metrics)
        self.assertIn("Sleep:", rec_str)
        self.assertIn("HRV Trend:", rec_str)

        cal_notes = format_calendar_notes([{"date": "2026-08-25", "title": "Travel to NYC", "description": "Flight at 10am"}])
        self.assertIn("Travel to NYC", cal_notes)

        checkin = compile_checkin_summary(
            lookback_days=14,
            lookahead_days=7,
            workouts_past=past_workouts,
            workouts_future=future_workouts,
            metrics_data=metrics,
            fitness_data=fitness,
            notes_list=[]
        )
        self.assertIn("Weekly Check-In Training & Physiological Report", checkin)

        audit = format_schedule_audit_summary([{
            "date_range": "Aug 25 - Aug 31",
            "total_distance_km": 50.0,
            "total_tss": 320.0,
            "easy_count": 3,
            "quality_count": 2,
            "sessions": ["Run 10k", "Run 15k"]
        }])
        self.assertIn("Training Schedule Audit", audit)

        nutrition = format_nutrition_context_summary(
            profile={"weight": "70kg", "age": "30", "training_goal": "Marathon", "timeline": "2026-11-01"},
            upcoming_workouts=future_workouts,
            weather_forecast="22°C Clear"
        )
        self.assertIn("Athlete Nutrition & Fueling Context", nutrition)


if __name__ == "__main__":
    unittest.main()
