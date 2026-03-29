from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from imap_tools import MailBox, AND

from tracker.adapters.base import BaseAdapter
from tracker.models import Result, SourceConfig, TopicConfig

logger = logging.getLogger(__name__)

# Strip HTML tags for a plain-text snippet
_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(text: str) -> str:
    return _TAG_RE.sub(" ", text).strip()


class EmailNewsletterAdapter(BaseAdapter):
    """
    Reads unread emails from a dedicated Gmail inbox (IMAP + App Password).

    Required env vars:
      GMAIL_USER         — the Gmail address used for newsletter subscriptions
      GMAIL_APP_PASSWORD — a Google App Password (not the account password)

    source_config.filters supports:
      senders: [list of sender addresses or domains to match]
        e.g. ["@wildfang.com", "news@someband.com"]
      max_emails: int (default 20)
    """

    source_type = "feeds"
    IMAP_HOST = "imap.gmail.com"

    def fetch(self, source_config: SourceConfig, topic: TopicConfig) -> list[Result]:
        user = os.environ.get("GMAIL_USER", "")
        password = os.environ.get("GMAIL_APP_PASSWORD", "")
        if not user or not password:
            logger.warning("EmailNewsletterAdapter: GMAIL_USER or GMAIL_APP_PASSWORD not set")
            self._last_failed = True
            return []

        senders: list[str] = source_config.filters.get("senders", [])
        max_emails: int = source_config.filters.get("max_emails", 20)

        results = []
        try:
            with MailBox(self.IMAP_HOST).login(user, password) as mailbox:
                # Fetch unseen emails only — imap-tools marks them seen on fetch
                # when mark_seen=True (default). We rely on this for deduplication
                # instead of maintaining a separate seen-IDs file.
                msgs = list(mailbox.fetch(AND(seen=False), mark_seen=True, limit=max_emails))

            for msg in msgs:
                from_addr = msg.from_ or ""
                # If senders filter is set, skip emails not matching any entry
                if senders and not any(s.lower() in from_addr.lower() for s in senders):
                    continue

                subject = msg.subject or "(no subject)"
                # Prefer plain text body; fall back to stripped HTML
                body = msg.text or _strip_html(msg.html or "")
                snippet = body[:300].strip()

                # Build a stable URL from Message-ID so dedup works
                msg_id = (msg.headers.get("message-id") or [""])[0].strip("<>")
                url = f"email://{user}/{msg_id}" if msg_id else f"email://{user}/{msg.uid}"

                pub_date: datetime | None = None
                try:
                    if msg.date:
                        pub_date = msg.date if msg.date.tzinfo else msg.date.replace(tzinfo=timezone.utc)
                except Exception:
                    pass

                results.append(Result(
                    url=url,
                    title=subject,
                    snippet=snippet,
                    source="email_newsletter",
                    source_type=self.source_type,
                    topic_name=topic.name,
                    fetched_at=datetime.now(timezone.utc),
                    published_at=pub_date,
                ))
        except Exception as exc:
            logger.warning("EmailNewsletterAdapter error: %s", exc)
            self._last_failed = True

        return results
