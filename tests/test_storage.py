from datetime import datetime, timedelta, timezone

from tracker.models import Result
from tracker.storage import Storage


def make_result(url="https://example.com/1", source_type="news", days_old=0):
    return Result(
        url=url,
        title="Test",
        snippet="snippet",
        source="google_news",
        source_type=source_type,
        topic_name="Test Topic",
        fetched_at=datetime.now(timezone.utc) - timedelta(days=days_old),
        novelty_score=0.8,
        tags=["noise"],
    )


def test_seen_url_roundtrip(tmp_path):
    s = Storage(data_dir=str(tmp_path))
    s.load()
    assert not s.is_seen("https://example.com")
    s.mark_seen("https://example.com", source_type="news")
    assert s.is_seen("https://example.com")


def test_prune_old_news_urls(tmp_path):
    s = Storage(data_dir=str(tmp_path))
    s.load()
    s.mark_seen("https://old.com", source_type="news")
    # Manually age the entry
    s._seen["https://old.com"]["seen_at"] = (
        datetime.now(timezone.utc) - timedelta(days=91)
    ).isoformat()
    s.prune()
    assert not s.is_seen("https://old.com")


def test_prune_keeps_fresh_shopping_urls(tmp_path):
    s = Storage(data_dir=str(tmp_path))
    s.load()
    s.mark_seen("https://ebay.com/itm/1", source_type="shopping")
    s._seen["https://ebay.com/itm/1"]["seen_at"] = (
        datetime.now(timezone.utc) - timedelta(days=200)
    ).isoformat()
    s.prune()
    # 200 days < 365-day shopping window — should survive
    assert s.is_seen("https://ebay.com/itm/1")


def test_add_and_retrieve_results(tmp_path):
    s = Storage(data_dir=str(tmp_path))
    s.load()
    r = make_result()
    s.add_result(r)
    index = s.get_index()
    assert "Test Topic" in index
    assert index["Test Topic"][0]["url"] == "https://example.com/1"


def test_index_capped_at_100(tmp_path):
    s = Storage(data_dir=str(tmp_path))
    s.load()
    for i in range(110):
        s.add_result(make_result(url=f"https://example.com/{i}"))
    index = s.get_index()
    assert len(index["Test Topic"]) == 100


def test_save_and_load_persists(tmp_path):
    s = Storage(data_dir=str(tmp_path))
    s.load()
    s.mark_seen("https://persist.com", source_type="news")
    s.save()
    s2 = Storage(data_dir=str(tmp_path))
    s2.load()
    assert s2.is_seen("https://persist.com")


def test_state_roundtrip(tmp_path):
    s = Storage(data_dir=str(tmp_path))
    s.load()
    state = {
        "circuit_breakers": {
            "My Topic": {"grailed": {"consecutive_failures": 2, "disabled": False}}
        }
    }
    s.save_state(state)
    s.save()
    s2 = Storage(data_dir=str(tmp_path))
    s2.load()
    loaded = s2.load_state()
    assert loaded["circuit_breakers"]["My Topic"]["grailed"]["consecutive_failures"] == 2
