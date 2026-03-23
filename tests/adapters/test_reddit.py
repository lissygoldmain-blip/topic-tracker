from unittest.mock import MagicMock, patch

from tests.conftest import make_full_topic
from tracker.adapters.reddit import RedditAdapter
from tracker.models import SourceConfig

TOPIC = make_full_topic()


def _make_feed(entries):
    feed = MagicMock()
    feed.entries = entries
    return feed


def _make_entry(link, title, summary="", published_parsed=None):
    e = MagicMock()
    e.link = link
    e.title = title
    e.summary = summary
    if published_parsed:
        e.published_parsed = published_parsed
        e.published_parsed = published_parsed
    else:
        del e.published_parsed  # not present on this entry
    return e


# Make MagicMock not carry published_parsed by default
def _make_entry_no_date(link, title):
    e = MagicMock(spec=["link", "title", "summary"])
    e.link = link
    e.title = title
    e.summary = ""
    return e


def test_subreddit_feeds_fetched():
    source = SourceConfig(
        source="reddit", subreddits=["malefashionadvice", "Grailed"]
    )
    with patch("tracker.adapters.reddit.feedparser.parse") as mock_parse:
        mock_parse.return_value = _make_feed([])
        RedditAdapter().fetch(source, TOPIC)
    assert mock_parse.call_count == 2
    urls = [call.args[0] for call in mock_parse.call_args_list]
    assert any("malefashionadvice" in u for u in urls)
    assert any("Grailed" in u for u in urls)


def test_terms_searched():
    source = SourceConfig(source="reddit", terms=["keiji kaneko suit"])
    with patch("tracker.adapters.reddit.feedparser.parse") as mock_parse:
        mock_parse.return_value = _make_feed([])
        RedditAdapter().fetch(source, TOPIC)
    assert mock_parse.call_count == 1
    url = mock_parse.call_args.args[0]
    assert "search.rss" in url
    assert "keiji" in url


def test_returns_results():
    entry = MagicMock()
    entry.link = "https://reddit.com/r/mfa/comments/abc"
    entry.title = "Found Kaneko suit on Grailed"
    entry.summary = "Link in comments"
    entry.published_parsed = (2026, 3, 23, 10, 0, 0, 0, 0, 0)

    source = SourceConfig(source="reddit", subreddits=["malefashionadvice"])
    with patch("tracker.adapters.reddit.feedparser.parse") as mock_parse:
        mock_parse.return_value = _make_feed([entry])
        results = RedditAdapter().fetch(source, TOPIC)

    assert len(results) == 1
    assert results[0].source == "reddit"
    assert results[0].source_type == "social"
    assert results[0].url == "https://reddit.com/r/mfa/comments/abc"


def test_feedparser_error_returns_empty():
    source = SourceConfig(source="reddit", subreddits=["malefashionadvice"])
    with patch("tracker.adapters.reddit.feedparser.parse") as mock_parse:
        mock_parse.side_effect = Exception("network error")
        results = RedditAdapter().fetch(source, TOPIC)
    assert results == []


def test_both_subreddits_and_terms():
    source = SourceConfig(
        source="reddit",
        subreddits=["Grailed"],
        terms=["keiji kaneko"],
    )
    with patch("tracker.adapters.reddit.feedparser.parse") as mock_parse:
        mock_parse.return_value = _make_feed([])
        RedditAdapter().fetch(source, TOPIC)
    assert mock_parse.call_count == 2
