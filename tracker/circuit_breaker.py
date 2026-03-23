"""
Circuit breaker for shopping adapters.

Manages the 'circuit_breakers' key inside the state dict (state.json).
All functions mutate `state` in-place. No I/O is performed here.
The poller is responsible for persisting state to disk.
"""

import logging

logger = logging.getLogger(__name__)

FAILURE_THRESHOLD = 5


def _entry(state: dict, topic_name: str, adapter_name: str) -> dict:
    """Return the mutable CB entry, creating it if needed."""
    cbs = state.setdefault("circuit_breakers", {})
    topic = cbs.setdefault(topic_name, {})
    return topic.setdefault(adapter_name, {"consecutive_failures": 0, "disabled": False})


def is_disabled(state: dict, topic_name: str, adapter_name: str) -> bool:
    """Return True if the adapter is disabled for this topic."""
    try:
        return state["circuit_breakers"][topic_name][adapter_name]["disabled"]
    except KeyError:
        return False


def record_success(state: dict, topic_name: str, adapter_name: str) -> None:
    """
    Reset consecutive_failures to 0.
    Does NOT re-enable a manually-disabled or threshold-disabled adapter;
    use reset() for that.
    """
    entry = _entry(state, topic_name, adapter_name)
    entry["consecutive_failures"] = 0


def record_failure(state: dict, topic_name: str, adapter_name: str) -> None:
    """
    Increment consecutive_failures. Disable the adapter when the threshold is reached.
    Counter is capped at FAILURE_THRESHOLD to avoid unbounded growth.
    """
    entry = _entry(state, topic_name, adapter_name)
    if entry["consecutive_failures"] < FAILURE_THRESHOLD:
        entry["consecutive_failures"] += 1
    if entry["consecutive_failures"] >= FAILURE_THRESHOLD and not entry["disabled"]:
        entry["disabled"] = True
        logger.warning(
            "Circuit breaker: adapter '%s' auto-disabled for topic '%s' "
            "after %d consecutive failures.",
            adapter_name,
            topic_name,
            FAILURE_THRESHOLD,
        )


def reset(state: dict, topic_name: str, adapter_name: str) -> None:
    """Re-enable a disabled adapter and clear its failure counter."""
    entry = _entry(state, topic_name, adapter_name)
    entry["consecutive_failures"] = 0
    entry["disabled"] = False
