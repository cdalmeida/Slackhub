"""Email digest delivery — daily brief and hourly pulse via Gmail API or SMTP."""

from __future__ import annotations

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Optional

from jinja2 import Environment, FileSystemLoader

from .config import Config
from .db import Database
from .digest import DigestGenerator

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).parent / "templates"


def _get_jinja_env() -> Environment:
    """Create a Jinja2 environment pointing at the templates directory."""
    if TEMPLATES_DIR.exists():
        return Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)), autoescape=True)
    return Environment(autoescape=True)


class EmailDigest:
    """Renders and delivers email digests."""

    def __init__(self, config: Config, db: Database):
        self.config = config
        self.db = db
        self.generator = DigestGenerator(config, db)
        self.jinja = _get_jinja_env()

    def send_daily_brief(self) -> bool:
        """Generate and send the daily morning brief."""
        if not self.config.email.daily_digest.enabled:
            logger.info("Daily digest disabled in config.")
            return False

        data = self.generator.generate_daily_data()
        html = self._render_daily(data)
        subject = f"Slack Hub \u2014 Daily Brief for {data['date_label']}"

        return self._send_email(subject=subject, html_body=html)

    def send_hourly_pulse(self) -> bool:
        """Generate and send an hourly pulse, with smart suppression."""
        if not self.config.email.hourly_pulse.enabled:
            logger.info("Hourly pulse disabled in config.")
            return False

        data = self.generator.generate_hourly_data(minutes=60)

        # Smart suppression
        if self.config.email.hourly_pulse.skip_if_empty:
            if not self.generator.should_send_hourly_pulse(data):
                logger.info("Hourly pulse suppressed — no notable items.")
                return False

        html = self._render_hourly(data)

        # Build subject with counts
        n_todos = len(data.get("new_todos", []))
        n_mentions = data["stats"].get("direct_mentions", 0)
        n_msgs = data["stats"].get("messages_received", 0)
        subject = (
            f"\u26A1 Slack Pulse {data['end_label']} \u2014 "
            f"{n_todos} new TODO{'s' if n_todos != 1 else ''}, "
            f"{n_mentions} mention{'s' if n_mentions != 1 else ''}, "
            f"{n_msgs} msgs"
        )

        return self._send_email(subject=subject, html_body=html)

    def _render_daily(self, data: dict) -> str:
        """Render the daily brief HTML."""
        try:
            template = self.jinja.get_template("daily_brief.html.j2")
            return template.render(**data)
        except Exception:
            # Inline fallback template
            return self._render_daily_inline(data)

    def _render_hourly(self, data: dict) -> str:
        """Render the hourly pulse HTML."""
        try:
            template = self.jinja.get_template("hourly_pulse.html.j2")
            return template.render(**data)
        except Exception:
            return self._render_hourly_inline(data)

    def _render_daily_inline(self, data: dict) -> str:
        """Inline fallback renderer for daily brief."""
        todos_html = ""
        for todo in data.get("open_todos", []):
            urgency = todo.get("Urgency", "medium").lower()
            color = {"high": "#fee2e2", "medium": "#fef9c3"}.get(urgency, "#f3f4f6")
            icon = {"high": "\U0001F534", "medium": "\U0001F7E1", "low": "\U0001F535"}.get(urgency, "\u2022")
            link = todo.get("Thread Link", "#")
            todos_html += (
                f'<tr style="background:{color}">'
                f'<td>{icon} {urgency.upper()}</td>'
                f'<td><strong>{todo.get("Title", "")}</strong></td>'
                f'<td>{todo.get("Due Date", "")}</td>'
                f'<td><a href="{link}">[thread]</a></td>'
                f'</tr>'
            )

        stats = data.get("stats", {})
        channel_html = ""
        for ch, count in sorted(
            stats.get("channel_volumes", {}).items(),
            key=lambda x: x[1], reverse=True
        ):
            max_v = max(stats.get("channel_volumes", {}).values() or [1])
            bar_len = int((count / max_v) * 10)
            bar = "\u2588" * bar_len + "\u2591" * (10 - bar_len)
            channel_html += f'<tr><td>{ch}</td><td>{bar} {count} msgs</td></tr>'

        sheet_link = data.get("sheet_url", "")
        link_html = f'<a href="{sheet_link}">Open full TODO sheet \u2192</a>' if sheet_link else ""

        return f"""
        <html><body style="font-family:Arial,sans-serif;max-width:700px;margin:auto;padding:20px;">
        <h2>\U0001F4CB Your Active TODOs ({data.get('total_open_todos', 0)} open)</h2>
        <table style="width:100%;border-collapse:collapse;" cellpadding="8">
        {todos_html}
        </table>
        <p>{link_html}</p>

        <h2>\U0001F4CA Yesterday's Activity</h2>
        <table cellpadding="4">
        <tr><td><strong>Messages sent</strong></td><td>{stats.get('messages_sent', 0)}</td></tr>
        <tr><td><strong>Messages received</strong></td><td>{stats.get('messages_received', 0)}</td></tr>
        <tr><td><strong>Direct @mentions</strong></td><td>{stats.get('direct_mentions', 0)}</td></tr>
        <tr><td><strong>Threads tagged in</strong></td><td>{stats.get('threads_tagged', 0)}</td></tr>
        <tr><td><strong>TODOs created</strong></td><td>{stats.get('todos_created', 0)}</td></tr>
        <tr><td><strong>TODOs resolved</strong></td><td>{stats.get('todos_resolved', 0)}</td></tr>
        </table>

        <h3>Channel Activity</h3>
        <table cellpadding="4">{channel_html}</table>

        <h2>\U0001F5D2\uFE0F What Happened Overnight</h2>
        <p>{data.get('narrative', 'No notable overnight activity.')}</p>
        </body></html>
        """

    def _render_hourly_inline(self, data: dict) -> str:
        """Inline fallback renderer for hourly pulse."""
        todos_html = ""
        for todo in data.get("new_todos", []):
            urgency = todo.get("urgency", "medium")
            color = {"high": "#fee2e2", "medium": "#fef9c3"}.get(urgency, "#f3f4f6")
            todos_html += (
                f'<tr style="background:{color}">'
                f'<td><strong>{todo.get("title", "")}</strong></td>'
                f'<td>{urgency.title()}</td>'
                f'<td>{todo.get("due_date", "")}</td>'
                f'</tr>'
                f'<tr><td colspan="3" style="color:#666;font-size:13px;">'
                f'\U0001F4AC <em>"{todo.get("source_message", "")[:200]}"</em> '
                f'\u2014 {todo.get("source_author", "")} '
                f'</td></tr>'
            )

        awaiting_html = ""
        for t in data.get("awaiting_response", []):
            awaiting_html += (
                f'<p><strong>{t.get("channel_name", "")}</strong> \u2014 '
                f'{t.get("summary", t.get("root_text", "")[:200])}</p>'
            )

        fyi_html = ""
        for t in data.get("fyi", []):
            fyi_html += (
                f'<li><strong>{t.get("channel_name", "")}</strong> \u2014 '
                f'{t.get("summary", t.get("root_text", "")[:150])}</li>'
            )

        stats = data.get("stats", {})
        channels = stats.get("channel_volumes", {})
        threshold = self.config.email.hourly_pulse.quiet_channel_threshold
        active_channels = {k: v for k, v in channels.items() if v >= threshold}
        quiet_count = len(channels) - len(active_channels)
        quiet_msgs = sum(v for k, v in channels.items() if v < threshold)

        channel_html = ""
        for ch, count in sorted(active_channels.items(), key=lambda x: x[1], reverse=True):
            channel_html += f'<tr><td>{ch}</td><td>{count} msgs</td></tr>'
        if quiet_count > 0:
            channel_html += (
                f'<tr><td style="color:#999">{quiet_count} other channels</td>'
                f'<td style="color:#999">{quiet_msgs} msgs combined</td></tr>'
            )

        uc = data.get("urgency_counts", {})
        sheet_link = data.get("sheet_url", "")
        footer_link = f'<a href="{sheet_link}">Open sheet \u2192</a>' if sheet_link else ""

        return f"""
        <html><body style="font-family:Arial,sans-serif;max-width:600px;margin:auto;padding:20px;">
        <h3>\u26A1 Last Hour ({data.get('start_label', '')} \u2013 {data.get('end_label', '')})</h3>

        {'<h4>\U0001F534 New TODOs (' + str(len(data.get("new_todos", []))) + ')</h4><table cellpadding="6" style="width:100%">' + todos_html + '</table>' if data.get("new_todos") else ''}

        {'<h4>\U0001F4AC Awaiting Your Response</h4>' + awaiting_html if data.get("awaiting_response") else ''}

        {'<h4>\U0001F4CC FYI Mentions</h4><ul>' + fyi_html + '</ul>' if data.get("fyi") else ''}

        <h4>\U0001F4CA Channel Activity</h4>
        <table cellpadding="4">{channel_html}</table>

        <p style="border-top:1px solid #eee;padding-top:8px;color:#666;">
        \U0001F4CB <strong>{data.get('total_open_todos', 0)} open TODOs</strong>
        ({uc.get('high', 0)} high, {uc.get('medium', 0)} medium, {uc.get('low', 0)} low)
        \u00B7 {footer_link}
        </p>
        </body></html>
        """

    def _send_email(self, subject: str, html_body: str) -> bool:
        """Send email via configured method."""
        recipient = self.config.email.recipient
        if not recipient:
            logger.error("No email recipient configured.")
            return False

        if self.config.email.method == "gmail_api":
            return self._send_via_gmail(subject, html_body, recipient)
        else:
            return self._send_via_smtp(subject, html_body, recipient)

    def _send_via_gmail(self, subject: str, html_body: str, to: str) -> bool:
        """Send email using Gmail API."""
        try:
            import base64
            from google.oauth2.service_account import Credentials
            from googleapiclient.discovery import build

            creds_path = Path(self.config.todo.google_credentials_path).expanduser()
            creds = Credentials.from_service_account_file(
                str(creds_path),
                scopes=["https://www.googleapis.com/auth/gmail.send"],
                subject=to,  # Send as the user
            )
            service = build("gmail", "v1", credentials=creds)

            msg = MIMEMultipart("alternative")
            msg["To"] = to
            msg["Subject"] = subject
            msg.attach(MIMEText(html_body, "html"))

            raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
            service.users().messages().send(
                userId="me", body={"raw": raw}
            ).execute()

            logger.info(f"Email sent via Gmail API: {subject}")
            return True

        except Exception as e:
            logger.error(f"Gmail API send failed: {e}")
            return False

    def _send_via_smtp(self, subject: str, html_body: str, to: str) -> bool:
        """Send email via SMTP."""
        try:
            smtp_cfg = self.config.email.smtp
            msg = MIMEMultipart("alternative")
            msg["To"] = to
            msg["From"] = to  # Send from self
            msg["Subject"] = subject
            msg.attach(MIMEText(html_body, "html"))

            if smtp_cfg.use_tls:
                server = smtplib.SMTP(smtp_cfg.host, smtp_cfg.port)
                server.starttls()
            else:
                server = smtplib.SMTP(smtp_cfg.host, smtp_cfg.port)

            server.send_message(msg)
            server.quit()

            logger.info(f"Email sent via SMTP: {subject}")
            return True

        except Exception as e:
            logger.error(f"SMTP send failed: {e}")
            return False
