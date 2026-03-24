import pytest
import responses as rsps_lib

from tracker.adapters.tmdb import TMDbAdapter
from tracker.models import SourceConfig, TopicConfig

DISCOVER_MOVIE_URL = "https://api.themoviedb.org/3/discover/movie"
DISCOVER_TV_URL = "https://api.themoviedb.org/3/discover/tv"
SEARCH_MULTI_URL = "https://api.themoviedb.org/3/search/multi"

FAKE_MOVIE = {
    "id": 101,
    "title": "The Grand Illusion Reboot",
    "release_date": "2026-06-15",
    "overview": "A sweeping drama about theater people.",
    "media_type": "movie",
}
FAKE_TV = {
    "id": 202,
    "name": "Stage Left",
    "first_air_date": "2026-07-04",
    "overview": "A limited series set backstage on Broadway.",
    "media_type": "tv",
}

FAKE_DISCOVER_MOVIE_RESP = {"results": [FAKE_MOVIE], "total_results": 1}
FAKE_DISCOVER_TV_RESP = {"results": [FAKE_TV], "total_results": 1}
FAKE_SEARCH_RESP = {"results": [FAKE_MOVIE, FAKE_TV, {"media_type": "person", "id": 9}]}


@pytest.fixture(autouse=True)
def set_env(monkeypatch):
    monkeypatch.setenv("TMDB_API_KEY", "test-tmdb-key")


def make_source_config(**kwargs):
    return SourceConfig(source="tmdb", **kwargs)


def make_topic(name="Film & TV"):
    return TopicConfig(
        name=name,
        description="test",
        importance="low",
        urgency="low",
        source_categories=["entertainment"],
        polling={"frequent": [], "discovery": [], "broad": []},
        notifications={"push": False, "email": "weekly_digest", "novelty_push_threshold": 0.7},
        llm_filter={"novelty_threshold": 0.6, "semantic_dedup_threshold": 0.85, "tags": []},
        escalation={"triggers": [], "auto_revert": True},
    )


class TestTMDbAdapterInit:
    def test_source_type_is_entertainment(self):
        assert TMDbAdapter.source_type == "entertainment"

    def test_missing_key_returns_empty_and_sets_last_failed(self, monkeypatch):
        monkeypatch.delenv("TMDB_API_KEY", raising=False)
        adapter = TMDbAdapter()
        results = adapter.fetch(make_source_config(), make_topic())
        assert results == []
        assert adapter._last_failed is True


class TestTMDbDiscover:
    @rsps_lib.activate
    def test_discover_both_fetches_movies_and_tv(self):
        rsps_lib.add(rsps_lib.GET, DISCOVER_MOVIE_URL, json=FAKE_DISCOVER_MOVIE_RESP, status=200)
        rsps_lib.add(rsps_lib.GET, DISCOVER_TV_URL, json=FAKE_DISCOVER_TV_RESP, status=200)

        adapter = TMDbAdapter()
        results = adapter.fetch(make_source_config(), make_topic())

        assert len(results) == 2
        titles = [r.title for r in results]
        assert any("Grand Illusion" in t for t in titles)
        assert any("Stage Left" in t for t in titles)

    @rsps_lib.activate
    def test_discover_movie_only(self):
        rsps_lib.add(rsps_lib.GET, DISCOVER_MOVIE_URL, json=FAKE_DISCOVER_MOVIE_RESP, status=200)

        adapter = TMDbAdapter()
        results = adapter.fetch(make_source_config(filters={"media_type": "movie"}), make_topic())

        assert len(results) == 1
        assert "Grand Illusion" in results[0].title

    @rsps_lib.activate
    def test_discover_tv_only(self):
        rsps_lib.add(rsps_lib.GET, DISCOVER_TV_URL, json=FAKE_DISCOVER_TV_RESP, status=200)

        adapter = TMDbAdapter()
        results = adapter.fetch(make_source_config(filters={"media_type": "tv"}), make_topic())

        assert len(results) == 1
        assert "Stage Left" in results[0].title

    @rsps_lib.activate
    def test_movie_result_fields(self):
        rsps_lib.add(rsps_lib.GET, DISCOVER_MOVIE_URL, json=FAKE_DISCOVER_MOVIE_RESP, status=200)
        rsps_lib.add(rsps_lib.GET, DISCOVER_TV_URL, json={"results": []}, status=200)

        adapter = TMDbAdapter()
        results = adapter.fetch(make_source_config(), make_topic())
        movie = next(r for r in results if "Grand Illusion" in r.title)

        assert movie.url == "https://www.themoviedb.org/movie/101"
        assert "2026-06-15" in movie.title
        assert movie.source == "tmdb"
        assert movie.source_type == "entertainment"
        assert movie.raw["id"] == 101

    @rsps_lib.activate
    def test_tv_result_has_tv_label(self):
        rsps_lib.add(rsps_lib.GET, DISCOVER_MOVIE_URL, json={"results": []}, status=200)
        rsps_lib.add(rsps_lib.GET, DISCOVER_TV_URL, json=FAKE_DISCOVER_TV_RESP, status=200)

        adapter = TMDbAdapter()
        results = adapter.fetch(make_source_config(), make_topic())
        tv = results[0]

        assert "[TV]" in tv.title
        assert tv.url == "https://www.themoviedb.org/tv/202"

    @rsps_lib.activate
    def test_bearer_token_sent_in_header(self):
        rsps_lib.add(rsps_lib.GET, DISCOVER_MOVIE_URL, json=FAKE_DISCOVER_MOVIE_RESP, status=200)
        rsps_lib.add(rsps_lib.GET, DISCOVER_TV_URL, json={"results": []}, status=200)

        adapter = TMDbAdapter()
        adapter.fetch(make_source_config(), make_topic())

        auth = rsps_lib.calls[0].request.headers.get("Authorization", "")
        assert auth == "Bearer test-tmdb-key"

    @rsps_lib.activate
    def test_http_error_returns_empty_and_sets_last_failed(self):
        rsps_lib.add(rsps_lib.GET, DISCOVER_MOVIE_URL, json={"status_message": "Invalid API key"}, status=401)

        adapter = TMDbAdapter()
        results = adapter.fetch(make_source_config(filters={"media_type": "movie"}), make_topic())
        assert results == []
        assert adapter._last_failed is True


class TestTMDbSearch:
    @rsps_lib.activate
    def test_search_mode_filters_person_results(self):
        rsps_lib.add(rsps_lib.GET, SEARCH_MULTI_URL, json=FAKE_SEARCH_RESP, status=200)

        adapter = TMDbAdapter()
        results = adapter.fetch(make_source_config(terms=["theater"]), make_topic())

        # person result should be excluded
        assert len(results) == 2
        media_types = {r.source_type for r in results}
        assert media_types == {"entertainment"}

    @rsps_lib.activate
    def test_search_called_once_per_term(self):
        rsps_lib.add(rsps_lib.GET, SEARCH_MULTI_URL, json={"results": []}, status=200)
        rsps_lib.add(rsps_lib.GET, SEARCH_MULTI_URL, json={"results": []}, status=200)

        adapter = TMDbAdapter()
        adapter.fetch(make_source_config(terms=["Dune", "Wicked"]), make_topic())

        search_calls = [c for c in rsps_lib.calls if SEARCH_MULTI_URL in c.request.url]
        assert len(search_calls) == 2
