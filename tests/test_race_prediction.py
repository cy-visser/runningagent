
import pytest

from running_coach.utils.race_prediction import format_seconds_hms, riegel_predict

MARATHON_KM = 42.195
HALF_KM = 21.0975


def test_riegel_predict():
    # 1:40:00 half -> ~3:28:30 marathon; 45:00 10K -> ~21:35 5K
    assert riegel_predict(6000, HALF_KM, MARATHON_KM) == pytest.approx(12511, abs=5)
    assert riegel_predict(2700, 10.0, 5.0) == pytest.approx(1295, abs=3)


def test_format_seconds_hms():
    for seconds, expected in [(1352, "22:32"), (12510, "3:28:30"), (3600, "1:00:00"), (59.6, "1:00"), (None, "-")]:
        assert format_seconds_hms(seconds) == expected, seconds
