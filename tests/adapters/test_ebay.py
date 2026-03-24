import pytest
import responses as rsps_lib

from tracker.adapters.ebay import EbayAdapter, _token_cache
from tracker.models import SourceConfig, TopicConfig

TOKEN_URL = "https://api.ebay.com/identity/v1/oauth2/token"
SEARCH_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"

FAKE_TOKEN_RESPONSE = {"access_token": "test-token-abc", "expires_in": 7200}
FAKE_SEARCH_RESPONSE = {
    "itemSummaries": [
        {
            "itemId": "v1|123|0",
            "title": "Keiji Kaneko suit 1960s",
            "itemWebUrl": "https://www.ebay.com/itm/123",
            "price": {"value": "450.00", "currency": "USD"},
        },
        {
            "itemId": "v1|456|0",
            "title": "Vintage Japanese suit",
            "itemWebUrl": "https://www.ebay.com/itm/456",
            "price": {"value": "120.00", "currency": "USD"},
        },
    ]
}


@pytest.fixture(autouse=True)
def set_env(monkeypatch):
    monkeypatch.setenv("EBAY_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("EBAY_CLIENT_SECRET", "test-client-secret")


@pytest.fixture(autouse=True)
def clear_token_cache():
    """Clear the module-level token cache between tests."""
    _token_cache.clear()
    yield
    _token_cache.clear()


def make_source_config(**kwargs):
    return SourceConfig(source="ebay", **kwargs)


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


class TestEbayAdapterInit:
    def test_missing_keys_returns_empty_and_sets_last_failed(self, monkeypatch):
        monkeypatch.delenv("EBAY_CLIENT_ID", raising=False)
        monkeypatch.delenv("EBAY_CLIENT_SECRET", raising=False)
        from tests.conftest import make_full_topic
        adapter = EbayAdapter()
        source = SourceConfig(source="ebay", terms=[])
        results = adapter.fetch(source, make_full_topic())
        assert results == []
        assert adapter._last_failed is True

    def test_source_type_is_shopping(self):
        assert EbayAdapter.source_type == "shopping"


class TestEbayFetch:
    @rsps_lib.activate
    def test_successful_fetch_returns_results(self):
        rsps_lib.add(rsps_lib.POST, TOKEN_URL, json=FAKE_TOKEN_RESPONSE, status=200)
        rsps_lib.add(rsps_lib.GET, SEARCH_URL, json=FAKE_SEARCH_RESPONSE, status=200)

        adapter = EbayAdapter()
        results = adapter.fetch(make_source_config(), make_topic())

        assert len(results) == 2
        assert results[0].title == "Keiji Kaneko suit 1960s"
        assert results[0].url == "https://www.ebay.com/itm/123"
        assert results[0].price == "$450.00 USD"
        assert results[0].source == "ebay"
        assert results[0].source_type == "shopping"

    @rsps_lib.activate
    def test_empty_results_when_no_item_summaries(self):
        rsps_lib.add(rsps_lib.POST, TOKEN_URL, json=FAKE_TOKEN_RESPONSE, status=200)
        rsps_lib.add(rsps_lib.GET, SEARCH_URL, json={}, status=200)

        adapter = EbayAdapter()
        results = adapter.fetch(make_source_config(), make_topic())
        assert results == []

    @rsps_lib.activate
    def test_returns_empty_list_on_token_error(self):
        rsps_lib.add(rsps_lib.POST, TOKEN_URL, json={"error": "invalid_client"}, status=401)

        adapter = EbayAdapter()
        results = adapter.fetch(make_source_config(), make_topic())
        assert results == []
        assert adapter._last_failed is True

    @rsps_lib.activate
    def test_returns_empty_list_on_search_http_error(self):
        rsps_lib.add(rsps_lib.POST, TOKEN_URL, json=FAKE_TOKEN_RESPONSE, status=200)
        rsps_lib.add(rsps_lib.GET, SEARCH_URL, json={"errors": [{}]}, status=500)

        adapter = EbayAdapter()
        results = adapter.fetch(make_source_config(), make_topic())
        assert results == []
        assert adapter._last_failed is True

    @rsps_lib.activate
    def test_price_filter_sent_in_params(self):
        rsps_lib.add(rsps_lib.POST, TOKEN_URL, json=FAKE_TOKEN_RESPONSE, status=200)
        rsps_lib.add(rsps_lib.GET, SEARCH_URL, json=FAKE_SEARCH_RESPONSE, status=200)

        adapter = EbayAdapter()
        source = make_source_config(filters={"price_max": 500})
        adapter.fetch(source, make_topic())

        search_call = rsps_lib.calls[1]
        assert "price" in search_call.request.url

    @rsps_lib.activate
    def test_token_is_cached_across_calls(self):
        rsps_lib.add(rsps_lib.POST, TOKEN_URL, json=FAKE_TOKEN_RESPONSE, status=200)
        rsps_lib.add(rsps_lib.GET, SEARCH_URL, json=FAKE_SEARCH_RESPONSE, status=200)
        rsps_lib.add(rsps_lib.GET, SEARCH_URL, json=FAKE_SEARCH_RESPONSE, status=200)

        adapter = EbayAdapter()
        adapter.fetch(make_source_config(), make_topic())
        adapter.fetch(make_source_config(), make_topic())

        token_calls = [c for c in rsps_lib.calls if TOKEN_URL in c.request.url]
        assert len(token_calls) == 1  # token fetched only once

    @rsps_lib.activate
    def test_result_raw_contains_full_item(self):
        rsps_lib.add(rsps_lib.POST, TOKEN_URL, json=FAKE_TOKEN_RESPONSE, status=200)
        rsps_lib.add(rsps_lib.GET, SEARCH_URL, json=FAKE_SEARCH_RESPONSE, status=200)

        adapter = EbayAdapter()
        results = adapter.fetch(make_source_config(), make_topic())
        assert results[0].raw["itemId"] == "v1|123|0"

    @rsps_lib.activate
    def test_item_without_price_field_maps_price_to_none(self):
        response = {
            "itemSummaries": [
                {
                    "itemId": "v1|789|0",
                    "title": "No Price Item",
                    "itemWebUrl": "https://ebay.com/itm/789",
                }
            ]
        }
        rsps_lib.add(rsps_lib.POST, TOKEN_URL, json=FAKE_TOKEN_RESPONSE, status=200)
        rsps_lib.add(rsps_lib.GET, SEARCH_URL, json=response, status=200)

        adapter = EbayAdapter()
        results = adapter.fetch(make_source_config(), make_topic())
        assert results[0].price is None

    @rsps_lib.activate
    def test_last_failed_false_on_success(self):
        rsps_lib.add(rsps_lib.POST, TOKEN_URL, json=FAKE_TOKEN_RESPONSE, status=200)
        rsps_lib.add(rsps_lib.GET, SEARCH_URL, json=FAKE_SEARCH_RESPONSE, status=200)

        adapter = EbayAdapter()
        adapter.fetch(make_source_config(), make_topic())
        assert adapter._last_failed is False
