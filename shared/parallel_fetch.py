"""Concurrent coroutine gathering with labelled exception logging."""

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)


def result_or_none(result: Any, label: str) -> Any:
    """Unwraps a gather() result, logging and discarding exceptions."""
    if isinstance(result, Exception):
        logger.warning("Failed to fetch %s: %s", label, result)
        return None
    return result


async def gather_labeled(fetches: dict[str, Any]) -> dict[str, Any]:
    """Runs labelled coroutines concurrently; failed ones map to None (and are logged)."""
    results = await asyncio.gather(*fetches.values(), return_exceptions=True)
    return {label: result_or_none(r, label) for label, r in zip(fetches, results)}
