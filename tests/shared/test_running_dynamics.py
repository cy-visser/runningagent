"""Unit tests for shared running dynamics extraction, late-run drift, and pace-normalized form trends."""

from datetime import date, timedelta

from running_coach.shared.running_dynamics import (
    DYNAMICS_SCHEMA_VERSION,
    compute_late_run_drift,
    derive_vert_ratio,
    dynamics_by_band,
    extract_lap_dynamics,
    extract_session_dynamics,
    form_at_speed,
    has_running_dynamics,
    late_fade_summary,
    normalize_balance,
    normalize_cadence,
    normalize_stride,
    normalize_vert_osc,
    reference_easy_speed,
)
from running_coach.shared.workout_structure import Alignment, ExecutedStep, PlannedStep


def test_unit_normalization_and_derived_vertical_ratio():
    # Single-foot half-cadence doubles when running; walks excluded.
    assert normalize_cadence(88.0, speed_kph=11.0) == 176.0
    assert normalize_cadence(174.0, speed_kph=11.0) == 174.0
    assert normalize_cadence(95.0, speed_kph=4.0) is None
    assert normalize_cadence(0.0, speed_kph=11.0) is None

    # StepLength mm -> m; VerticalOscillation mm -> cm (lapData) vs cm (series).
    assert normalize_stride(1120.0) == 1.12
    assert normalize_stride(1.12) == 1.12
    assert normalize_vert_osc(94.0) == 9.4
    assert normalize_vert_osc(9.4) == 9.4

    # Derived Vertical Ratio avoids TP integer rounding (9.4 cm / 1.12 m = 8.39%, not 8%).
    assert derive_vert_ratio(9.4, 1.12, fallback=8.0) == 8.39
    assert derive_vert_ratio(None, None, fallback=8.0) == 8.0

    # Zero / out-of-range balance ignored (sensor without L/R balance).
    assert normalize_balance(0.0) is None
    assert normalize_balance(50.3) == 50.3


def test_zero_contaminated_stops_and_channels_filtered():
    # 1-Hz series with traffic-light stops (0.0 GCT / 0 speed) + running samples.
    series = [
        {"time": t, "Speed": 0.0, "Cadence": 0.0, "StanceTime": 0.0, "StepLength": 0.0, "VerticalOscillation": 0.0}
        for t in range(0, 60)
    ] + [
        {
            "time": t,
            "Speed": 11.5,
            "Cadence": 172.0,
            "StanceTime": 262.0,
            "StepLength": 1110.0,
            "VerticalOscillation": 9.8,
            "VerticalRatio": 9.0,  # TP integer-rounded
            "GroundContactTimeBalance": 0.0,
        }
        for t in range(60, 180)
    ]
    dyn = extract_session_dynamics(series, raw_laps=[], data_channels=[])
    assert has_running_dynamics(dyn)
    assert dyn["cadence"] == 172.0
    assert dyn["gct_ms"] == 262.0
    assert dyn["stride_m"] == 1.11
    assert dyn["vert_osc_cm"] == 9.8
    assert dyn["vert_ratio_pct"] == 8.83  # derived 9.8 / 1.11
    assert "gct_balance" not in dyn

    # Fallback dataChannels must reject zero-contaminated channels (min == 0).
    channels = [
        {"identifier": "StanceTime", "average": 233.0, "min": 0.0},
        {"identifier": "StepLength", "average": 980.0, "min": 0.0},
    ]
    assert extract_session_dynamics([], [], channels) is None

    # Clean lapData with mm VerticalOscillation and walk lap excluded.
    walk_lap = {"TotalTimerTime": 120, "AverageSpeed": 1.1, "AverageCadence": 100, "AverageStanceTime": 420}
    run_lap = {
        "TotalTimerTime": 330,
        "AverageSpeed": 3.05,
        "AverageCadence": 170,
        "AverageStanceTime": 265,
        "AverageStepLength": 1080,
        "AverageVerticalOscillation": 96.0,
        "AverageVerticalRatio": 9,
    }
    assert extract_lap_dynamics(walk_lap) == {}
    lap_dyn = extract_lap_dynamics(run_lap)
    assert lap_dyn["vert_osc_cm"] == 9.6
    assert lap_dyn["stride_m"] == 1.08
    assert lap_dyn["vert_ratio_pct"] == 8.89


def _make_series(duration_s: int, fn) -> list[dict]:
    return [{"time": float(t), **fn(t)} for t in range(0, duration_s, 5)]


def test_late_run_drift_detects_fatigue_and_guards_progressive_pickups():
    # 1. Steady run where form holds -> fatigue_flag False.
    steady = _make_series(3000, lambda t: {
        "Speed": 11.5, "Cadence": 174.0, "StanceTime": 252.0 + (2.0 if t > 2000 else 0.0),
        "StepLength": 1100.0, "VerticalOscillation": 9.3,
    })
    d_steady = compute_late_run_drift(steady, [])
    assert d_steady is not None and d_steady["fatigue_flag"] is False

    # 2. Steady pace with clear stiffness breakdown (GCT +18 ms, VR +1.0 pp) -> fatigue_flag True.
    faded = _make_series(3000, lambda t: {
        "Speed": 11.4 if t < 1800 else 11.2,
        "Cadence": 174.0 if t < 1800 else 168.0,
        "StanceTime": 250.0 if t < 1800 else 268.0,
        "StepLength": 1100.0 if t < 1800 else 1040.0,
        "VerticalOscillation": 9.2 if t < 1800 else 9.8,
    })
    d_faded = compute_late_run_drift(faded, [])
    assert d_faded is not None and d_faded["fatigue_flag"] is True
    assert d_faded["gct_delta_ms"] >= 14.0

    # 3. Progressive negative split (+10% speed late) with normal crisp mechanics -> NOT fatigue.
    pickup = _make_series(3000, lambda t: {
        "Speed": 10.8 if t < 1800 else 12.2,
        "Cadence": 170.0 if t < 1800 else 176.0,
        "StanceTime": 264.0 if t < 1800 else 242.0,
        "StepLength": 1060.0 if t < 1800 else 1155.0,
        "VerticalOscillation": 9.4 if t < 1800 else 9.6,
    })
    d_pickup = compute_late_run_drift(pickup, [])
    assert d_pickup is not None and d_pickup["speed_delta_pct"] > 4.0
    assert d_pickup["fatigue_flag"] is False

    # 4. Structured interval reps: rep 1-2 crisp, rep 4 breaks down -> rep-to-rep fade detected.
    def _rep(rep_idx: int, gct: float, sl_mm: float, vo_mm: float) -> ExecutedStep:
        step = PlannedStep(block=2, block_reps=4, rep=rep_idx, pos=0, name="1km @ T", intensity="active")
        lap = {
            "TotalTimerTime": 240.0, "TotalDistance": 1000.0, "AverageSpeed": 4.16,
            "AverageCadence": 180.0, "AverageStanceTime": gct,
            "AverageStepLength": sl_mm, "AverageVerticalOscillation": vo_mm,
        }
        return ExecutedStep(step=step, laps=[lap], start=rep_idx * 300.0, end=rep_idx * 300.0 + 240.0,
                            dur_s=240.0, dist_km=1.0, pace_s=240.0, hr_avg=168.0, hr_max=174.0,
                            power=None, cadence=180.0)

    alignment = Alignment(
        steps=[
            _rep(1, 224.0, 1380.0, 96.0),
            _rep(2, 226.0, 1375.0, 96.5),
            _rep(3, 232.0, 1350.0, 98.0),
            _rep(4, 244.0, 1300.0, 102.0),
        ],
    )
    d_reps = compute_late_run_drift([], [], alignment=alignment)
    assert d_reps is not None
    assert d_reps["scope"].startswith("reps (4x")
    assert d_reps["gct_delta_ms"] >= 14.0
    assert d_reps["fatigue_flag"] is True


def _run_record(day: date, kind: str, speed_ms: float, gct_ms: float, vo_cm: float,
                cadence: float, stride_m: float, late_drift=None) -> dict:
    vr = derive_vert_ratio(vo_cm, stride_m)
    laps = [
        {
            "duration_s": 320.0,
            "distance_km": round(speed_ms * 0.32, 3),
            "speed_ms": speed_ms,
            "cadence": cadence,
            "gct_ms": gct_ms,
            "stride_m": stride_m,
            "vert_osc_cm": vo_cm,
            "vert_ratio_pct": vr,
        }
        for _ in range(4)
    ]
    return {
        "workout_id": f"w_{day.isoformat()}_{kind}",
        "date": day.isoformat(),
        "sport": "Run",
        "title": f"{kind.title()} Run",
        "kind": kind,
        "dynamics_version": DYNAMICS_SCHEMA_VERSION,
        "laps": laps,
        "late_drift": late_drift,
    }


def test_pace_normalized_form_prevents_fake_trend_from_speed_mix_and_detects_real_improvement():
    # Curve: GCT(v) = 360 - 35 * v  (at v=3.0 -> 255 ms; at v=3.5 -> 237.5 ms).
    # Early 4 weeks run slower (v=2.9–3.1), late 4 weeks run faster (v=3.1–3.5) on the EXACT SAME curve.
    today = date(2026, 10, 27)
    same_curve_records = []
    for i, spd in enumerate([2.90, 2.95, 3.00, 3.05, 3.10]):
        d = today - timedelta(days=45 - i * 4)
        same_curve_records.append(_run_record(d, "easy", spd, 360.0 - 35.0 * spd, 9.5, 170.0, spd * 60 / 170.0))
    for i, spd in enumerate([3.05, 3.15, 3.25, 3.35, 3.45]):
        d = today - timedelta(days=20 - i * 4)
        same_curve_records.append(_run_record(d, "easy", spd, 360.0 - 35.0 * spd, 9.5, 170.0, spd * 60 / 170.0))

    ref = reference_easy_speed(same_curve_records)
    assert ref is not None
    early_form = form_at_speed(same_curve_records, today - timedelta(weeks=4), ref)
    late_form = form_at_speed(same_curve_records, today, ref)
    assert early_form and late_form
    # Despite faster average speed in late weeks, pace-normalized GCT stays identical!
    assert abs(late_form["gct_ms"] - early_form["gct_ms"]) < 0.5

    # Now add genuine biomechanical improvement (-12 ms GCT and -0.8 cm Vert Osc at the same speed).
    improved_records = list(same_curve_records[:5])
    for i, spd in enumerate([2.95, 3.00, 3.05, 3.10, 3.15]):
        d = today - timedelta(days=20 - i * 4)
        improved_records.append(_run_record(d, "easy", spd, 348.0 - 35.0 * spd, 8.7, 173.0, spd * 60 / 173.0))

    ref2 = reference_easy_speed(improved_records)
    f_early = form_at_speed(improved_records, today - timedelta(weeks=4), ref2)
    f_late = form_at_speed(improved_records, today, ref2)
    assert f_early and f_late
    assert (f_late["gct_ms"] - f_early["gct_ms"]) <= -10.0
    assert (f_late["vert_ratio_pct"] - f_early["vert_ratio_pct"]) <= -0.5


def test_dynamics_by_band_exact_speed_modulation_and_late_fade_summary():
    today = date(2026, 10, 27)
    thresh = 4.0  # 4:10/km
    # Easy @ 3.00 m/s (cad 170, stride 1.059 m), Threshold @ 3.90 m/s (cad 180, stride 1.300 m).
    records = [
        _run_record(today - timedelta(days=10), "easy", 3.00, 260.0, 9.6, 170.0, 1.059,
                    late_drift={"scope": "session", "gct_delta_ms": 2.0, "vr_delta_pp": 0.1, "fatigue_flag": False}),
        _run_record(today - timedelta(days=6), "quality", 3.90, 224.0, 9.8, 180.0, 1.300,
                    late_drift={"scope": "reps (4x 1km)", "gct_delta_ms": 15.0, "vr_delta_pp": 0.9, "fatigue_flag": True}),
    ]
    info = dynamics_by_band(records, threshold_speed=thresh, today=today)
    assert info is not None
    assert [b["band"] for b in info["bands"]] == ["Easy", "Threshold"]
    sm = info["speed_modulation"]
    assert sm is not None
    assert sm["from_band"] == "Easy" and sm["to_band"] == "Threshold"
    # Exact log decomposition sums to ~100% (within rounding).
    assert abs((sm["cadence_share_pct"] + sm["stride_share_pct"]) - 100) <= 1
    assert sm["stride_share_pct"] > sm["cadence_share_pct"]  # ~78% stride, ~22% cadence

    fade = late_fade_summary(records, since_date=today - timedelta(days=14))
    assert fade is not None
    assert fade["checked"] == 2 and fade["faded"] == 1
    assert len(fade["flagged_runs"]) == 1
    assert fade["flagged_runs"][0]["gct_delta_ms"] == 15.0
