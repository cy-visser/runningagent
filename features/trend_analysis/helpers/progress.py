from statistics import mean
from typing import Callable, Optional

from ....shared.units import fmt_clock
from .weekly_rows import key_run_label

SUMMARY_WEEKS = 4                   # progress compares the first and last 4 complete weeks

# Web-report verdict badges (payload only; the LLM text shows facts, not verdicts).
VERDICT_IMPROVING = "🟢 improving"
VERDICT_STABLE = "🟡 stable"
VERDICT_DECLINING = "🔴 declining"


def _num(fmt: str) -> Callable[[float], str]:
    return fmt.format


def _pace(seconds: float) -> str:
    return f"{fmt_clock(seconds)}/km"


def _pace_change(seconds: float) -> str:
    return f"{seconds:+.0f} s/km"


def progress_markers(goal_label: Optional[str] = None) -> tuple:
    """(key, label, higher_is_better, value_fmt, change_fmt) per displayed progress marker."""
    return (
        ("ctl", "CTL (fitness)", True, _num("{:.1f}"), _num("{:+.1f}")),
        ("km", "Weekly running km", True, _num("{:.0f}"), _num("{:+.0f}")),
        ("lt1_pace_s", "Pace @ LT1 (top of zone 2)", False, _pace, _pace_change),
        ("lt2_pace_s", "Pace @ LT2 (LTHR)", False, _pace, _pace_change),
        ("key_decoupling", f"Key-run Pa:Hr % ({key_run_label(goal_label)})", False,
         _num("{:.1f}"), _num("{:+.1f}")),
        ("hrv", "HRV (ms)", True, _num("{:.0f}"), _num("{:+.0f}")),
        ("rhr", "Resting HR (bpm)", False, _num("{:.0f}"), _num("{:+.0f}")),
        ("sleep_h", "Sleep (h)", True, _num("{:.1f}"), _num("{:+.1f}")),
    )


def progress_summary(rows: list[dict], goal_label: Optional[str] = None) -> list[dict]:
    """Per marker: mean of the first and last 4 complete weeks, best week, change and direction.

    `arrow` is the direction of the number; `verdict` judges the runner (e.g. a rising Pa:Hr or
    a slower LT pace is 🔴 declining even though the number went up). Both are web-payload only.
    """
    complete = [r for r in rows if r["complete"]]
    out = []
    for key, label, higher, fmt, change_fmt in progress_markers(goal_label):
        values = [(r["week"], r[key]) for r in complete if r.get(key) is not None]
        if len(values) < 2:
            continue
        n = min(SUMMARY_WEEKS, max(1, len(values) // 2))
        first, latest = mean(v for _, v in values[:n]), mean(v for _, v in values[-n:])
        best = (max if higher else min)(values, key=lambda x: x[1])
        change = latest - first
        arrow = "→" if abs(change) < 1e-9 or (first and abs(change / first) < 0.01) else ("↑" if change > 0 else "↓")
        improving = change > 0 if higher else change < 0
        verdict = VERDICT_STABLE if arrow == "→" else (VERDICT_IMPROVING if improving else VERDICT_DECLINING)
        out.append({"key": key, "label": label, "first": fmt(first), "latest": fmt(latest),
                    "best": f"{fmt(best[1])} (wk {best[0].isoformat()})", "change": change_fmt(change),
                    "higher_is_better": higher, "arrow": arrow, "verdict": verdict})
    return out


def format_progress_table(progress: list[dict]) -> str:
    if not progress:
        return ""
    lines = ["**Progress** (mean of the first vs last complete weeks, up to 4 each):", "",
             "| Marker | First | Latest | Best | Change | Higher is better |", "|---|---|---|---|---|---|"]
    lines += [f"| {p['label']} | {p['first']} | {p['latest']} | {p['best']} | {p['change']} "
              f"| {'yes' if p['higher_is_better'] else 'no'} |"
              for p in progress]
    return "\n".join(lines)
