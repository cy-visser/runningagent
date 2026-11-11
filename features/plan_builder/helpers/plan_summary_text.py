"""Coded texts of the plan builder: staged / applied replies, the per-week lines for the coach, errors."""


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def staged_line(totals: dict) -> str:
    return (f"📋 {totals['weeks']}-week plan staged: {totals['sessions']} sessions ({totals['create']} new · "
            f"{totals['update']} updated · {totals['delete']} removed). Review the weeks below and press "
            "**Apply to TrainingPeaks**.")


def staged_reply(message: str, totals: dict) -> str:
    text = (message or "").strip()
    line = staged_line(totals)
    return f"{text}\n\n{line}" if text else line


def week_line(week: dict) -> str:
    """'W7 2027-01-11 build 58 km TSS 410: 6 sessions (5 new, 1 updated)' (+ bike / strength / removed)."""
    c = week["counts"]
    parts = [f"{c['create']} new"] if c["create"] else []
    parts += [f"{c[k]} {label}" for k, label in (("update", "updated"), ("keep", "kept"), ("delete", "removed")) if c[k]]
    extras = []
    if week["bike_minutes"]:
        extras.append(f"bike {week['bike_minutes']}'")
    if week["strength_sessions"]:
        extras.append(f"strength {week['strength_sessions']}x")
    if week.get("skipped"):
        extras.append(f"{week['skipped']} past/before-start skipped")
    head = f"W{week['week']} {week['start']} {week['phase'] or '-'} {week['run_km']:g} km TSS {week['tss']}"
    tail = f": {_plural(week['sessions'], 'session')}" + (f" ({', '.join(parts)})" if parts else "")
    return head + tail + (f" · {' · '.join(extras)}" if extras else "")


ERRORS_MESSAGE = (
    "Nothing was staged: fix every listed code (session-code language in the plan-builder skill) and call "
    "stage_training_plan again with the full plan (or only the fixed weeks with base_staged_id). Do not ask the "
    "runner."
)


def give_up_text(errors: list[dict]) -> str:
    lines = ["⚠️ **Nothing was staged:** I could not build these sessions of the plan:"]
    lines += [f"- Week {e.get('week') or '?'} {e.get('day') or ''} `{e.get('code') or ''}`: {e.get('why')}"
              for e in errors[:8]]
    if len(errors) > 8:
        lines.append(f"- … and {len(errors) - 8} more")
    lines += ["", "Ask me again and I will rebuild the plan."]
    return "\n".join(lines)


CALENDAR_UNAVAILABLE_TEXT = (
    "⚠️ **Nothing was staged:** I could not read your TrainingPeaks calendar to compare the plan with it. "
    "Please try again in a moment."
)
NOTHING_STAGED_TEXT = "There is no staged training plan to apply. Ask me to build the plan first."
REPLACED_TEXT = "This plan was replaced by a newer one. Use **Apply to TrainingPeaks** on the latest plan."


def week_not_found_text(week: int) -> str:
    return f"⚠️ Week {week} is not part of the staged plan."


def week_failed_text(week: int, errors: list[str]) -> str:
    detail = "; ".join(errors[:3]) + (" …" if len(errors) > 3 else "")
    return f"⚠️ **Week {week} was not fully saved** ({detail}). Press **Resume** to retry it."


def applied_text(applied: dict, staged: dict) -> str:
    """'✅ **TrainingPeaks updated:** 24 weeks · 148 sessions (120 created, 18 updated, 10 removed).' + failures."""
    done = set(applied["weeks_done"])
    sessions = sum(w["sessions"] for w in staged["weeks"] if w["week"] in done)
    text = (f"✅ **TrainingPeaks updated:** {_plural(len(done), 'week')} · {_plural(sessions, 'session')} "
            f"({applied['created']} created, {applied['updated']} updated, {applied['deleted']} removed).")
    if applied["failed_weeks"]:
        weeks = ", ".join(str(w) for w in applied["failed_weeks"])
        text += (f"\n\n⚠️ Not saved: {_plural(applied['failed'], 'session')} in week(s) {weeks}. "
                 "Press **Resume** to retry them.")
    return text
