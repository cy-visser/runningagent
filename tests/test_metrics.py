import json

import pytest

from running_coach.utils.metrics import (
    coerce_mcp_payload,
    extract_health_metrics,
    parse_mcp_response,
)


def mcp_envelope(payload) -> dict:
    """Builds the MCP response envelope shape returned by the TrainingPeaks tools."""
    return {"content": [{"text": json.dumps(payload)}]}


class TestParseMcpResponse:
    def test_extracts_json_payload(self):
        assert parse_mcp_response(mcp_envelope({"workouts": [1, 2]})) == {"workouts": [1, 2]}

    @pytest.mark.parametrize(
        "response",
        [None, {}, "a string", {"content": []}, {"content": [{"text": ""}]}],
    )
    def test_returns_none_for_unusable_input(self, response):
        assert parse_mcp_response(response) is None

    def test_returns_none_on_malformed_json(self):
        assert parse_mcp_response({"content": [{"text": "{not json"}]}) is None


class TestCoerceMcpPayload:
    def test_prefers_the_mcp_envelope(self):
        assert coerce_mcp_payload(mcp_envelope({"id": "abc"})) == {"id": "abc"}

    def test_falls_back_to_a_raw_dict(self):
        assert coerce_mcp_payload({"id": "abc"}) == {"id": "abc"}

    def test_falls_back_to_a_json_string(self):
        assert coerce_mcp_payload('{"id": "abc"}') == {"id": "abc"}

    def test_wraps_plain_text_as_a_message(self):
        assert coerce_mcp_payload("workout created") == {"message": "workout created"}

    def test_wraps_non_dict_json_as_a_message(self):
        assert coerce_mcp_payload("[1, 2, 3]") == {"message": "[1, 2, 3]"}

    def test_returns_empty_dict_for_unusable_input(self):
        assert coerce_mcp_payload(None) == {}

    def test_honours_the_supplied_default(self):
        assert coerce_mcp_payload(None, default={"fallback": True}) == {"fallback": True}

    def test_surfaces_error_envelopes(self):
        payload = coerce_mcp_payload(mcp_envelope({"isError": True, "message": "boom"}))
        assert payload["isError"] is True
        assert payload["message"] == "boom"


class TestExtractHealthMetrics:
    def test_buckets_values_by_metric_type(self):
        raw = mcp_envelope({
            "metrics": [
                {"details": [
                    {"type": 6, "value": 7.5},    # sleep
                    {"type": 60, "value": 48},    # hrv
                    {"type": 5, "value": 52},     # rhr
                ]},
                {"details": [{"type": 6, "value": 8.0}]},
            ]
        })
        assert extract_health_metrics(raw) == {"sleep": [7.5, 8.0], "hrv": [48], "rhr": [52]}

    def test_skips_null_values_and_unknown_types(self):
        raw = mcp_envelope({
            "metrics": [{"details": [
                {"type": 6, "value": None},
                {"type": 999, "value": 1},
            ]}]
        })
        assert extract_health_metrics(raw) == {"sleep": [], "hrv": [], "rhr": []}

    def test_returns_empty_buckets_for_missing_data(self):
        assert extract_health_metrics(None) == {"sleep": [], "hrv": [], "rhr": []}
