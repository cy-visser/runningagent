from datetime import date

import pytest

from running_coach.utils.race_prediction import (
    MAX_DETRAINING_PENALTY,
    ctl_on,
    detraining_factor,
    format_seconds_hms,
    riegel_predict,
)

MARATHON_KM = 42.195
HALF_KM = 21.0975


class TestRiegelPredict:
    def test_half_to_marathon(self):
        # 1:40:00 half -> ~3:28:30 marathon
        assert riegel_predict(6000, HALF_KM, MARATHON_KM) == pytest.approx(12511, abs=5)

    def test_10k_to_5k(self):
        # 45:00 10K -> ~21:35 5K
        assert riegel_predict(2700, 10.0, 5.0) == pytest.approx(1295, abs=3)


class TestFormatSecondsHms:
    @pytest.mark.parametrize("seconds, expected", [
        (1352, "22:32"), (12510, "3:28:30"), (3600, "1:00:00"), (59.6, "1:00"), (None, "-"),
    ])
    def test_formats(self, seconds, expected):
        assert format_seconds_hms(seconds) == expected


class TestCtlOn:
    PMC = [{"date": "2026-09-01", "ctl": 50.0}, {"date": "2026-09-10", "ctl": 60.0}]

    def test_exact_and_nearest_before(self):
        assert ctl_on(self.PMC, date(2026, 9, 10)) == 60.0
        assert ctl_on(self.PMC, date(2026, 9, 5)) == 50.0

    def test_before_history_or_missing(self):
        assert ctl_on(self.PMC, date(2026, 8, 1)) is None
        assert ctl_on(None, date(2026, 9, 1)) is None
        assert ctl_on(self.PMC, None) is None


class TestDetrainingFactor:
    def test_no_penalty_when_fitter_or_equal(self):
        assert detraining_factor(50.0, 60.0) == 1.0
        assert detraining_factor(60.0, 60.0) == 1.0

    def test_missing_values_are_neutral(self):
        assert detraining_factor(None, 60.0) == 1.0
        assert detraining_factor(60.0, None) == 1.0

    def test_penalises_ctl_drop(self):
        assert detraining_factor(70.0, 50.0) == pytest.approx((70 / 50) ** 0.15)

    def test_capped(self):
        assert detraining_factor(100.0, 5.0) == MAX_DETRAINING_PENALTY
