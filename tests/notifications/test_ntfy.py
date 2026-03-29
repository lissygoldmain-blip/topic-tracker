from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

from tracker.notifications.ntfy import NtfyNotifier
from tracker.models import Result


def _make_result(**kwargs):
    defaults = dict(
        url="https://example.com/article",
        title="ICE activity spotted in Jackson Heights",
        snippet="Reports of enforcement activity near Roosevelt Ave",
        source="google_news",
        source_type="news",
        topic_name="Immigration & ICE",
        fetched_at=datetime.now(timezone.utc),
        novelty_score=0.9,
        escalation_trigger=None,
    )
    defaults.update(kwargs)
    return Result(**defaults)


def _ok_response():
    resp = MagicMock()
    resp.ok = True
    resp.status_code = 200
    return resp


def test_sends_post_to_ntfy(monkeypatch):
    notifier = NtfyNotifier("lissy-tracker-test")
    result = _make_result(escalation_trigger="confirmed_activity")
    with patch("tracker.notifications.ntfy.requests.post", return_value=_ok_response()) as mock_post:
        notifier.send(result, urgency="urgent")
    mock_post.assert_called_once()
    call_kwargs = mock_post.call_args
    assert "ntfy.sh/lissy-tracker-test" in call_kwargs[0][0]


def test_escalation_uses_rotating_light_tag():
    notifier = NtfyNotifier("lissy-tracker-test")
    result = _make_result(escalation_trigger="confirmed_activity")
    with patch("tracker.notifications.ntfy.requests.post", return_value=_ok_response()) as mock_post:
        notifier.send(result)
    headers = mock_post.call_args[1]["headers"]
    assert headers["Tags"] == "rotating_light"


def test_urgent_priority_is_5():
    notifier = NtfyNotifier("lissy-tracker-test")
    result = _make_result()
    with patch("tracker.notifications.ntfy.requests.post", return_value=_ok_response()) as mock_post:
        notifier.send(result, urgency="urgent")
    headers = mock_post.call_args[1]["headers"]
    assert headers["Priority"] == "5"


def test_high_priority_is_4():
    notifier = NtfyNotifier("lissy-tracker-test")
    result = _make_result()
    with patch("tracker.notifications.ntfy.requests.post", return_value=_ok_response()) as mock_post:
        notifier.send(result, urgency="high")
    headers = mock_post.call_args[1]["headers"]
    assert headers["Priority"] == "4"


def test_click_header_is_result_url():
    notifier = NtfyNotifier("lissy-tracker-test")
    result = _make_result()
    with patch("tracker.notifications.ntfy.requests.post", return_value=_ok_response()) as mock_post:
        notifier.send(result)
    headers = mock_post.call_args[1]["headers"]
    assert headers["Click"] == "https://example.com/article"


def test_marks_notified_push_on_success():
    notifier = NtfyNotifier("lissy-tracker-test")
    result = _make_result()
    assert result.notified_push is False
    with patch("tracker.notifications.ntfy.requests.post", return_value=_ok_response()):
        notifier.send(result)
    assert result.notified_push is True


def test_does_not_mark_notified_on_http_error():
    notifier = NtfyNotifier("lissy-tracker-test")
    result = _make_result()
    bad_resp = MagicMock()
    bad_resp.ok = False
    bad_resp.status_code = 429
    with patch("tracker.notifications.ntfy.requests.post", return_value=bad_resp):
        notifier.send(result)
    assert result.notified_push is False


def test_network_error_does_not_raise():
    notifier = NtfyNotifier("lissy-tracker-test")
    result = _make_result()
    with patch("tracker.notifications.ntfy.requests.post", side_effect=Exception("timeout")):
        notifier.send(result)  # should not raise
    assert result.notified_push is False
