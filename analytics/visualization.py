def generate_visual_progress_table(fitness_data: dict, trajectory_info: dict) -> str:
    """Generates Markdown visual progress indicators and status table."""
    ctl_end = fitness_data.get("ctl_end", 0.0)
    atl_end = fitness_data.get("atl_end", 0.0)
    tsb_end = fitness_data.get("tsb_end", 0.0)
    target_ctl = trajectory_info.get("expected_current_ctl", 70.0)
    
    pct = min(100, max(0, int((ctl_end / target_ctl) * 100))) if target_ctl > 0 else 100
    filled = pct // 10
    empty = 10 - filled
    bar = "█" * filled + "░" * empty
    
    tsb_delta = round(atl_end - ctl_end, 1)
        
    table_md = (
        f"| Metric | Current Value | Benchmark Target | Status & Visual Progress |\n"
        f"|---|---|---|---|\n"
        f"| **CTL (Fitness)** | `{ctl_end}` | Expected: `{target_ctl}` (Peak Target: `{trajectory_info.get('target_peak_ctl')}`) | `[{bar}]` **{pct}%** ({trajectory_info.get('status_label')}) |\n"
        f"| **ATL (Fatigue)** | `{atl_end}` | Baseline: `{ctl_end}` | Fatigue Delta: `{atl_end - ctl_end:+.1f}` vs CTL |\n"
        f"| **TSB (Form)** | `{tsb_end}` | Formula: `CTL - ATL` | Net Balance: `{tsb_end:+.1f}` (ATL Delta: `{tsb_delta:+.1f}`) |\n"
    )
    
    return table_md
