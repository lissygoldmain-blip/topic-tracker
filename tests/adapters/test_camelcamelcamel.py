from unittest.mock import MagicMock, patch

from tests.conftest import make_full_topic
from tracker.adapters.camelcamelcamel import CamelCamelCamelAdapter
from tracker.models import SourceConfig

TOPIC = make_full_topic()
SOURCE = SourceConfig(
    source="camelcamelcamel",
    filters={"asins": ["B09XXXXXXX", "B0AXXXXXXX"]},
)


def _make_feed(entries):
    feed = MagicMock()
    feed.entries = entries
    return feed


def _make_entry(link, title, published_parsed=None):
    e = MagicMock()
    e.link = link
    e.title = title
    e.summary = ""
    if published_parsed is not None:
        e.published_parsed = published_parsed
    else:
        del e.published_parsed
    return e


def _mock_response(content=b"<feed />"):
    resp = MagicMock()
    resp.content = content
    resp.raise_for_status = MagicMock()
    return resp


def test_fetches_each_asin():
    with patch("tracker.adapters.camelcamelcamel.requests.get") as mock_get, \
         patch("tracker.adapters.camelcamelcamel.feedparser.parse") as mock_parse:
        mock_get.return_value = _mock_response()
        mock_parse.return_value = _make_feed([])
        CamelCamelCamelAdapter().fetch(SOURCE, TOPIC)
    assert mock_get.call_count == 2
    urls = [c[0][0] for c in mock_get.call_args_list]
    assert any("B09XXXXXXX" in u for u in urls)
    assert any("B0AXXXXXXX" in u for u in urls)


def test_returns_results():
    entry = _make_entry(
        "https://camelcamelcamel.com/product/B09XXXXXXX",
        "Amazon Price Drop: Product dropped to $89.99",
        published_parsed=(2026, 3, 23, 10, 0, 0, 0, 0, 0),
    )
    source = SourceConfig(
        source="camelcamelcamel", filters={"asins": ["B09XXXXXXX"]}
    )
    with patch("tracker.adapters.camelcamelcamel.requests.get") as mock_get, \
         patch("tracker.adapters.camelcamelcamel.feedparser.parse") as mock_parse:
        mock_get.return_value = _mock_response()
        mock_parse.return_value = _make_feed([entry])
        results = CamelCamelCamelAdapter().fetch(source, TOPIC)
    assert len(results) == 1
    assert results[0].source == "camelcamelcamel"
    assert results[0].source_type == "shopping"


def test_empty_asins_returns_empty():
    source = SourceConfig(source="camelcamelcamel", filters={})
    results = CamelCamelCamelAdapter().fetch(source, TOPIC)
    assert results == []


def test_error_returns_empty():
    with patch("tracker.adapters.camelcamelcamel.requests.get") as mock_get:
        mock_get.side_effect = Exception("network error")
        results = CamelCamelCamelAdapter().fetch(SOURCE, TOPIC)
    assert results == []


def test_fetch_uses_timeout():
    """requests.get must always be called with a timeout to prevent hanging."""
    source = SourceConfig(
        source="camelcamelcamel", filters={"asins": ["B09XXXXXXX"]}
    )
    with patch("tracker.adapters.camelcamelcamel.requests.get") as mock_get, \
         patch("tracker.adapters.camelcamelcamel.feedparser.parse") as mock_parse:
        mock_get.return_value = _mock_response()
        mock_parse.return_value = _make_feed([])
        CamelCamelCamelAdapter().fetch(source, TOPIC)
    _, kwargs = mock_get.call_args
    assert "timeout" in kwargs
    assert kwargs["timeout"] > 0
