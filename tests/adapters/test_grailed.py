from unittest.mock import MagicMock, patch

from tracker.adapters.grailed import GrailedAdapter
from tracker.models import SourceConfig, TopicConfig

FAKE_RESULTS = [
    {
        "id": 101,
        "title": "Keiji Kaneko Suit 1960s",
        "price": 450,
        "slug": None,
        "designer_names": ["Keiji Kaneko"],
    },
    {
        "id": 202,
        "title": "Japanese Vintage Blazer",
        "price": 120,
        "slug": None,
        "designer_names": [],
    },
]


def make_source_config():
    return SourceConfig(source="grailed")


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


class TestGrailedAdapterMeta:
    def test_source_type_is_shopping(self):
        assert GrailedAdapter.source_type == "shopping"


class TestGrailedFetch:
    def test_successful_fetch_returns_results(self):
        with patch("tracker.adapters.grailed.GrailedAPIClient") as MockClient:
            mock_client = MagicMock()
            mock_client.find_products.return_value = FAKE_RESULTS
            MockClient.return_value = mock_client

            adapter = GrailedAdapter()
            results = adapter.fetch(make_source_config(), make_topic())

        assert len(results) == 2
        assert results[0].title == "Keiji Kaneko Suit 1960s"
        assert results[0].url == "https://www.grailed.com/listings/101"
        assert results[0].price == "$450.00"
        assert results[0].source == "grailed"
        assert results[0].source_type == "shopping"

    def test_find_products_called_with_topic_name_and_limit(self):
        with patch("tracker.adapters.grailed.GrailedAPIClient") as MockClient:
            mock_client = MagicMock()
            mock_client.find_products.return_value = FAKE_RESULTS
            MockClient.return_value = mock_client

            adapter = GrailedAdapter()
            adapter.fetch(make_source_config(), make_topic("My Topic"))

            mock_client.find_products.assert_called_once_with(
                query_search="My Topic", hits_per_page=20, sold=False
            )

    def test_empty_list_from_library_returns_empty(self):
        with patch("tracker.adapters.grailed.GrailedAPIClient") as MockClient:
            mock_client = MagicMock()
            mock_client.find_products.return_value = []
            MockClient.return_value = mock_client

            adapter = GrailedAdapter()
            results = adapter.fetch(make_source_config(), make_topic())
        assert results == []

    def test_returns_empty_list_on_exception(self):
        with patch("tracker.adapters.grailed.GrailedAPIClient") as MockClient:
            mock_client = MagicMock()
            mock_client.find_products.side_effect = Exception("network error")
            MockClient.return_value = mock_client

            adapter = GrailedAdapter()
            results = adapter.fetch(make_source_config(), make_topic())
        assert results == []
        assert adapter._last_failed is True

    def test_item_without_price_maps_to_none(self):
        item_no_price = {"id": 303, "title": "No Price", "slug": None, "designer_names": []}
        with patch("tracker.adapters.grailed.GrailedAPIClient") as MockClient:
            mock_client = MagicMock()
            mock_client.find_products.return_value = [item_no_price]
            MockClient.return_value = mock_client

            adapter = GrailedAdapter()
            results = adapter.fetch(make_source_config(), make_topic())
        assert results[0].price is None

    def test_result_raw_contains_full_item(self):
        with patch("tracker.adapters.grailed.GrailedAPIClient") as MockClient:
            mock_client = MagicMock()
            mock_client.find_products.return_value = FAKE_RESULTS
            MockClient.return_value = mock_client

            adapter = GrailedAdapter()
            results = adapter.fetch(make_source_config(), make_topic())
        assert results[0].raw["id"] == 101

    def test_last_failed_false_on_success(self):
        with patch("tracker.adapters.grailed.GrailedAPIClient") as MockClient:
            mock_client = MagicMock()
            mock_client.find_products.return_value = FAKE_RESULTS
            MockClient.return_value = mock_client

            adapter = GrailedAdapter()
            adapter.fetch(make_source_config(), make_topic())
        assert adapter._last_failed is False
