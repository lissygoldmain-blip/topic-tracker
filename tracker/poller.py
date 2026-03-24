from __future__ import annotations

import logging
import os

from tracker import circuit_breaker as cb
from tracker.adapters import (
    BlueskyAdapter,
    CamelCamelCamelAdapter,
    EbayAdapter,
    EtsyAdapter,
    GDELTAdapter,
    GenericRSSAdapter,
    GoogleNewsAdapter,
    GrailedAdapter,
    HackerNewsAdapter,
    MastodonAdapter,
    MercariUSAdapter,
    NewsAPIAdapter,
    RedditAdapter,
    SlickdealsAdapter,
    WeatherAdapter,
    YouTubeAdapter,
)
from tracker.adapters.base import BaseAdapter
from tracker.config import load_topics
from tracker.models import Result, TopicConfig
from tracker.notifications.email import EmailNotifier
from tracker.pipeline.stage1 import Stage1Filter
from tracker.storage import Storage

logger = logging.getLogger(__name__)

# Maps urgency level to list of tier names by index (tier1=0, tier2=1, tier3=2, tier4=3)
TIER_MAP = {
    "urgent": ["frequent", "discovery", "broad", "broad"],
    "high":   ["frequent", "discovery", "broad", "broad"],
    "medium": ["discovery", "broad", "broad"],
    "low":    ["broad", "broad"],
}

ADAPTERS: dict[str, type[BaseAdapter]] = {
    "google_news": GoogleNewsAdapter,
    "ebay": EbayAdapter,
    "etsy": EtsyAdapter,
    "grailed": GrailedAdapter,
    "mercari": MercariUSAdapter,
    "hacker_news": HackerNewsAdapter,
    "reddit": RedditAdapter,
    "rss": GenericRSSAdapter,
    "bluesky": BlueskyAdapter,
    "mastodon": MastodonAdapter,
    "youtube": YouTubeAdapter,
    "newsapi": NewsAPIAdapter,
    "slickdeals": SlickdealsAdapter,
    "camelcamelcamel": CamelCamelCamelAdapter,
    "weather": WeatherAdapter,
    "gdelt": GDELTAdapter,
}


def run_poll(tier_index: int = 0, topics_path: str = "topics.yaml", data_dir: str = ".") -> None:
    """
    tier_index: 0=tier1 (frequent), 1=tier2 (discovery), 2=tier3, 3=tier4
    """
    logging.basicConfig(level=logging.INFO)

    gemini_key = os.environ["GEMINI_API_KEY"]
    resend_key = os.environ["RESEND_API_KEY"]
    to_email = os.environ.get("TO_EMAIL", "lissygold.junk@gmail.com")
    from_email = os.environ.get("FROM_EMAIL", "tracker@updates.resend.dev")

    topics = load_topics(topics_path)
    storage = Storage(data_dir=data_dir)
    storage.load()
    storage.prune()

    state = storage.load_state()

    stage1 = Stage1Filter(api_key=gemini_key)
    notifier = EmailNotifier(api_key=resend_key, from_email=from_email, to_email=to_email)

    for topic in topics:
        tier_names = TIER_MAP.get(topic.urgency, ["discovery"])
        if tier_index >= len(tier_names):
            continue  # this urgency level has no tier at this index
        tier_name = tier_names[tier_index]
        sources = topic.sources_for_tier(tier_name)

        raw_results: list[tuple[Result, TopicConfig]] = []
        for source_config in sources:
            adapter_cls = ADAPTERS.get(source_config.source)
            if adapter_cls is None:
                logger.warning("No adapter for source '%s', skipping", source_config.source)
                continue

            # Circuit breaker: skip auto-disabled adapters
            if cb.is_disabled(state, topic.name, source_config.source):
                logger.info(
                    "Circuit breaker: skipping '%s' for topic '%s' (auto-disabled)",
                    source_config.source,
                    topic.name,
                )
                continue

            try:
                adapter = adapter_cls()
                results = adapter.fetch(source_config, topic)
                if getattr(adapter, "_last_failed", False):
                    cb.record_failure(state, topic.name, source_config.source)
                else:
                    cb.record_success(state, topic.name, source_config.source)
            except Exception as exc:
                logger.warning(
                    "Adapter '%s' raised an unhandled exception for topic '%s': %s",
                    source_config.source,
                    topic.name,
                    exc,
                )
                cb.record_failure(state, topic.name, source_config.source)
                results = []

            for r in results:
                if not storage.is_seen(r.url):
                    raw_results.append((r, topic))
                    storage.mark_seen(r.url, source_type=r.source_type)

        if not raw_results:
            logger.info("No new results for topic '%s' at tier '%s'", topic.name, tier_name)
            continue

        passed = stage1.filter(raw_results)
        logger.info(
            "%d/%d results passed Stage 1 for '%s'", len(passed), len(raw_results), topic.name
        )

        for result, t in passed:
            storage.add_result(result)
            if t.notifications.get("email") == "immediate":
                notifier.send_immediate(result)

    storage.save_state(state)
    storage.save()
    logger.info("Poll complete.")
