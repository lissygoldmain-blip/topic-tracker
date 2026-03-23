from datetime import datetime, timezone
from unittest.mock import patch

from tracker.models import Result
from tracker.notifications.email import EmailNotifier


def make_result(title="Test Result", score=0.85, topic="Test Topic"):
    return Result(
        url="https://example.com/1",
        title=title,
        snippet="Test snippet",
        source="google_news",
        source_type="news",
        topic_name=topic,
        fetched_at=datetime.now(timezone.utc),
        novelty_score=score,
        summary="Summary sentence here.",
        tags=["new_listing"],
    )


def test_send_immediate_notification():
    notifier = EmailNotifier(
        api_key="fake",
        from_email="tracker@updates.resend.dev",
        to_email="test@example.com",
    )
    result = make_result()
    with patch("tracker.notifications.email.resend.Emails.send") as mock_send:
        mock_send.return_value = {"id": "123"}
        notifier.send_immediate(result)
        mock_send.assert_called_once()
        call_args = mock_send.call_args[0][0]
        assert call_args["to"] == ["test@example.com"]
        assert "Test Result" in call_args["html"]
        assert "0.85" in call_args["html"]


def test_send_digest_batches_results():
    notifier = EmailNotifier(
        api_key="fake",
        from_email="tracker@updates.resend.dev",
        to_email="test@example.com",
    )
    results = [make_result(title=f"Result {i}") for i in range(3)]
    with patch("tracker.notifications.email.resend.Emails.send") as mock_send:
        mock_send.return_value = {"id": "456"}
        notifier.send_digest(results, subject="Weekly Digest")
        mock_send.assert_called_once()
        call_args = mock_send.call_args[0][0]
        assert "Result 0" in call_args["html"]
        assert "Result 2" in call_args["html"]


def test_send_marks_notified_digest():
    notifier = EmailNotifier(
        api_key="fake",
        from_email="tracker@updates.resend.dev",
        to_email="test@example.com",
    )
    result = make_result()
    with patch("tracker.notifications.email.resend.Emails.send", return_value={"id": "1"}):
        notifier.send_digest([result])
    assert result.notified_digest is True
    assert result.notified_push is False  # email notifier doesn't touch push flag


def test_send_digest_empty_does_nothing():
    notifier = EmailNotifier(
        api_key="fake",
        from_email="tracker@updates.resend.dev",
        to_email="test@example.com",
    )
    with patch("tracker.notifications.email.resend.Emails.send") as mock_send:
        notifier.send_digest([])
        mock_send.assert_not_called()


def test_price_shown_in_email():
    notifier = EmailNotifier(
        api_key="fake",
        from_email="tracker@updates.resend.dev",
        to_email="test@example.com",
    )
    result = make_result()
    result.price = "$245.00 USD"
    with patch("tracker.notifications.email.resend.Emails.send") as mock_send:
        mock_send.return_value = {"id": "789"}
        notifier.send_immediate(result)
        html = mock_send.call_args[0][0]["html"]
        assert "$245.00 USD" in html
