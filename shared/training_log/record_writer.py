"""Single write path for saving a workout's training-log record to Firestore."""

import asyncio
import logging
from datetime import datetime
from typing import Optional

from ...integrations import firestore
from ..dates import parse_date
from ..runner_identity import profile_user_id
from ..runner_weather import weather_at
from ..sports import RUN_SPORTS
from .record_builder import WorkoutBundle, build_training_record, workout_context

logger = logging.getLogger(__name__)


async def record_workout(
    profile: dict, meta: dict, analysis: Optional[dict], series: Optional[list[dict]], *,
    thresholds: dict, daily_pmc: Optional[list[dict]], dated_metrics: Optional[dict], start: Optional[str],
    start_position: Optional[dict] = None, start_is_utc: bool = False,
) -> Optional[dict]:
    """Builds and saves the training-log record for one workout. Best effort: never raises.

    The single write path for the training log; analyze_workout and gap-fill both call it.
    """
    try:
        user_id = profile_user_id(profile)
        if not user_id or not meta:
            return None
        weather = None
        if start and str(meta.get("sport") or "").lower() in RUN_SPORTS:
            weather = await asyncio.to_thread(
                weather_at, profile, start, position=start_position, utc=start_is_utc,
            )
        bundle = WorkoutBundle(
            meta=meta, analysis=analysis, series=series, thresholds=thresholds, weather=weather,
            context=workout_context(parse_date(meta.get("date")), daily_pmc, dated_metrics),
            start_position=start_position,
        )
        record = build_training_record(bundle, datetime.now())
        if record:
            await firestore.save_training_record(user_id, record["workout_id"], record)
        return record
    except Exception as e:
        logger.warning("Training-log record failed for workout %s: %s", (meta or {}).get("id"), e)
        return None
