import pytest
import responses as rsps_lib

from tracker.adapters.etsy import EtsyAdapter
from tracker.models import SourceConfig, TopicConfig

SEARCH_URL = "https://openapi.etsy.com/v3/application/listings/active"

FAKE_RESPONSE = {
    "results": [
        {
            "listing_id": 111,
            "title": "Keiji Kaneko era suit",
            "url": "https://www.etsy.com/listing/111/keiji",
            "price": {"amount": 4500, "divisor": 100, "currency_code": "USD"},
        },
        {
            "listing_id": 222,
            "title": "Japanese vintage suit",
            "url": "https://www.etsy.com/listing/222/japanese",
            "price": {"amount": 8000, "divisor": 100, "currency_code": "USD"},
        },
    ]
}


@pytest.fixture(autouse=True)
def set_env(monkeypatch):
    monkeypatch.setenv("ETSY_API_KEY", "test-etsy-key-xyz")


def make_source_config(**kwargs):
    return SourceConfig(source="etsy", **kwargs)


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


class TestEtsyAdapterInit:
    def test_raises_if_api_key_missing(self, monkeypatch):
        monkeypatch.delenv("ETSY_API_KEY")
        with pytest.raises(EnvironmentError, match="ETSY_API_KEY"):
            EtsyAdapter()

    def test_source_type_is_shopping(self):
        assert EtsyAdapter.source_type == "shopping"


class TestEtsyFetch:
    @rsps_lib.activate
    def test_successful_fetch_returns_results(self):
        rsps_lib.add(rsps_lib.GET, SEARCH_URL, json=FAKE_RESPONSE, status=200)

        adapter = EtsyAdapter()
        results = adapter.fetch(make_source_config(), make_topic())

        assert len(results) == 2
        assert results[0].title == "Keiji Kaneko era suit"
        assert results[0].url == "https://www.etsy.com/listing/111/keiji"
        assert results[0].price == "$45.00 USD"
        assert results[0].source == "etsy"
        assert results[0].source_type == "shopping"

    @rsps_lib.activate
    def test_empty_results_key_returns_empty_list(self):
        rsps_lib.add(rsps_lib.GET, SEARCH_URL, json={"results": []}, status=200)

        adapter = EtsyAdapter()
        results = adapter.fetch(make_source_config(), make_topic())
        assert results == []

    @rsps_lib.activate
    def test_missing_results_key_returns_empty_list(self):
        rsps_lib.add(rsps_lib.GET, SEARCH_URL, json={}, status=200)

        adapter = EtsyAdapter()
        results = adapter.fetch(make_source_config(), make_topic())
        assert results == []

    @rsps_lib.activate
    def test_returns_empty_list_on_http_error(self):
        rsps_lib.add(rsps_lib.GET, SEARCH_URL, json={"error": "Forbidden"}, status=403)

        adapter = EtsyAdapter()
        results = adapter.fetch(make_source_config(), make_topic())
        assert results == []
        assert adapter._last_failed is True

    @rsps_lib.activate
    def test_api_key_sent_in_header(self):
        rsps_lib.add(rsps_lib.GET, SEARCH_URL, json=FAKE_RESPONSE, status=200)

        adapter = EtsyAdapter()
        adapter.fetch(make_source_config(), make_topic())

        request = rsps_lib.calls[0].request
        assert request.headers.get("x-api-key") == "test-etsy-key-xyz"

    @rsps_lib.activate
    def test_keywords_param_is_topic_name(self):
        rsps_lib.add(rsps_lib.GET, SEARCH_URL, json=FAKE_RESPONSE, status=200)

        adapter = EtsyAdapter()
        adapter.fetch(make_source_config(), make_topic("My Search Term"))

        request = rsps_lib.calls[0].request
        assert (
            "My+Search+Term" in request.url
            or "My%20Search%20Term" in request.url
            or "keywords=My+Search+Term" in request.url
        )

    @rsps_lib.activate
    def test_item_without_price_maps_to_none(self):
        response = {
            "results": [
                {
                    "listing_id": 333,
                    "title": "No price listing",
                    "url": "https://etsy.com/listing/333/x",
                }
            ]
        }
        rsps_lib.add(rsps_lib.GET, SEARCH_URL, json=response, status=200)

        adapter = EtsyAdapter()
        results = adapter.fetch(make_source_config(), make_topic())
        assert results[0].price is None

    @rsps_lib.activate
    def test_result_raw_contains_full_item(self):
        rsps_lib.add(rsps_lib.GET, SEARCH_URL, json=FAKE_RESPONSE, status=200)

        adapter = EtsyAdapter()
        results = adapter.fetch(make_source_config(), make_topic())
        assert results[0].raw["listing_id"] == 111
