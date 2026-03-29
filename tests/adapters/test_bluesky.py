from unittest.mock import MagicMock, patch

from tests.conftest import make_full_topic
from tracker.adapters.bluesky import BlueskyAdapter
from tracker.models import SourceConfig

TOPIC = make_full_topic()
SOURCE = SourceConfig(source="bluesky", terms=["keiji kaneko suit"])

BSKY_RESPONSE = {
    "posts": [
        {
            "uri": "at://did:plc:abc123/app.bsky.feed.post/rkey001",
            "author": {"handle": "fashionlover.bsky.social"},
            "record": {
                "text": "Just found the Keiji Kaneko Fruit of the Loom suit on Grailed!",
                "createdAt": "2026-03-23T10:00:00.000Z",
            },
            "indexedAt": "2026-03-23T10:00:01.000Z",
        },
        {
            "uri": "at://did:plc:xyz/app.bsky.feed.post/rkey002",
            "author": {"handle": "menswear.bsky.social"},
            "record": {
                "text": "This collaboration is wild — athletic formal wear",
                "createdAt": "2026-03-22T08:00:00.000Z",
            },
            "indexedAt": "2026-03-22T08:00:01.000Z",
        },
    ]
}


def _mock_get(json_data, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.raise_for_status = MagicMock(
        side_effect=None if status_code < 400 else Exception(f"HTTP {status_code}")
    )
    return resp


def test_returns_results():
    with patch("tracker.adapters.bluesky.requests.get") as mock_get:
        mock_get.return_value = _mock_get(BSKY_RESPONSE)
        results = BlueskyAdapter().fetch(SOURCE, TOPIC)
    assert len(results) == 2
    assert results[0].source == "bluesky"
    assert results[0].source_type == "social"


def test_url_constructed_from_handle_and_rkey():
    with patch("tracker.adapters.bluesky.requests.get") as mock_get:
        mock_get.return_value = _mock_get(BSKY_RESPONSE)
        results = BlueskyAdapter().fetch(SOURCE, TOPIC)
    assert results[0].url == (
        "https://bsky.app/profile/fashionlover.bsky.social/post/rkey001"
    )


def test_title_truncated_at_120():
    long_text = "x" * 200
    data = {
        "posts": [{
            "uri": "at://did:plc:a/app.bsky.feed.post/r1",
            "author": {"handle": "user.bsky.social"},
            "record": {"text": long_text, "createdAt": "2026-03-23T10:00:00.000Z"},
        }]
    }
    with patch("tracker.adapters.bluesky.requests.get") as mock_get:
        mock_get.return_value = _mock_get(data)
        results = BlueskyAdapter().fetch(SOURCE, TOPIC)
    assert results[0].title.endswith("…")
    assert len(results[0].title) == 121  # 120 chars + ellipsis


def test_http_error_returns_empty():
    with patch("tracker.adapters.bluesky.requests.get") as mock_get:
        mock_get.side_effect = Exception("timeout")
        results = BlueskyAdapter().fetch(SOURCE, TOPIC)
    assert results == []


def test_multiple_terms_each_queried():
    source = SourceConfig(source="bluesky", terms=["term one", "term two"])
    with patch("tracker.adapters.bluesky.requests.get") as mock_get:
        mock_get.return_value = _mock_get({"posts": []})
        BlueskyAdapter().fetch(source, TOPIC)
    assert mock_get.call_count == 2


# ── Author feed (profiles) tests ──────────────────────────────────────────

AUTHOR_FEED_RESPONSE = {
    "feed": [
        {
            "post": {
                "uri": "at://did:plc:wf/app.bsky.feed.post/drop001",
                "author": {"handle": "wildfang.bsky.social"},
                "record": {
                    "text": "New drop! The Tomboy Tux is back in stock 🎉",
                    "createdAt": "2026-03-28T14:00:00.000Z",
                },
                "indexedAt": "2026-03-28T14:00:01.000Z",
            }
        }
    ]
}


def test_profile_feed_fetches_author_feed():
    source = SourceConfig(source="bluesky", profiles=["wildfang.bsky.social"])
    with patch("tracker.adapters.bluesky.requests.get") as mock_get:
        mock_get.return_value = _mock_get(AUTHOR_FEED_RESPONSE)
        results = BlueskyAdapter().fetch(source, TOPIC)
    assert len(results) == 1
    assert results[0].url == "https://bsky.app/profile/wildfang.bsky.social/post/drop001"
    assert results[0].source_type == "social"


def test_profile_feed_uses_author_feed_endpoint():
    source = SourceConfig(source="bluesky", profiles=["wildfang.bsky.social"])
    with patch("tracker.adapters.bluesky.requests.get") as mock_get:
        mock_get.return_value = _mock_get(AUTHOR_FEED_RESPONSE)
        BlueskyAdapter().fetch(source, TOPIC)
    call_url = mock_get.call_args[0][0]
    assert "getAuthorFeed" in call_url


def test_profiles_and_terms_both_fetched():
    source = SourceConfig(
        source="bluesky",
        profiles=["wildfang.bsky.social"],
        terms=["wildfang sale"],
    )
    with patch("tracker.adapters.bluesky.requests.get") as mock_get:
        mock_get.side_effect = [
            _mock_get(AUTHOR_FEED_RESPONSE),  # author feed
            _mock_get({"posts": []}),          # search
        ]
        results = BlueskyAdapter().fetch(source, TOPIC)
    assert mock_get.call_count == 2
    assert len(results) == 1  # only author feed returned a result


def test_profile_feed_error_returns_empty_gracefully():
    source = SourceConfig(source="bluesky", profiles=["wildfang.bsky.social"])
    with patch("tracker.adapters.bluesky.requests.get", side_effect=Exception("timeout")):
        results = BlueskyAdapter().fetch(source, TOPIC)
    assert results == []
