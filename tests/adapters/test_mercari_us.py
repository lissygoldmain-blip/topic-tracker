from unittest.mock import MagicMock, patch

from tracker.adapters.mercari_us import MercariUSAdapter
from tracker.models import SourceConfig, TopicConfig


def make_fake_item(item_id="m111", name="Keiji Kaneko Suit Jacket", price=350.0):
    """Create a mock mercari Item object with the real library's attribute interface."""
    item = MagicMock()
    item.id = item_id
    item.productName = name
    item.productURL = f"https://jp.mercari.com/item/{item_id}"
    item.price = price
    item.status = "ITEM_STATUS_ON_SALE"
    item.soldOut = False
    return item


FAKE_ITEMS = [
    make_fake_item("m111", "Keiji Kaneko Suit Jacket", 350.0),
    make_fake_item("m222", "1960s Japanese Suit", 200.0),
]


def make_source_config():
    return SourceConfig(source="mercari")


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
        with patch("tracker.adapters.mercari_us.mercari_lib.search") as mock_search:
            mock_search.return_value = iter(FAKE_ITEMS)

            adapter = MercariUSAdapter()
            results = adapter.fetch(make_source_config(), make_topic())

        assert len(results) == 2
        assert results[0].title == "Keiji Kaneko Suit Jacket"
        assert results[0].url == "https://jp.mercari.com/item/m111"
        assert results[0].price == "$350.00"
        assert results[0].source == "mercari"
        assert results[0].source_type == "shopping"

    def test_search_called_with_topic_name(self):
        with patch("tracker.adapters.mercari_us.mercari_lib.search") as mock_search:
            mock_search.return_value = iter([])

            adapter = MercariUSAdapter()
            adapter.fetch(make_source_config(), make_topic("My Topic"))

            mock_search.assert_called_once_with("My Topic")

    def test_empty_result_returns_empty(self):
        with patch("tracker.adapters.mercari_us.mercari_lib.search") as mock_search:
            mock_search.return_value = iter([])

            adapter = MercariUSAdapter()
            results = adapter.fetch(make_source_config(), make_topic())
        assert results == []

    def test_returns_empty_list_on_exception(self):
        with patch("tracker.adapters.mercari_us.mercari_lib.search") as mock_search:
            mock_search.side_effect = Exception("timeout")

            adapter = MercariUSAdapter()
            results = adapter.fetch(make_source_config(), make_topic())
        assert results == []
        assert adapter._last_failed is True

    def test_item_without_price_maps_to_none(self):
        item_no_price = make_fake_item("m333", "No Price Item", None)
        with patch("tracker.adapters.mercari_us.mercari_lib.search") as mock_search:
            mock_search.return_value = iter([item_no_price])

            adapter = MercariUSAdapter()
            results = adapter.fetch(make_source_config(), make_topic())
        assert results[0].price is None

    def test_last_failed_false_on_success(self):
        with patch("tracker.adapters.mercari_us.mercari_lib.search") as mock_search:
            mock_search.return_value = iter(FAKE_ITEMS)

            adapter = MercariUSAdapter()
            adapter.fetch(make_source_config(), make_topic())
        assert adapter._last_failed is False
