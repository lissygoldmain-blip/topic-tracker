from unittest.mock import MagicMock, patch

from tests.conftest import make_full_topic
from tracker.adapters.mastodon import MastodonAdapter, _strip_html
from tracker.models import SourceConfig

TOPIC = make_full_topic()
SOURCE = SourceConfig(source="mastodon", terms=["keiji kaneko suit"])

MASTODON_RESPONSE = {
    "statuses": [
        {
            "id": "111111",
            "url": "https://mastodon.social/@fashionista/111111",
            "content": "<p>Just saw the <strong>Keiji Kaneko</strong> suit drop!</p>",
            "created_at": "2026-03-23T10:00:00.000Z",
            "account": {"acct": "fashionista@mastodon.social"},
        },
        {
            "id": "222222",
            "url": "https://mastodon.social/@menswear/222222",
            "content": "<p>This collab is amazing</p>",
            "created_at": "2026-03-22T08:00:00.000Z",
            "account": {"acct": "menswear"},
        },
    ]
}


def _mock_get(json_data, status_code=200):
    resp = MagicMock()
    resp.json.return_value = json_data
    resp.raise_for_status = MagicMock(
        side_effect=None if status_code < 400 else Exception(f"HTTP {status_code}")
    )
    return resp


def test_strip_html():
    assert _strip_html("<p>Hello <strong>world</strong></p>") == "Hello world"
    assert _strip_html("plain text") == "plain text"
    assert _strip_html("") == ""


def test_returns_results():
    with patch("tracker.adapters.mastodon.requests.get") as mock_get:
        mock_get.return_value = _mock_get(MASTODON_RESPONSE)
        results = MastodonAdapter().fetch(SOURCE, TOPIC)
    assert len(results) == 2
    assert results[0].source_type == "social"


def test_html_stripped_from_title_and_snippet():
    with patch("tracker.adapters.mastodon.requests.get") as mock_get:
        mock_get.return_value = _mock_get(MASTODON_RESPONSE)
        results = MastodonAdapter().fetch(SOURCE, TOPIC)
    assert "<p>" not in results[0].title
    assert "<strong>" not in results[0].title


def test_source_includes_instance():
    with patch("tracker.adapters.mastodon.requests.get") as mock_get:
        mock_get.return_value = _mock_get(MASTODON_RESPONSE)
        results = MastodonAdapter().fetch(SOURCE, TOPIC)
    assert results[0].source == "mastodon:mastodon.social"


def test_custom_instance_from_filters():
    source = SourceConfig(
        source="mastodon",
        terms=["fashion"],
        filters={"instance": "fosstodon.org"},
    )
    with patch("tracker.adapters.mastodon.requests.get") as mock_get:
        mock_get.return_value = _mock_get({"statuses": []})
        MastodonAdapter().fetch(source, TOPIC)
    url = mock_get.call_args.args[0]
    assert "fosstodon.org" in url


def test_http_error_returns_empty():
    with patch("tracker.adapters.mastodon.requests.get") as mock_get:
        mock_get.side_effect = Exception("connection refused")
        results = MastodonAdapter().fetch(SOURCE, TOPIC)
    assert results == []
