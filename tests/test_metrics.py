import json

from running_coach.utils.metrics import (
    coerce_mcp_payload,
    extract_health_metrics,
    parse_mcp_response,
)


def mcp_envelope(payload) -> dict:
    """Builds the MCP response envelope shape returned by the TrainingPeaks tools."""
    return {"content": [{"text": json.dumps(payload)}]}


def test_parse_mcp_response():
    assert parse_mcp_response(mcp_envelope({"workouts": [1, 2]})) == {"workouts": [1, 2]}
    for response in (None, {}, "a string", {"content": []}, {"content": [{"text": ""}]},
                     {"content": [{"text": "{not json"}]}):
        assert parse_mcp_response(response) is None, response


def test_coerce_mcp_payload():
    for raw, expected in [
        (mcp_envelope({"id": "abc"}), {"id": "abc"}),       # envelope preferred
        ({"id": "abc"}, {"id": "abc"}),                     # raw dict
        ('{"id": "abc"}', {"id": "abc"}),                   # JSON string
        ("workout created", {"message": "workout created"}),  # plain text
        ("[1, 2, 3]", {"message": "[1, 2, 3]"}),            # non-dict JSON
        (None, {}),
    ]:
        assert coerce_mcp_payload(raw) == expected, raw
    assert coerce_mcp_payload(None, default={"fallback": True}) == {"fallback": True}


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
