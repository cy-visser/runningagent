def generate_visual_progress_table(fitness_data: dict, trajectory_info: dict) -> str:
    """Generates Markdown visual progress indicators and status table."""
    ctl_end = round(fitness_data.get("ctl_end", 0.0), 1)
    atl_end = round(fitness_data.get("atl_end", 0.0), 1)
    tsb_end = round(fitness_data.get("tsb_end", 0.0), 1)
    target_peak = trajectory_info.get("target_peak_ctl", 70.0)
    ref_range = trajectory_info.get("reference_range", [55.0, 70.0])
    req_ramp = trajectory_info.get("required_ramp_rate")
    weeks_rem = trajectory_info.get("weeks_remaining")
    
    pct = min(100, max(0, int((ctl_end / target_peak) * 100))) if target_peak > 0 else 100
    filled = pct // 10
    empty = 10 - filled
    bar = "█" * filled + "░" * empty
    
    tsb_delta = round(atl_end - ctl_end, 1)
    ramp_str = f" | Req. Ramp: `+{req_ramp} pts/wk`" if req_ramp is not None else ""
    weeks_str = f" ({weeks_rem}w out)" if weeks_rem is not None else ""
    range_str = f" (Range: `{ref_range[0]}-{ref_range[1]}`)" if ref_range and len(ref_range) == 2 else ""
        
    table_md = (
        f"| Metric | Current Value | Target / Reference | Progress & Trajectory |\n"
        f"|---|---|---|---|\n"
        f"| **CTL (Fitness)** | `{ctl_end}` | Target: `{target_peak}`{range_str}{weeks_str} | `[{bar}]` **{pct}%**{ramp_str} |\n"
        f"| **ATL (Fatigue)** | `{atl_end}` | Baseline: `{ctl_end}` | Fatigue Delta: `{atl_end - ctl_end:+.1f}` vs CTL |\n"
        f"| **TSB (Form)** | `{tsb_end}` | Formula: `CTL - ATL` | Net Balance: `{tsb_end:+.1f}` (ATL Delta: `{tsb_delta:+.1f}`) |\n"
    )
    
    return table_md
