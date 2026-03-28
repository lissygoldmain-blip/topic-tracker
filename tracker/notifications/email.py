from __future__ import annotations

import html as _html
import logging

import resend

from tracker.models import Result

logger = logging.getLogger(__name__)


class EmailNotifier:
    def __init__(self, api_key: str, from_email: str, to_email: str):
        resend.api_key = api_key
        self._from = from_email
        self._to = to_email

    def send_immediate(self, result: Result) -> None:
        html = self._render_single(result)
        self._send(
            subject=f"[Tracker] {result.topic_name}: {result.title[:60]}",
            html=html,
        )

    def send_digest(self, results: list[Result], subject: str = "Topic Tracker Digest") -> None:
        if not results:
            return
        html = "<h2>Topic Tracker Digest</h2>"
        for r in results:
            html += self._render_single(r)
            r.notified_digest = True
        self._send(subject=subject, html=html)

    def _render_single(self, r: Result) -> str:
        score_pct = f"{r.novelty_score:.2f}" if r.novelty_score is not None else "—"
        title = _html.escape(r.title)
        url = _html.escape(r.url, quote=True)
        summary = _html.escape(r.summary or r.snippet or "")
        source = _html.escape(r.source)
        tags_str = ", ".join(_html.escape(t) for t in r.tags) if r.tags else "none"
        price_str = f" | Price: {_html.escape(str(r.price))}" if r.price else ""
        return (
            f"<div style='margin-bottom:24px;border-bottom:1px solid #eee;padding-bottom:16px'>"
            f"<h3><a href='{url}'>{title}</a></h3>"
            f"<p>{summary}</p>"
            f"<small>Source: {source}{price_str} | Score: {score_pct} | Tags: {tags_str}</small>"
            f"</div>"
        )

    def _send(self, subject: str, html: str) -> None:
        try:
            resend.Emails.send({
                "from": self._from,
                "to": [self._to],
                "subject": subject,
                "html": html,
            })
            logger.info("Email sent: %s", subject)
        except Exception as e:
            logger.error("Failed to send email: %s", e)
