from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

from tests.conftest import make_full_topic
from tracker.adapters.email_newsletter import EmailNewsletterAdapter
from tracker.models import SourceConfig

TOPIC = make_full_topic()
SOURCE = SourceConfig(source="email", filters={"senders": ["@wildfang.com"]})


def _make_msg(subject="New drop!", from_="store@wildfang.com", text="Big sale today.", uid="001"):
    msg = MagicMock()
    msg.subject = subject
    msg.from_ = from_
    msg.text = text
    msg.html = None
    msg.uid = uid
    msg.date = datetime(2026, 3, 28, 12, 0, 0, tzinfo=timezone.utc)
    msg.headers = {"message-id": [f"<{uid}@wildfang.com>"]}
    return msg


def _patch_mailbox(msgs):
    """Returns a MailBox mock matching the adapter's usage pattern:
    with MailBox(host).login(user, password) as mailbox: mailbox.fetch(...)
    """
    inner = MagicMock()
    inner.fetch.return_value = iter(msgs)

    login_ctx = MagicMock()
    login_ctx.__enter__ = MagicMock(return_value=inner)
    login_ctx.__exit__ = MagicMock(return_value=False)

    mock_mb = MagicMock()
    mock_mb.login.return_value = login_ctx
    return mock_mb


def test_returns_result_for_matching_sender(monkeypatch):
    monkeypatch.setenv("GMAIL_USER", "test@gmail.com")
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "secret")
    msg = _make_msg()
    with patch("tracker.adapters.email_newsletter.MailBox", return_value=_patch_mailbox([msg])):
        results = EmailNewsletterAdapter().fetch(SOURCE, TOPIC)
    assert len(results) == 1
    assert results[0].title == "New drop!"
    assert results[0].source == "email_newsletter"
    assert results[0].source_type == "feeds"


def test_filters_out_non_matching_sender(monkeypatch):
    monkeypatch.setenv("GMAIL_USER", "test@gmail.com")
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "secret")
    msg = _make_msg(from_="info@someotherbrand.com")
    with patch("tracker.adapters.email_newsletter.MailBox", return_value=_patch_mailbox([msg])):
        results = EmailNewsletterAdapter().fetch(SOURCE, TOPIC)
    assert results == []


def test_no_sender_filter_accepts_all(monkeypatch):
    monkeypatch.setenv("GMAIL_USER", "test@gmail.com")
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "secret")
    source = SourceConfig(source="email", filters={})
    msgs = [_make_msg(uid="1"), _make_msg(from_="other@brand.com", uid="2")]
    with patch("tracker.adapters.email_newsletter.MailBox", return_value=_patch_mailbox(msgs)):
        results = EmailNewsletterAdapter().fetch(source, TOPIC)
    assert len(results) == 2


def test_missing_credentials_returns_empty(monkeypatch):
    monkeypatch.delenv("GMAIL_USER", raising=False)
    monkeypatch.delenv("GMAIL_APP_PASSWORD", raising=False)
    results = EmailNewsletterAdapter().fetch(SOURCE, TOPIC)
    assert results == []


def test_url_uses_message_id(monkeypatch):
    monkeypatch.setenv("GMAIL_USER", "test@gmail.com")
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "secret")
    msg = _make_msg(uid="abc123")
    with patch("tracker.adapters.email_newsletter.MailBox", return_value=_patch_mailbox([msg])):
        results = EmailNewsletterAdapter().fetch(SOURCE, TOPIC)
    assert "abc123@wildfang.com" in results[0].url


def test_published_at_set_from_date(monkeypatch):
    monkeypatch.setenv("GMAIL_USER", "test@gmail.com")
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "secret")
    msg = _make_msg()
    with patch("tracker.adapters.email_newsletter.MailBox", return_value=_patch_mailbox([msg])):
        results = EmailNewsletterAdapter().fetch(SOURCE, TOPIC)
    assert results[0].published_at is not None
    assert results[0].published_at.year == 2026


def test_imap_error_returns_empty(monkeypatch):
    monkeypatch.setenv("GMAIL_USER", "test@gmail.com")
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "secret")
    with patch("tracker.adapters.email_newsletter.MailBox", side_effect=Exception("connection refused")):
        results = EmailNewsletterAdapter().fetch(SOURCE, TOPIC)
    assert results == []
