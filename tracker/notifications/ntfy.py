from __future__ import annotations

import logging

import requests

from tracker.models import Result

logger = logging.getLogger(__name__)

_URGENCY_PRIORITY = {"urgent": 5, "high": 4, "medium": 3, "low": 2}

# Emoji tags that show as icons in the ntfy app
_TOPIC_TAGS = {
    "Immigration & ICE":  "rotating_light",
    "Jobs":               "briefcase",
    "Shopping":           "shopping_cart",
    "Health research":    "pill",
    "Drag Race & drag":   "crown",
    "Queer & trans":      "rainbow",
    "Politics & world":   "newspaper",
}


class NtfyNotifier:
    """
    Sends push notifications via ntfy.sh (no account required).

    Required env var:
      NTFY_TOPIC — the private channel name, e.g. "lissy-tracker-xk9q2"
                   Set in GitHub Secrets and in the ntfy app on your phone.

    Usage in topics.yaml (notifications section):
      push: true                 → send on any escalation_trigger
      novelty_push_threshold: X  → also send if novelty_score >= X
    """

    BASE_URL = "https://ntfy.sh"

    def __init__(self, topic: str) -> None:
        self._topic = topic
        self._url = f"{self.BASE_URL}/{topic}"

    def send(self, result: Result, urgency: str = "high") -> None:
        priority = _URGENCY_PRIORITY.get(urgency, 4)
        tag = _TOPIC_TAGS.get(result.topic_name, "bell")
        if result.escalation_trigger:
            tag = "rotating_light"

        title = f"{result.topic_name}"
        if result.escalation_trigger:
            title += f" · {result.escalation_trigger}"

        try:
            resp = requests.post(
                self._url,
                data=result.title.encode("utf-8"),
                headers={
                    "Title":    title,
                    "Priority": str(priority),
                    "Tags":     tag,
                    "Click":    result.url,
                },
                timeout=10,
            )
            if not resp.ok:
                logger.warning("NtfyNotifier: HTTP %d for '%s'", resp.status_code, result.url)
            else:
                result.notified_push = True
        except Exception as exc:
            logger.warning("NtfyNotifier error for '%s': %s", result.url, exc)
