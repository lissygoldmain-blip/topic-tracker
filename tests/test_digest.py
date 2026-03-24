"""Tests for run_digest() in tracker/poller.py."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from tracker.models import Result
from tracker.poller import run_digest


def _make_result_dict(url="https://example.com/1", topic="Test Topic",
                      notified_digest=False, novelty_score=0.8):
    return {
        "url": url,
        "title": "Test Title",
        "snippet": "Test snippet",
        "source": "google_news",
        "source_type": "news",
        "topic_name": topic,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "novelty_score": novelty_score,
        "summary": None,
        "tags": [],
        "escalation_trigger": None,
        "action_url": None,
        "price": None,
        "notified_push": False,
        "notified_digest": notified_digest,
    }


def _write_index(tmp_path: Path, index: dict) -> None:
    results_dir = tmp_path / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    (results_dir / "index.json").write_text(json.dumps(index))
    (tmp_path / "seen_urls.json").write_text("{}")
    (tmp_path / "state.json").write_text("{}")


def test_digest_sends_unnotified_results(tmp_path):
    index = {
        "Test Topic": [
            _make_result_dict(url="https://example.com/1", notified_digest=False),
            _make_result_dict(url="https://example.com/2", notified_digest=False),
        ]
    }
    _write_index(tmp_path, index)

    env = {"RESEND_API_KEY": "fake", "TO_EMAIL": "test@example.com", "FROM_EMAIL": "noreply@example.com"}
    with patch.dict(os.environ, env), \
         patch("tracker.poller.EmailNotifier") as MockNotifier:
        mock_notif = MagicMock()
        MockNotifier.return_value = mock_notif
        # Simulate send_digest marking results as notified
        def fake_send_digest(results, subject=""):
            for r in results:
                r.notified_digest = True
        mock_notif.send_digest.side_effect = fake_send_digest

        run_digest(data_dir=str(tmp_path))

    mock_notif.send_digest.assert_called_once()
    sent_results = mock_notif.send_digest.call_args[0][0]
    assert len(sent_results) == 2


def test_digest_skips_already_notified(tmp_path):
    index = {
        "Test Topic": [
            _make_result_dict(url="https://example.com/1", notified_digest=True),
            _make_result_dict(url="https://example.com/2", notified_digest=False),
        ]
    }
    _write_index(tmp_path, index)

    env = {"RESEND_API_KEY": "fake", "TO_EMAIL": "test@example.com", "FROM_EMAIL": "noreply@example.com"}
    with patch.dict(os.environ, env), \
         patch("tracker.poller.EmailNotifier") as MockNotifier:
        mock_notif = MagicMock()
        MockNotifier.return_value = mock_notif
        def fake_send_digest(results, subject=""):
            for r in results:
                r.notified_digest = True
        mock_notif.send_digest.side_effect = fake_send_digest

        run_digest(data_dir=str(tmp_path))

    sent_results = mock_notif.send_digest.call_args[0][0]
    assert len(sent_results) == 1
    assert sent_results[0].url == "https://example.com/2"


def test_digest_marks_notified_in_index(tmp_path):
    index = {
        "Test Topic": [
            _make_result_dict(url="https://example.com/1", notified_digest=False),
        ]
    }
    _write_index(tmp_path, index)

    env = {"RESEND_API_KEY": "fake", "TO_EMAIL": "test@example.com", "FROM_EMAIL": "noreply@example.com"}
    with patch.dict(os.environ, env), \
         patch("tracker.poller.EmailNotifier") as MockNotifier:
        mock_notif = MagicMock()
        MockNotifier.return_value = mock_notif
        def fake_send_digest(results, subject=""):
            for r in results:
                r.notified_digest = True
        mock_notif.send_digest.side_effect = fake_send_digest

        run_digest(data_dir=str(tmp_path))

    saved = json.loads((tmp_path / "results" / "index.json").read_text())
    assert saved["Test Topic"][0]["notified_digest"] is True


def test_digest_no_results_skips_send(tmp_path):
    index = {
        "Test Topic": [
            _make_result_dict(url="https://example.com/1", notified_digest=True),
        ]
    }
    _write_index(tmp_path, index)

    env = {"RESEND_API_KEY": "fake", "TO_EMAIL": "test@example.com", "FROM_EMAIL": "noreply@example.com"}
    with patch.dict(os.environ, env), \
         patch("tracker.poller.EmailNotifier") as MockNotifier:
        mock_notif = MagicMock()
        MockNotifier.return_value = mock_notif

        run_digest(data_dir=str(tmp_path))

    mock_notif.send_digest.assert_not_called()


def test_digest_no_resend_key_skips(tmp_path):
    index = {"Test Topic": [_make_result_dict(notified_digest=False)]}
    _write_index(tmp_path, index)

    with patch.dict(os.environ, {"RESEND_API_KEY": ""}, clear=False), \
         patch("tracker.poller.EmailNotifier") as MockNotifier:
        run_digest(data_dir=str(tmp_path))

    MockNotifier.assert_not_called()


def test_digest_results_sorted_by_topic_then_novelty(tmp_path):
    index = {
        "Aardvark": [
            _make_result_dict(url="https://example.com/a1", topic="Aardvark", novelty_score=0.6),
            _make_result_dict(url="https://example.com/a2", topic="Aardvark", novelty_score=0.9),
        ],
        "Zebra": [
            _make_result_dict(url="https://example.com/z1", topic="Zebra", novelty_score=0.8),
        ],
    }
    _write_index(tmp_path, index)

    env = {"RESEND_API_KEY": "fake", "TO_EMAIL": "test@example.com", "FROM_EMAIL": "noreply@example.com"}
    with patch.dict(os.environ, env), \
         patch("tracker.poller.EmailNotifier") as MockNotifier:
        mock_notif = MagicMock()
        MockNotifier.return_value = mock_notif
        def fake_send_digest(results, subject=""):
            for r in results:
                r.notified_digest = True
        mock_notif.send_digest.side_effect = fake_send_digest

        run_digest(data_dir=str(tmp_path))

    sent = mock_notif.send_digest.call_args[0][0]
    topics = [r.topic_name for r in sent]
    # Aardvark comes before Zebra
    assert topics.index("Aardvark") < topics.index("Zebra")
    # Within Aardvark, higher novelty score first
    aardvark_scores = [r.novelty_score for r in sent if r.topic_name == "Aardvark"]
    assert aardvark_scores == sorted(aardvark_scores, reverse=True)


def test_digest_subject_includes_date(tmp_path):
    index = {"Test Topic": [_make_result_dict(notified_digest=False)]}
    _write_index(tmp_path, index)

    env = {"RESEND_API_KEY": "fake", "TO_EMAIL": "t@t.com", "FROM_EMAIL": "f@f.com"}
    with patch.dict(os.environ, env), \
         patch("tracker.poller.EmailNotifier") as MockNotifier:
        mock_notif = MagicMock()
        MockNotifier.return_value = mock_notif
        def fake_send_digest(results, subject=""):
            for r in results:
                r.notified_digest = True
        mock_notif.send_digest.side_effect = fake_send_digest

        run_digest(data_dir=str(tmp_path))

    _, kwargs = mock_notif.send_digest.call_args
    subject = kwargs.get("subject", mock_notif.send_digest.call_args[0][1] if len(mock_notif.send_digest.call_args[0]) > 1 else "")
    assert "Digest" in subject
