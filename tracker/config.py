import yaml

from tracker.models import TopicConfig

VALID_IMPORTANCE = {"high", "low"}
VALID_URGENCY = {"urgent", "high", "medium", "low"}


class ConfigError(Exception):
    pass


def load_topics(path: str = "topics.yaml") -> list[TopicConfig]:
    with open(path) as f:
        data = yaml.safe_load(f)

    topics = []
    for raw in data.get("topics", []):
        name = raw.get("name", "<unnamed>")
        importance = raw.get("importance")
        urgency = raw.get("urgency")

        if importance not in VALID_IMPORTANCE:
            raise ConfigError(
                f"Topic '{name}': invalid importance '{importance}'."
                f" Must be one of {VALID_IMPORTANCE}"
            )
        if urgency not in VALID_URGENCY:
            raise ConfigError(
                f"Topic '{name}': invalid urgency '{urgency}'. Must be one of {VALID_URGENCY}"
            )

        topics.append(
            TopicConfig(
                name=name,
                description=raw.get("description", ""),
                importance=importance,
                urgency=urgency,
                source_categories=raw.get("source_categories", []),
                polling=raw.get("polling", {"frequent": [], "discovery": [], "broad": []}),
                notifications=raw.get("notifications", {}),
                llm_filter=raw.get("llm_filter", {}),
                escalation=raw.get("escalation", {"triggers": [], "auto_revert": True}),
            )
        )
    return topics
