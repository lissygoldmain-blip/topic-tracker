from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

import requests

from tracker.adapters.base import BaseAdapter
from tracker.models import Result, SourceConfig, TopicConfig

logger = logging.getLogger(__name__)

# Default instance. Override per-source via filters: {instance: "fosstodon.org"}
DEFAULT_INSTANCE = "mastodon.social"

_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(html: str) -> str:
    return _TAG_RE.sub("", html).strip()


class MastodonAdapter(BaseAdapter):
    """
    Searches public Mastodon posts (statuses) via the unauthenticated v2 search API.

    Searches the instance specified in source_config.filters['instance']
    (defaults to mastodon.social). For broader coverage add multiple source
    entries pointing at different instances (e.g. mastodon.social, fosstodon.org,
    sigmoid.social for tech/ML, etc.).

    Note: content is returned as HTML — stripped to plain text before storage.
    """

    source_type = "social"

    def fetch(self, source_config: SourceConfig, topic: TopicConfig) -> list[Result]:
        instance = source_config.filters.get("instance", DEFAULT_INSTANCE)
        search_url = f"https://{instance}/api/v2/search"
        results = []

        for term in source_config.terms:
            try:
                resp = requests.get(
                    search_url,
                    params={"q": term, "type": "statuses", "limit": 20},
                    timeout=10,
                )
                resp.raise_for_status()
                for status in resp.json().get("statuses", []):
                    text = _strip_html(status.get("content", ""))
                    url = status.get("url", "")
                    raw_date = status.get("created_at")
                    fetched_at = datetime.now(timezone.utc)
                    if raw_date:
                        try:
                            fetched_at = datetime.fromisoformat(
                                raw_date.replace("Z", "+00:00")
                            )
                        except ValueError:
                            pass
                    acct = status.get("account", {}).get("acct", "")
                    results.append(
                        Result(
                            url=url,
                            title=text[:120] + ("…" if len(text) > 120 else ""),
                            snippet=f"@{acct}: {text}" if acct else text,
                            source=f"mastodon:{instance}",
                            source_type=self.source_type,
                            topic_name=topic.name,
                            fetched_at=fetched_at,
                        )
                    )
            except Exception as exc:
                logger.warning(
                    "MastodonAdapter error on %s for term '%s': %s",
                    instance, term, exc,
                )
        return results
