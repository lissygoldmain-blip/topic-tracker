from __future__ import annotations

import json
import logging
import math
import os
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass as _dataclass

from tracker import circuit_breaker as cb
from tracker import escalation as esc
from tracker.adapters import (
    AdzunaAdapter,
    ArxivAdapter,
    BioRxivAdapter,
    BlueskyAdapter,
    EmailNewsletterAdapter,
    CamelCamelCamelAdapter,
    EbayAdapter,
    EtsyAdapter,
    GDELTAdapter,
    GenericRSSAdapter,
    GoogleNewsAdapter,
    GrailedAdapter,
    GuardianAdapter,
    HackerNewsAdapter,
    IndeedAdapter,
    MastodonAdapter,
    MercariUSAdapter,
    NewsAPIAdapter,
    NYTimesAdapter,
    PlaybillJobsAdapter,
    PubMedAdapter,
    RedditAdapter,
    SemanticScholarAdapter,
    SlickdealsAdapter,
    SubstackAdapter,
    TMDbAdapter,
    USITTJobsAdapter,
    WeatherAdapter,
    YouTubeAdapter,
)
from tracker.adapters.base import BaseAdapter
from tracker.config import load_topics
from tracker.models import Result, TopicConfig
from tracker.notifications.email import EmailNotifier
from tracker.notifications.ntfy import NtfyNotifier
from tracker.pipeline.stage1 import Stage1Filter
from tracker.storage import Storage

logger = logging.getLogger(__name__)


@_dataclass
class _TopicRun:
    fetched: int = 0   # all items returned by adapters (including already-seen)
    new: int = 0       # items that passed in-run dedup (entered Stage1 queue)
    scored: int = 0    # items actually sent to Stage1 after per-topic budget cap
    passed: int = 0    # items that passed Stage1 quality filter


# Maps urgency level to list of tier names by index (tier1=0, tier2=1, tier3=2, tier4=3)
TIER_MAP = {
    "urgent": ["frequent", "discovery", "broad", "broad"],
    "high":   ["frequent", "discovery", "broad", "broad"],
    "medium": ["discovery", "broad", "broad"],
    "low":    ["broad", "broad"],
}

ADAPTERS: dict[str, type[BaseAdapter]] = {
    "google_news": GoogleNewsAdapter,
    "email": EmailNewsletterAdapter,
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
    "tmdb": TMDbAdapter,
    "camelcamelcamel": CamelCamelCamelAdapter,
    "weather": WeatherAdapter,
    "gdelt": GDELTAdapter,
    "nytimes": NYTimesAdapter,
    "guardian": GuardianAdapter,
    "pubmed": PubMedAdapter,
    "arxiv": ArxivAdapter,
    "biorxiv": BioRxivAdapter,
    "medrxiv": BioRxivAdapter,
    "semantic_scholar": SemanticScholarAdapter,
    "indeed": IndeedAdapter,
    "adzuna": AdzunaAdapter,
    "substack": SubstackAdapter,
    "playbill_jobs": PlaybillJobsAdapter,
    "usitt_jobs": USITTJobsAdapter,
}


def run_poll(tier_index: int = 0, topics_path: str = "topics.yaml", data_dir: str = ".") -> None:
    """
    tier_index: 0=tier1 (frequent), 1=tier2 (discovery), 2=tier3, 3=tier4
    """
    logging.basicConfig(level=logging.INFO)

    gemini_key = os.environ.get("GEMINI_API_KEY", "")
    if not gemini_key:
        raise RuntimeError(
            "GEMINI_API_KEY is not set. Add it to your .env file or GitHub Secrets."
        )
    resend_key = os.environ.get("RESEND_API_KEY", "")
    to_email = os.environ.get("TO_EMAIL", "")
    from_email = os.environ.get("FROM_EMAIL", "")

    topics = load_topics(topics_path)
    storage = Storage(data_dir=data_dir)
    storage.load()
    storage.prune()

    state = storage.load_state()

    feedback_path = os.path.join(data_dir, "feedback.json")
    feedback: list = []
    if os.path.exists(feedback_path):
        try:
            with open(feedback_path) as _f:
                feedback = json.load(_f)
            logger.info("Loaded %d feedback entries from feedback.json", len(feedback))
        except Exception as _e:
            logger.warning("Could not load feedback.json: %s", _e)

    stage1 = Stage1Filter(api_key=gemini_key, feedback=feedback)
    notifier = EmailNotifier(
        api_key=resend_key, from_email=from_email, to_email=to_email
    ) if resend_key else None
    ntfy_topic = os.environ.get("NTFY_TOPIC", "")
    push_notifier = NtfyNotifier(ntfy_topic) if ntfy_topic else None

    # In-memory dedup for the current run only. Prevents the same URL from being
    # scored twice if two adapters (or two topics) return it in a single run.
    # Kept separate from storage.mark_seen() so that URLs which are fetched but
    # NOT passed by Stage1 (e.g. quota hit) are NOT permanently recorded as seen
    # — they remain eligible for re-scoring on the next run.
    within_run_seen: set[str] = set()

    # Proportional budget: each topic gets a fair share of the remaining Gemini
    # slots. Topics that are skipped (tier mismatch, no sources, CB disabled)
    # donate their allocation to later topics because remaining_topics is
    # decremented unconditionally at the top of each iteration.
    remaining_topics = len(topics)
    run_stats: dict[str, _TopicRun] = {}

    for topic in topics:
        global_remaining = stage1.MAX_ITEMS_PER_RUN - stage1._items_scored_this_run
        per_topic_budget = math.ceil(global_remaining / remaining_topics) if remaining_topics > 0 else 0
        remaining_topics -= 1
        run_stats.setdefault(topic.name, _TopicRun())
        urgency = esc.effective_urgency(state, topic)
        tier_names = TIER_MAP.get(urgency, ["discovery"])
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

            run_stats[topic.name].fetched += len(results)
            for r in results:
                if not storage.is_seen(r.url) and r.url not in within_run_seen:
                    raw_results.append((r, topic))
                    within_run_seen.add(r.url)

        run_stats[topic.name].new += len(raw_results)

        # Staleness filter: drop news/feeds/social items older than 7 days,
        # science items older than 30 days. Jobs and shopping pass through
        # (they don't set published_at, or recency is managed by adapter filters).
        _stale_cutoffs = {"news": 7, "feeds": 7, "social": 7, "science": 30}
        _now = datetime.now(timezone.utc)
        fresh_results = []
        for r, t in raw_results:
            cutoff_days = _stale_cutoffs.get(r.source_type)
            if cutoff_days and r.published_at:
                age = _now - r.published_at.replace(tzinfo=timezone.utc) if r.published_at.tzinfo is None else _now - r.published_at
                if age > timedelta(days=cutoff_days):
                    continue
            fresh_results.append((r, t))
        if len(fresh_results) < len(raw_results):
            logger.info(
                "Staleness filter: dropped %d old items for '%s'",
                len(raw_results) - len(fresh_results), topic.name,
            )
        raw_results = fresh_results

        if not raw_results:
            logger.info("No new results for topic '%s' at tier '%s'", topic.name, tier_name)
            continue

        if len(raw_results) > per_topic_budget:
            logger.info(
                "Budget: capping '%s' at %d items (fair share of %d remaining slots)",
                topic.name, per_topic_budget, global_remaining,
            )
            raw_results = raw_results[:per_topic_budget]

        run_stats[topic.name].scored += len(raw_results)
        passed = stage1.filter(raw_results)
        run_stats[topic.name].passed += len(passed)
        logger.info(
            "%d/%d results passed Stage 1 for '%s'", len(passed), len(raw_results), topic.name
        )

        esc.check_and_apply(state, passed)

        for result, t in passed:
            # Only persist URLs that actually passed Stage1 — items deferred due to
            # quota exhaustion stay absent from seen_urls.json and will be retried.
            storage.mark_seen(result.url, source_type=result.source_type)
            storage.add_result(result)
            if notifier and t.notifications.get("email") == "immediate":
                notifier.send_immediate(result)
            if push_notifier and t.notifications.get("push"):
                should_push = (
                    result.escalation_trigger is not None
                    or (result.novelty_score or 0) >= t.novelty_push_threshold
                )
                if should_push:
                    urgency = esc.effective_urgency(state, t)
                    push_notifier.send(result, urgency=urgency)

    storage.save_state(state)
    storage.save()

    # ── Per-topic summary ─────────────────────────────────────────────────────
    logger.info("── Poll summary %s", "─" * 50)
    logger.info("  %-26s %7s %5s %6s %6s", "Topic", "Fetched", "New", "Scored", "Passed")
    logger.info("  %-26s %7s %5s %6s %6s", "─" * 26, "─" * 7, "─" * 5, "─" * 6, "─" * 6)
    for tname, s in run_stats.items():
        logger.info("  %-26s %7d %5d %6d %6d", tname, s.fetched, s.new, s.scored, s.passed)
    used = stage1._items_scored_this_run
    logger.info("  Gemini slots used: %d / %d", used, stage1.MAX_ITEMS_PER_RUN)
    if stage1._quota_exhausted:
        logger.warning("  ⚠ Daily quota exhausted during this run")
    logger.info("─" * 66)

    logger.info("Poll complete.")


def run_digest(topics_path: str = "topics.yaml", data_dir: str = ".") -> None:
    """Send a weekly digest email of all unnotified results, then mark them as sent."""
    logging.basicConfig(level=logging.INFO)

    resend_key = os.environ.get("RESEND_API_KEY", "")
    to_email = os.environ.get("TO_EMAIL", "")
    from_email = os.environ.get("FROM_EMAIL", "")

    if not resend_key:
        logger.warning("Digest: RESEND_API_KEY not set — skipping")
        return

    storage = Storage(data_dir=data_dir)
    storage.load()

    index = storage.get_index()

    # Collect all results not yet included in a digest
    unnotified: list[Result] = []
    for result_dicts in index.values():
        for d in result_dicts:
            if not d.get("notified_digest", False):
                unnotified.append(Result.from_dict(d))

    if not unnotified:
        logger.info("Digest: no new results to send")
        return

    # Sort: topic name first (groups topics together), then novelty descending within each topic
    unnotified.sort(key=lambda r: (r.topic_name, -(r.novelty_score or 0.0)))

    from datetime import date

    week_str = date.today().strftime("%b %d, %Y")
    subject = f"Topic Tracker Digest — {week_str}"

    notifier = EmailNotifier(api_key=resend_key, from_email=from_email, to_email=to_email)
    notifier.send_digest(unnotified, subject=subject)

    # send_digest sets r.notified_digest = True on each Result object.
    # Mirror that back into the live index dicts so storage.save() persists it.
    notified_urls = {r.url for r in unnotified if r.notified_digest}
    for result_dicts in index.values():
        for d in result_dicts:
            if d.get("url") in notified_urls:
                d["notified_digest"] = True

    storage.save()
    logger.info("Digest: sent %d results", len(notified_urls))
