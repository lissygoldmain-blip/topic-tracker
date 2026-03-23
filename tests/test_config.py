import textwrap

import pytest

from tracker.config import ConfigError, load_topics

VALID_YAML = textwrap.dedent("""
    topics:
      - name: "Test Topic"
        description: "A test topic"
        importance: high
        urgency: medium
        source_categories: [news]
        polling:
          frequent:
            - source: google_news
              terms: ["test query"]
          discovery: []
          broad: []
        notifications:
          push: true
          email: weekly_digest
          novelty_push_threshold: 0.7
        llm_filter:
          novelty_threshold: 0.65
          semantic_dedup_threshold: 0.85
          tags: [new_listing, noise]
        escalation:
          triggers: []
          auto_revert: true
""")


def test_load_valid_yaml(tmp_path):
    f = tmp_path / "topics.yaml"
    f.write_text(VALID_YAML)
    topics = load_topics(str(f))
    assert len(topics) == 1
    assert topics[0].name == "Test Topic"
    assert topics[0].urgency == "medium"
    assert topics[0].importance == "high"


def test_load_sources_for_tier(tmp_path):
    f = tmp_path / "topics.yaml"
    f.write_text(VALID_YAML)
    topics = load_topics(str(f))
    sources = topics[0].sources_for_tier("frequent")
    assert len(sources) == 1
    assert sources[0].source == "google_news"
    assert "test query" in sources[0].terms


def test_invalid_importance_raises(tmp_path):
    bad = VALID_YAML.replace("importance: high", "importance: critical")
    f = tmp_path / "topics.yaml"
    f.write_text(bad)
    with pytest.raises(ConfigError):
        load_topics(str(f))


def test_invalid_urgency_raises(tmp_path):
    bad = VALID_YAML.replace("urgency: medium", "urgency: sorta")
    f = tmp_path / "topics.yaml"
    f.write_text(bad)
    with pytest.raises(ConfigError):
        load_topics(str(f))
