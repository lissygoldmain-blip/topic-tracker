from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from tracker.models import Result

PRUNE_DAYS = {
    "news": 90,
    "social": 90,
    "shopping": 365,
    "video": 90,
    "feeds": 90,
    "weather": 7,
    "science": 365,
    "jobs": 30,
}
INDEX_MAX = 100


class Storage:
    def __init__(self, data_dir: str = "."):
        self._dir = Path(data_dir)
        self._seen: dict[str, dict] = {}
        self._index: dict[str, list[dict]] = {}
        self._state: dict = {}

    def _seen_path(self) -> Path:
        return self._dir / "seen_urls.json"

    def _index_path(self) -> Path:
        return self._dir / "results" / "index.json"

    def _state_path(self) -> Path:
        return self._dir / "state.json"

    def _archive_path(self) -> Path:
        month = datetime.now(timezone.utc).strftime("%Y-%m")
        return self._dir / "results" / "archive" / f"{month}.ndjson"

    def load(self) -> None:
        if self._seen_path().exists():
            self._seen = json.loads(self._seen_path().read_text())
        if self._index_path().exists():
            self._index = json.loads(self._index_path().read_text())
        if self._state_path().exists():
            self._state = json.loads(self._state_path().read_text())

    def save(self) -> None:
        self._seen_path().write_text(json.dumps(self._seen, indent=2))
        self._index_path().parent.mkdir(parents=True, exist_ok=True)
        self._index_path().write_text(json.dumps(self._index, indent=2))
        self._state_path().write_text(json.dumps(self._state, indent=2))

    def load_state(self) -> dict:
        return self._state

    def save_state(self, state: dict) -> None:
        self._state = state

    def prune(self) -> None:
        now = datetime.now(timezone.utc)
        to_delete = []
        for url, meta in self._seen.items():
            source_type = meta.get("source_type", "news")
            max_days = PRUNE_DAYS.get(source_type, 90)
            seen_at = datetime.fromisoformat(meta["seen_at"])
            if (now - seen_at).days > max_days:
                to_delete.append(url)
        for url in to_delete:
            del self._seen[url]

    def is_seen(self, url: str) -> bool:
        return url in self._seen

    def mark_seen(self, url: str, source_type: str = "news") -> None:
        self._seen[url] = {
            "seen_at": datetime.now(timezone.utc).isoformat(),
            "source_type": source_type,
        }

    def add_result(self, result: Result) -> None:
        topic = result.topic_name
        if topic not in self._index:
            self._index[topic] = []
        self._index[topic].insert(0, result.to_dict())
        self._index[topic] = self._index[topic][:INDEX_MAX]
        # Append to NDJSON archive
        self._archive_path().parent.mkdir(parents=True, exist_ok=True)
        with open(self._archive_path(), "a") as f:
            f.write(json.dumps(result.to_dict()) + "\n")

    def get_index(self) -> dict[str, list[dict]]:
        return self._index
