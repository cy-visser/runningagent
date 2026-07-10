#!/usr/bin/env python3
"""
fetch_token_metrics.py — Standalone Cloud Telemetry Analytics Script

This script queries Google Cloud Monitoring and Google Cloud Logging to analyze
LLM token consumption for the AI Running Coach when the agent starts and for
every subsequent user prompt.

Usage Examples:
  # 1. Macro time-series view across all models (Monitoring mode)
  python3 fetch_token_metrics.py --mode monitoring --hours 24

  # 2. Micro turn-by-turn breakdown for the most recent session (Logging mode)
  python3 fetch_token_metrics.py --mode logging

  # 3. Micro turn-by-turn breakdown for a specific session ID
  python3 fetch_token_metrics.py --mode logging --session-id cli-session-12345678
"""

import argparse
from datetime import datetime, timedelta, timezone
import json
import sys
from typing import Any, Dict, List, Optional, Tuple

try:
    from google.cloud import monitoring_v3
    from google.cloud import logging as cloud_logging
    from google.protobuf import timestamp_pb2
    from google.api_core.exceptions import GoogleAPICallError
except ImportError:
    print("Error: Required Google Cloud SDK libraries are not installed in this environment.")
    print("Since this is a standalone script, please install them locally:")
    print("  pip install google-cloud-monitoring google-cloud-logging")
    sys.exit(1)


DEFAULT_PROJECT = "firestore-cyvisser"


def format_number(n: int) -> str:
    """Formats an integer with comma separators."""
    return f"{n:,}"


def run_monitoring_mode(project_id: str, hours: int):
    """Queries Cloud Monitoring for Vertex AI prediction token count metrics."""
    print(f"\n📊 Querying Google Cloud Monitoring for project '{project_id}' (Past {hours} hours)...")
    client = monitoring_v3.MetricServiceClient()
    project_name = f"projects/{project_id}"
    
    now = datetime.now(timezone.utc)
    start_time = now - timedelta(hours=hours)
    
    interval = monitoring_v3.TimeInterval(
        end_time={"seconds": int(now.timestamp())},
        start_time={"seconds": int(start_time.timestamp())}
    )
    
    filter_str = 'metric.type = "aiplatform.googleapis.com/prediction/token_count"'
    
    try:
        results = client.list_time_series(
            request={
                "name": project_name,
                "filter": filter_str,
                "interval": interval,
                "view": monitoring_v3.ListTimeSeriesRequest.TimeSeriesView.FULL,
            }
        )
    except GoogleAPICallError as e:
        if "not_found" in str(e).lower() or "cannot find metric" in str(e).lower() or getattr(e, "code", None) == 404:
            print("No token count metrics found in Cloud Monitoring for this time window.")
            print("Tip: This metric is created automatically once prediction requests are logged to Cloud Monitoring.")
            return
        print(f"Error querying Cloud Monitoring API: {e}")
        return
    except Exception as e:
        print(f"Unexpected error in monitoring mode: {e}")
        return

    # Aggregate by model_id and token/response type
    model_stats: Dict[str, Dict[str, int]] = {}
    total_series_found = 0
    
    for ts in results:
        total_series_found += 1
        labels = ts.metric.labels
        model_id = labels.get("model_id") or labels.get("model_name") or "unknown_model"
        
        # In Vertex AI, token counts are distinguished by labels like 'token_type' or 'response_type'
        token_type = labels.get("token_type") or labels.get("response_type") or "total"
        
        if model_id not in model_stats:
            model_stats[model_id] = {"prompt": 0, "cached": 0, "candidates": 0, "total": 0}
            
        series_sum = sum(p.value.int64_value or int(p.value.double_value) for p in ts.points)
        
        token_type_lower = token_type.lower()
        if "prompt" in token_type_lower or "input" in token_type_lower:
            model_stats[model_id]["prompt"] += series_sum
        elif "cache" in token_type_lower:
            model_stats[model_id]["cached"] += series_sum
        elif "candidate" in token_type_lower or "output" in token_type_lower:
            model_stats[model_id]["candidates"] += series_sum
        else:
            model_stats[model_id]["total"] += series_sum

    if total_series_found == 0:
        print(f"No token count time series found in the past {hours} hours.")
        print("Tip: Ensure the agent has been executed recently and telemetry is exported to Cloud Monitoring.")
        return

    # Print Macro View Dashboard
    print("\n┌─── 📊 Vertex AI Token Consumption ───────────────────────────────────────────────────┐")
    print(f"│ {'Model ID':<25} │ {'Input (New)':>12} │ {'Input (Cached)':>14} │ {'Output':>10} │ {'Total':>12} │")
    print("├───────────────────────────┼──────────────┼────────────────┼────────────┼──────────────┤")
    
    tot_prompt = 0
    tot_cached = 0
    tot_candidates = 0
    tot_all = 0
    
    for model_id, stats in sorted(model_stats.items()):
        # Calculate row total if not explicitly provided by a total series
        row_tot = stats["total"] if stats["total"] > 0 else (stats["prompt"] + stats["cached"] + stats["candidates"])
        print(f"│ {model_id:<25} │ {format_number(stats['prompt']):>12} │ {format_number(stats['cached']):>14} │ {format_number(stats['candidates']):>10} │ {format_number(row_tot):>12} │")
        tot_prompt += stats["prompt"]
        tot_cached += stats["cached"]
        tot_candidates += stats["candidates"]
        tot_all += row_tot
        
    print("├───────────────────────────┼──────────────┼────────────────┼────────────┼──────────────┤")
    print(f"│ {'TOTALS':<25} │ {format_number(tot_prompt):>12} │ {format_number(tot_cached):>14} │ {format_number(tot_candidates):>10} │ {format_number(tot_all):>12} │")
    print("└───────────────────────────┴──────────────┴────────────────┴────────────┴──────────────┘")
    
    total_input = tot_prompt + tot_cached
    if total_input > 0:
        eff = (tot_cached / total_input) * 100
        print(f"💡 Cache Efficiency: {eff:.1f}% of all input tokens served from Vertex AI Context Cache!")


def extract_token_data_from_payload(payload: Any) -> List[Dict[str, Any]]:
    """Recursively searches a log payload for usage_metadata or token count dictionaries."""
    found_usages = []
    
    if isinstance(payload, dict):
        # Check if this dict itself is usage_metadata
        if any(k in payload for k in ["promptTokenCount", "prompt_token_count", "candidatesTokenCount", "candidates_token_count"]):
            prompt = payload.get("promptTokenCount") or payload.get("prompt_token_count") or 0
            candidates = payload.get("candidatesTokenCount") or payload.get("candidates_token_count") or 0
            cached = payload.get("cachedContentTokenCount") or payload.get("cached_content_token_count") or 0
            total = payload.get("totalTokenCount") or payload.get("total_token_count") or (prompt + candidates)
            found_usages.append({
                "prompt_tokens": int(prompt),
                "candidates_tokens": int(candidates),
                "cached_tokens": int(cached),
                "total_tokens": int(total),
            })
            return found_usages

        # Otherwise search nested keys
        for key, value in payload.items():
            if key in ["usage_metadata", "usageMetadata", "usage"]:
                found_usages.extend(extract_token_data_from_payload(value))
            elif isinstance(value, (dict, list)):
                found_usages.extend(extract_token_data_from_payload(value))
                
    elif isinstance(payload, list):
        for item in payload:
            found_usages.extend(extract_token_data_from_payload(item))
            
    elif isinstance(payload, str):
        # Attempt to parse JSON strings embedded in logs
        if "TokenCount" in payload or "token_count" in payload:
            try:
                parsed = json.loads(payload)
                found_usages.extend(extract_token_data_from_payload(parsed))
            except Exception:
                pass
                
    return found_usages


def run_logging_mode(project_id: str, hours: int, target_session_id: Optional[str]):
    """Queries Cloud Logging for turn-by-turn session token usage."""
    print(f"\n🔍 Querying Google Cloud Logging for project '{project_id}'...")
    client = cloud_logging.Client(project=project_id)
    
    now = datetime.now(timezone.utc)
    start_time = now - timedelta(hours=hours)
    time_filter = f'timestamp >= "{start_time.strftime("%Y-%m-%dT%H:%M:%SZ")}"'
    
    if target_session_id:
        print(f"Filtering strictly for session ID: {target_session_id}")
        filter_str = f'{time_filter} AND "{target_session_id}"'
    else:
        print(f"No session ID provided. Searching recent logs for usage metadata (Past {hours} hours)...")
        filter_str = f'{time_filter} AND (usage_metadata OR usageMetadata OR promptTokenCount OR prompt_token_count)'

    try:
        entries = list(client.list_entries(filter_=filter_str, order_by=cloud_logging.DESCENDING, page_size=200))
    except GoogleAPICallError as e:
        print(f"Error querying Cloud Logging API: {e}")
        return
    except Exception as e:
        print(f"Unexpected error in logging mode: {e}")
        return

    if not entries:
        print("No matching log entries found with token usage metadata.")
        print("Tip: Ensure the agent was run with OpenTelemetry Cloud export enabled (--otel_to_cloud).")
        return

    # Group extracted turns by session_id
    sessions: Dict[str, List[Tuple[datetime, Dict[str, Any]]]] = {}
    
    for entry in entries:
        payload = entry.payload
        if not payload:
            continue
            
        # Try to identify session_id from log payload or labels
        session_id = target_session_id
        if not session_id:
            if isinstance(payload, dict):
                session_id = payload.get("session_id") or payload.get("sessionId") or payload.get("invocation_id") or payload.get("invocationId")
            if not session_id and entry.labels:
                session_id = entry.labels.get("session_id") or entry.labels.get("invocation_id")
            if not session_id:
                session_id = "default_session"

        usages = extract_token_data_from_payload(payload)
        for u in usages:
            if session_id not in sessions:
                sessions[session_id] = []
            sessions[session_id].append((entry.timestamp or now, u))

    if not sessions:
        print("Found logs, but could not extract structured usage_metadata.")
        return

    # If no target_session_id was specified, pick the session with the most recent timestamp
    if not target_session_id:
        target_session_id = max(sessions.keys(), key=lambda s: max(t[0] for t in sessions[s]))
        print(f"Selected most recent active session: {target_session_id}")

    turns = sessions.get(target_session_id, [])
    if not turns:
        print(f"No token usage turns found for session '{target_session_id}'.")
        return

    # Sort chronologically (oldest to newest) to distinguish Turn 1 (Agent Start) from subsequent prompts
    turns.sort(key=lambda x: x[0])

    print(f"\n┌─── 🔍 Turn-by-Turn Token Breakdown (Session: {target_session_id}) ──────────────────────────────────────┐")
    print(f"│ {'Turn':<5} │ {'Phase':<16} │ {'Input (New)':>12} │ {'Cached':>10} │ {'Output':>8} │ {'Total':>10} │ {'Hit Rate':>10} │")
    print("├───────┼──────────────────┼──────────────┼────────────┼──────────┼────────────┼────────────┤")

    sum_prompt = 0
    sum_cached = 0
    sum_candidates = 0
    sum_total = 0

    for idx, (timestamp, u) in enumerate(turns, start=1):
        prompt = u["prompt_tokens"]
        cached = u["cached_tokens"]
        candidates = u["candidates_tokens"]
        total = u["total_tokens"]
        
        # Turn 1 is the Agent Start (Onboarding/Coaching Init)
        phase = "Agent Start" if idx == 1 else f"Prompt #{idx}"
        
        # Calculate cache hit rate for this turn
        turn_input = prompt + cached
        hit_rate_str = f"{(cached / turn_input) * 100:.1f}%" if turn_input > 0 else "0.0%"
        
        print(f"│ {idx:<5} │ {phase:<16} │ {format_number(prompt):>12} │ {format_number(cached):>10} │ {format_number(candidates):>8} │ {format_number(total):>10} │ {hit_rate_str:>10} │")
        
        sum_prompt += prompt
        sum_cached += cached
        sum_candidates += candidates
        sum_total += total

    print("├───────┼──────────────────┼──────────────┼────────────┼──────────┼────────────┼────────────┤")
    tot_input = sum_prompt + sum_cached
    overall_hit = f"{(sum_cached / tot_input) * 100:.1f}%" if tot_input > 0 else "0.0%"
    print(f"│ {'SUM':<5} │ {f'{len(turns)} Turns':<16} │ {format_number(sum_prompt):>12} │ {format_number(sum_cached):>10} │ {format_number(sum_candidates):>8} │ {format_number(sum_total):>10} │ {overall_hit:>10} │")
    print("└───────┴──────────────────┴──────────────┴────────────┴──────────┴────────────┴────────────┘")


def main():
    parser = argparse.ArgumentParser(description="Analyze AI Running Coach LLM token consumption in GCP.")
    parser.add_argument("--mode", choices=["monitoring", "logging", "both"], default="both",
                        help="Telemetry source: 'monitoring' (macro time-series), 'logging' (micro turn-by-turn), or 'both'.")
    parser.add_argument("--project", default=DEFAULT_PROJECT, help=f"GCP Project ID (default: {DEFAULT_PROJECT})")
    parser.add_argument("--hours", type=int, default=24, help="Time window in hours to search (default: 24)")
    parser.add_argument("--session-id", dest="session_id", default=None,
                        help="Specific session ID to drill down into (for logging mode). If omitted, picks the latest session.")

    args = parser.parse_args()

    if args.mode in ["monitoring", "both"]:
        run_monitoring_mode(args.project, args.hours)

    if args.mode in ["logging", "both"]:
        run_logging_mode(args.project, args.hours, args.session_id)


if __name__ == "__main__":
    main()
