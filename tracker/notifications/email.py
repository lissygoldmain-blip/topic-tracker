from __future__ import annotations

import html as _html
import itertools
import logging
from typing import Iterable

import resend

from tracker.models import Result

logger = logging.getLogger(__name__)

# ── colour palette ────────────────────────────────────────────────────────────
_BG = "#0f0f0f"
_SURFACE = "#1c1c1e"
_BORDER = "#2e2e30"
_TEXT = "#f5f5f5"
_MUTED = "#8e8e93"
_ACCENT = "#4f8ef7"
_GREEN = "#30d158"
_YELLOW = "#ffd60a"
_RED = "#ff453a"

_TOPIC_ICONS: dict[str, str] = {
    "jobs": "💼",
    "shopping": "🛍",
    "film": "🎬",
    "drag": "👑",
    "queer": "🏳️‍🌈",
    "immigration": "⚠️",
    "health": "🔬",
    "politics": "🌐",
    "queens": "🗺",
    "substack": "📬",
    "ai": "🤖",
    "nyc": "🗽",
    "theater": "🎭",
}


def _topic_icon(name: str) -> str:
    lower = name.lower()
    for key, icon in _TOPIC_ICONS.items():
        if key in lower:
            return icon
    return "📌"


def _score_color(score: float | None) -> str:
    if score is None:
        return _MUTED
    if score >= 0.75:
        return _GREEN
    if score >= 0.55:
        return _YELLOW
    return _RED


class EmailNotifier:
    def __init__(self, api_key: str, from_email: str, to_email: str):
        resend.api_key = api_key
        self._from = from_email
        self._to = to_email

    def send_immediate(self, result: Result) -> None:
        html = self._wrap_email(
            body=self._render_single(result),
            subject=f"[Tracker] {result.topic_name}: {result.title[:60]}",
        )
        self._send(
            subject=f"[Tracker] {result.topic_name}: {result.title[:60]}",
            html=html,
        )

    def send_digest(self, results: list[Result], subject: str = "Topic Tracker Digest") -> None:
        if not results:
            return

        # Group by topic name (assume results pre-sorted by topic_name)
        body_parts: list[str] = []
        for topic_name, group in itertools.groupby(results, key=lambda r: r.topic_name):
            items = list(group)
            icon = _topic_icon(topic_name)
            topic_html = (
                f"<tr><td style='padding:28px 0 10px'>"
                f"<span style='font-size:18px;font-weight:700;color:{_TEXT}'>"
                f"{icon} {_html.escape(topic_name)}</span>"
                f"</td></tr>"
            )
            body_parts.append(topic_html)
            for r in items:
                body_parts.append(self._render_single(r))
                r.notified_digest = True

        body = "\n".join(body_parts)
        count = len(results)
        footer_note = f"{count} result{'s' if count != 1 else ''} this week"
        html = self._wrap_email(body=body, subject=subject, footer_note=footer_note)
        self._send(subject=subject, html=html)

    # ── rendering ─────────────────────────────────────────────────────────────

    def _render_single(self, r: Result) -> str:
        score = r.novelty_score
        score_color = _score_color(score)
        score_str = f"{score:.2f}" if score is not None else "—"

        title = _html.escape(r.title)
        url = _html.escape(r.url, quote=True)
        summary = _html.escape(r.summary or r.snippet or "")[:400]
        source = _html.escape(r.source)
        tags = ", ".join(_html.escape(t) for t in r.tags) if r.tags else ""
        price_badge = (
            f"<span style='margin-left:8px;background:#2c2c2e;color:{_TEXT};"
            f"padding:2px 8px;border-radius:4px;font-size:12px'>"
            f"{_html.escape(str(r.price))}</span>"
            if r.price else ""
        )

        return (
            f"<tr><td style='padding:12px 0;border-bottom:1px solid {_BORDER}'>"
            f"  <a href='{url}' style='font-size:15px;font-weight:600;color:{_ACCENT};"
            f"     text-decoration:none;display:block;margin-bottom:5px'>{title}</a>"
            + (f"  <p style='margin:0 0 8px;font-size:13px;color:{_TEXT};line-height:1.55'>{summary}</p>" if summary else "")
            + f"  <span style='font-size:12px;color:{_MUTED}'>{source}</span>"
            + (f"  &nbsp;·&nbsp;<span style='font-size:12px;color:{_MUTED}'>{tags}</span>" if tags else "")
            + price_badge
            + f"  &nbsp;&nbsp;<span style='font-size:12px;font-weight:700;color:{score_color}'>"
            + f"  ▲ {score_str}</span>"
            + f"</td></tr>"
        )

    def _wrap_email(self, body: str, subject: str, footer_note: str = "") -> str:
        ui_url = "https://lissygoldmain-blip.github.io/topic-tracker-ui/"
        escaped_subject = _html.escape(subject)
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{escaped_subject}</title>
</head>
<body style="margin:0;padding:0;background:{_BG};font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:{_BG};padding:32px 16px">
    <tr><td align="center">
      <table width="600" cellpadding="0" cellspacing="0"
             style="max-width:600px;background:{_SURFACE};border-radius:12px;
                    border:1px solid {_BORDER};overflow:hidden">

        <!-- header -->
        <tr><td style="padding:24px 32px;border-bottom:1px solid {_BORDER}">
          <span style="font-size:22px;font-weight:700;color:{_TEXT}">
            Topic Tracker
          </span>
          <span style="float:right;font-size:13px;color:{_MUTED};line-height:2.2">
            {escaped_subject}
          </span>
        </td></tr>

        <!-- body -->
        <tr><td style="padding:0 32px">
          <table width="100%" cellpadding="0" cellspacing="0">
            {body}
          </table>
        </td></tr>

        <!-- footer -->
        <tr><td style="padding:20px 32px;border-top:1px solid {_BORDER};text-align:center">
          <span style="font-size:12px;color:{_MUTED}">
            {_html.escape(footer_note)}
            {'&nbsp;·&nbsp;' if footer_note else ''}
            <a href="{_html.escape(ui_url, quote=True)}"
               style="color:{_ACCENT};text-decoration:none">View dashboard</a>
          </span>
        </td></tr>

      </table>
    </td></tr>
  </table>
</body>
</html>"""

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
