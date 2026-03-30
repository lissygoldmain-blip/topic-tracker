from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

import requests

from tracker.adapters.base import BaseAdapter
from tracker.models import Result, SourceConfig, TopicConfig

logger = logging.getLogger(__name__)

BSKY_SEARCH_URL  = "https://public.api.bsky.app/xrpc/app.bsky.feed.searchPosts"
BSKY_AUTHOR_URL  = "https://public.api.bsky.app/xrpc/app.bsky.feed.getAuthorFeed"
BSKY_SESSION_URL = "https://bsky.social/xrpc/com.atproto.server.createSession"


def _get_access_token() -> str | None:
    """Exchange BSKY_IDENTIFIER + BSKY_APP_PASSWORD for a short-lived access JWT."""
    identifier = os.environ.get("BSKY_IDENTIFIER", "")
    password   = os.environ.get("BSKY_APP_PASSWORD", "")
    if not identifier or not password:
        return None
    try:
        resp = requests.post(
            BSKY_SESSION_URL,
            json={"identifier": identifier, "password": password},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json().get("accessJwt")
    except Exception as exc:
        logger.warning("BlueskyAdapter: could not create session: %s", exc)
        return None


class BlueskyAdapter(BaseAdapter):
    """
    Fetches Bluesky posts via the AT Protocol AppView.
    - source_config.terms: keyword search (requires BSKY_IDENTIFIER + BSKY_APP_PASSWORD)
    - source_config.profiles: pull directly from specific account feeds (no auth needed)

    Optional env vars:
        BSKY_IDENTIFIER    — handle or DID (e.g. "user.bsky.social")
        BSKY_APP_PASSWORD  — Bluesky app password (Settings → App Passwords)
    """

    source_type = "social"

    def fetch(self, source_config: SourceConfig, topic: TopicConfig) -> list[Result]:
        results = []

        for handle in source_config.profiles:
            try:
                resp = requests.get(
                    BSKY_AUTHOR_URL,
                    params={"actor": handle, "limit": 25, "filter": "posts_no_replies"},
                    timeout=10,
                )
                resp.raise_for_status()
                for item in resp.json().get("feed", []):
                    post = item.get("post", {})
                    results.append(self._post_to_result(post, topic))
            except Exception as exc:
                logger.warning("BlueskyAdapter author feed error for '%s': %s", handle, exc)

        if source_config.terms:
            token = _get_access_token()
            headers = {"Authorization": f"Bearer {token}"} if token else {}
            if not token:
                logger.warning(
                    "BlueskyAdapter: BSKY_IDENTIFIER/BSKY_APP_PASSWORD not set — "
                    "search may be blocked from datacenter IPs"
                )

            for term in source_config.terms:
                try:
                    resp = requests.get(
                        BSKY_SEARCH_URL,
                        params={"q": term, "limit": 25},
                        headers=headers,
                        timeout=10,
                    )
                    resp.raise_for_status()
                    for post in resp.json().get("posts", []):
                        results.append(self._post_to_result(post, topic))
                except Exception as exc:
                    logger.warning("BlueskyAdapter search error for term '%s': %s", term, exc)

        return results

    def _post_to_result(self, post: dict, topic: TopicConfig) -> Result:
        handle = post.get("author", {}).get("handle", "")
        uri = post.get("uri", "")
        rkey = uri.rsplit("/", 1)[-1] if uri else ""
        url = (
            f"https://bsky.app/profile/{handle}/post/{rkey}"
            if handle and rkey else ""
        )
        record = post.get("record", {})
        text = record.get("text", "")
        raw_date = record.get("createdAt") or post.get("indexedAt")
        post_date = datetime.now(timezone.utc)
        if raw_date:
            try:
                post_date = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
            except ValueError:
                pass
        return Result(
            url=url,
            title=text[:120] + ("…" if len(text) > 120 else ""),
            snippet=text,
            source="bluesky",
            source_type=self.source_type,
            topic_name=topic.name,
            fetched_at=datetime.now(timezone.utc),
            published_at=post_date,
        )
