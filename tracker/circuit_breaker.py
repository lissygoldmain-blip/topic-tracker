"""
Circuit breaker for source adapters.

Manages the 'circuit_breakers' key inside the state dict (state.json).
All functions mutate `state` in-place. No I/O is performed here.
The poller is responsible for persisting state to disk.

Auto-recovery: disabled adapters automatically re-enable after COOLDOWN_HOURS.
This prevents permanent lockout from transient failures (GDELT rate-limits,
temporary network errors, etc.).
"""

import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

FAILURE_THRESHOLD = 5
COOLDOWN_HOURS = 6


def _entry(state: dict, topic_name: str, adapter_name: str) -> dict:
    """Return the mutable CB entry, creating it if needed."""
    cbs = state.setdefault("circuit_breakers", {})
    topic = cbs.setdefault(topic_name, {})
    return topic.setdefault(
        adapter_name,
        {"consecutive_failures": 0, "disabled": False, "disabled_at": None},
    )


def is_disabled(state: dict, topic_name: str, adapter_name: str) -> bool:
    """
    Return True if the adapter is currently disabled for this topic.
    Automatically re-enables entries whose cooldown period has elapsed.
    """
    try:
        entry = state["circuit_breakers"][topic_name][adapter_name]
    except KeyError:
        return False

    if not entry.get("disabled"):
        return False

    # Auto-recover after cooldown period
    disabled_at = entry.get("disabled_at")
    if disabled_at:
        try:
            dt = datetime.fromisoformat(disabled_at)
            elapsed_hours = (datetime.now(timezone.utc) - dt).total_seconds() / 3600
            if elapsed_hours >= COOLDOWN_HOURS:
                entry["disabled"] = False
                entry["consecutive_failures"] = 0
                entry["disabled_at"] = None
                logger.info(
                    "Circuit breaker: adapter '%s' for topic '%s' auto-recovered "
                    "after %.1fh cooldown.",
                    adapter_name,
                    topic_name,
                    elapsed_hours,
                )
                return False
        except (ValueError, TypeError):
            pass

    return True


def record_success(state: dict, topic_name: str, adapter_name: str) -> None:
    """
    Reset consecutive_failures to 0.
    Does NOT re-enable a manually-disabled adapter; use reset() for that.
    """
    entry = _entry(state, topic_name, adapter_name)
    entry["consecutive_failures"] = 0


def record_failure(state: dict, topic_name: str, adapter_name: str) -> None:
    """
    Increment consecutive_failures. Disable the adapter when threshold is reached,
    recording the disable timestamp for auto-recovery.
    Counter is capped at FAILURE_THRESHOLD to avoid unbounded growth.
    """
    entry = _entry(state, topic_name, adapter_name)
    if entry["consecutive_failures"] < FAILURE_THRESHOLD:
        entry["consecutive_failures"] += 1
    if entry["consecutive_failures"] >= FAILURE_THRESHOLD and not entry["disabled"]:
        entry["disabled"] = True
        entry["disabled_at"] = datetime.now(timezone.utc).isoformat()
        logger.warning(
            "Circuit breaker: adapter '%s' auto-disabled for topic '%s' "
            "after %d consecutive failures. Will auto-recover in %dh.",
            adapter_name,
            topic_name,
            FAILURE_THRESHOLD,
            COOLDOWN_HOURS,
        )


def reset(state: dict, topic_name: str, adapter_name: str) -> None:
    """Re-enable a disabled adapter and clear its failure counter."""
    entry = _entry(state, topic_name, adapter_name)
    entry["consecutive_failures"] = 0
    entry["disabled"] = False
    entry["disabled_at"] = None
