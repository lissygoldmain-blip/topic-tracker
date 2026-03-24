from unittest.mock import MagicMock, patch

import pytest

from tracker.adapters.mercari_us import MercariUSAdapter
from tracker.models import SourceConfig, TopicConfig

FAKE_API_RESPONSE = {
    "items": [
        {"id": "m111", "name": "Keiji Kaneko Suit Jacket", "price": 35000,
         "status": "ITEM_STATUS_ON_SALE"},
        {"id": "m222", "name": "1960s Japanese Suit", "price": 20000,
         "status": "ITEM_STATUS_ON_SALE"},
    ]
}


def make_mock_response(json_data=None, status_code=200):
    mock = MagicMock()
    mock.status_code = status_code
    mock.json.return_value = json_data or {}
    if status_code >= 400:
        mock.raise_for_status.side_effect = Exception(f"HTTP {status_code}")
    else:
        mock.raise_for_status.return_value = None
    return mock


def make_source_config(**kwargs):
    return SourceConfig(source="mercari", **kwargs)


def make_topic(name="Keiji Kaneko suit"):
    return TopicConfig(
        name=name,
        description="test",
        importance="high",
        urgency="medium",
        source_categories=["shopping"],
        polling={"frequent": [], "discovery": [], "broad": []},
        notifications={"push": True, "email": "weekly_digest", "novelty_push_threshold": 0.7},
        llm_filter={"novelty_threshold": 0.65, "semantic_dedup_threshold": 0.85, "tags": []},
        escalation={"triggers": [], "auto_revert": True},
    )


class TestMercariUSAdapterMeta:
    def test_source_type_is_shopping(self):
        assert MercariUSAdapter.source_type == "shopping"


class TestMercariUSFetch:
    def test_successful_fetch_returns_results(self):
        with patch("tracker.adapters.mercari_us.requests.post") as mock_post:
            mock_post.return_value = make_mock_response(FAKE_API_RESPONSE)
            adapter = MercariUSAdapter()
            results = adapter.fetch(make_source_config(), make_topic())

        assert len(results) == 2
        assert results[0].title == "Keiji Kaneko Suit Jacket"
        assert results[0].url == "https://jp.mercari.com/item/m111"
        assert results[0].price == "¥35,000"
        assert results[0].source == "mercari"
        assert results[0].source_type == "shopping"

    def test_uses_source_terms_when_provided(self):
        with patch("tracker.adapters.mercari_us.requests.post") as mock_post:
            mock_post.return_value = make_mock_response({"items": []})
            adapter = MercariUSAdapter()
            adapter.fetch(make_source_config(terms=["kaneko suit", "fruit loom kaneko"]),
                          make_topic())

        assert mock_post.call_count == 2  # one call per term

    def test_falls_back_to_topic_name_when_no_terms(self):
        with patch("tracker.adapters.mercari_us.requests.post") as mock_post:
            mock_post.return_value = make_mock_response({"items": []})
            adapter = MercariUSAdapter()
            adapter.fetch(make_source_config(), make_topic("My Topic"))

        body = mock_post.call_args.kwargs.get("data") or mock_post.call_args.args[1]
        import json
        parsed = json.loads(body)
        assert parsed["searchCondition"]["keyword"] == "My Topic"

    def test_empty_items_returns_empty_list(self):
        with patch("tracker.adapters.mercari_us.requests.post") as mock_post:
            mock_post.return_value = make_mock_response({"items": []})
            adapter = MercariUSAdapter()
            results = adapter.fetch(make_source_config(), make_topic())
        assert results == []

    def test_http_error_returns_empty_and_sets_last_failed(self):
        with patch("tracker.adapters.mercari_us.requests.post") as mock_post:
            mock_post.return_value = make_mock_response(status_code=403)
            adapter = MercariUSAdapter()
            results = adapter.fetch(make_source_config(), make_topic())
        assert results == []
        assert adapter._last_failed is True

    def test_item_without_price_maps_to_none(self):
        response = {"items": [{"id": "m333", "name": "No Price Item"}]}
        with patch("tracker.adapters.mercari_us.requests.post") as mock_post:
            mock_post.return_value = make_mock_response(response)
            adapter = MercariUSAdapter()
            results = adapter.fetch(make_source_config(), make_topic())
        assert results[0].price is None

    def test_last_failed_false_on_success(self):
        with patch("tracker.adapters.mercari_us.requests.post") as mock_post:
            mock_post.return_value = make_mock_response(FAKE_API_RESPONSE)
            adapter = MercariUSAdapter()
            adapter.fetch(make_source_config(), make_topic())
        assert adapter._last_failed is False

    def test_raw_contains_full_item(self):
        with patch("tracker.adapters.mercari_us.requests.post") as mock_post:
            mock_post.return_value = make_mock_response(FAKE_API_RESPONSE)
            adapter = MercariUSAdapter()
            results = adapter.fetch(make_source_config(), make_topic())
        assert results[0].raw["id"] == "m111"
