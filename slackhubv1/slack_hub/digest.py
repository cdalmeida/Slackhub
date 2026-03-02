"""Digest generator — creates structured summaries of Slack activity."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

from .config import Config
from .db import Database
from .classifier import Classifier
from .sheets import get_sheets_manager

logger = logging.getLogger(__name__)


URGENCY_ICONS = {"high": "\U0001F534", "medium": "\U0001F7E1", "low": "\U0001F535"}
CLASSIFICATION_SECTIONS = {
    "action_required": ("\U0001F534 Action Required", 1),
    "awaiting_response": ("\U0001F7E1 Awaiting Your Response", 2),
    "fyi": ("\U0001F535 FYI", 3),
}


class DigestGenerator:
    """Generates Markdown and data-structure digests from classified Slack activity."""

    def __init__(self, config: Config, db: Database):
        self.config = config
        self.db = db
        self.classifier = Classifier(config, db)
        self.sheets = get_sheets_manager(config, db)

    def generate(
        self,
        hours: Optional[int] = None,
        include_todos: bool = True,
        include_stats: bool = True,
    ) -> str:
        """Generate a full Markdown digest.

        Args:
            hours: Lookback window in hours (defaults to config.lookback_hours).
            include_todos: Include open TODO list.
            include_stats: Include activity statistics.

        Returns:
            Markdown string.
        """
        lookback = hours or self.config.lookback_hours
        end = datetime.utcnow()
        start = end - timedelta(hours=lookback)

        lines = [
            f"# Slack Digest — {end.strftime('%b %d, %Y')} (Last {lookback} hours)",
            "",
        ]

        # Classified threads
        grouped = self.db.get_classified_threads_in_window(start, end)

        for cls_key, (section_title, _) in CLASSIFICATION_SECTIONS.items():
            threads = grouped.get(cls_key, [])
            if not threads:
                continue

            lines.append(f"## {section_title} ({len(threads)} items)")
            lines.append("")

            # Group by channel
            by_channel: dict[str, list[dict]] = {}
            for t in threads:
                ch = t.get("channel_name", "unknown")
                by_channel.setdefault(ch, []).append(t)

            for channel, channel_threads in by_channel.items():
                lines.append(f"### {channel}")
                for t in channel_threads:
                    summary = t.get("summary") or t.get("root_text", "")[:200]
                    source = t.get("source_type", "channel")
                    prefix = "[DM] " if source in ("im", "mpim") else ""
                    lines.append(f"- {prefix}**{summary}**")
                lines.append("")

        # TODOs
        if include_todos:
            todos = self.sheets.get_open_todos_for_digest()
            if todos:
                lines.append(f"## \U0001F4CB Open TODOs ({len(todos)})")
                lines.append("")
                for todo in todos:
                    urgency = todo.get("Urgency", "medium").lower()
                    icon = URGENCY_ICONS.get(urgency, "\u2022")
                    title = todo.get("Title", "Untitled")
                    due = todo.get("Due Date", "")
                    due_str = f" — Due: {due}" if due else ""
                    status = todo.get("effective_status", "open")
                    lines.append(f"- {icon} **{title}**{due_str} [{status}]")
                lines.append("")

        # Stats
        if include_stats:
            stats = self.db.compute_activity_stats(start, end, self.config.user_id)
            lines.extend(self._format_stats(stats))

        content = "\n".join(lines)

        # Save to DB
        self.db.save_digest(start, end, content)

        return content

    def generate_hourly_data(self, minutes: int = 60) -> dict:
        """Generate structured data for the hourly pulse email.

        Returns a dict with all data needed by the email template.
        """
        end = datetime.utcnow()
        start = end - timedelta(minutes=minutes)

        grouped = self.db.get_classified_threads_in_window(start, end)
        new_todos = self.db.get_recent_todos(hours=1)
        all_open_todos = self.sheets.get_open_todos_for_digest()
        stats = self.db.compute_activity_stats(start, end, self.config.user_id)

        # Count by urgency for the running total
        urgency_counts = {"high": 0, "medium": 0, "low": 0}
        for todo in all_open_todos:
            urg = todo.get("Urgency", "medium").lower()
            urgency_counts[urg] = urgency_counts.get(urg, 0) + 1

        return {
            "start": start,
            "end": end,
            "start_label": start.strftime("%-I:%M %p"),
            "end_label": end.strftime("%-I:%M %p"),
            "new_todos": new_todos,
            "action_required": grouped.get("action_required", []),
            "awaiting_response": grouped.get("awaiting_response", []),
            "fyi": grouped.get("fyi", []),
            "stats": stats,
            "total_open_todos": len(all_open_todos),
            "urgency_counts": urgency_counts,
            "sheet_url": f"https://docs.google.com/spreadsheets/d/{self.config.todo.sheet_id}"
            if self.config.todo.sheet_id else "",
        }

    def generate_daily_data(self) -> dict:
        """Generate structured data for the daily brief email."""
        end = datetime.utcnow()
        # Go back to yesterday's last active hour (roughly)
        start = end - timedelta(hours=14)

        grouped = self.db.get_classified_threads_in_window(start, end)
        all_open_todos = self.sheets.get_open_todos_for_digest()
        stats = self.db.compute_activity_stats(start, end, self.config.user_id)

        # Generate narrative summary
        narrative = self.classifier.generate_summary(
            start, end,
            window_label=f"overnight ({start.strftime('%I:%M %p')} to {end.strftime('%I:%M %p')})",
        )

        # Urgency counts
        urgency_counts = {"high": 0, "medium": 0, "low": 0}
        for todo in all_open_todos:
            urg = todo.get("Urgency", "medium").lower()
            urgency_counts[urg] = urgency_counts.get(urg, 0) + 1

        return {
            "date": end,
            "date_label": end.strftime("%A, %b %-d"),
            "open_todos": all_open_todos,
            "total_open_todos": len(all_open_todos),
            "urgency_counts": urgency_counts,
            "stats": stats,
            "narrative": narrative,
            "grouped_threads": grouped,
            "sheet_url": f"https://docs.google.com/spreadsheets/d/{self.config.todo.sheet_id}"
            if self.config.todo.sheet_id else "",
        }

    def should_send_hourly_pulse(self, data: dict) -> bool:
        """Determine if the hourly pulse should be sent based on smart suppression."""
        if data.get("new_todos"):
            return True
        if data.get("awaiting_response"):
            return True
        if data["stats"].get("direct_mentions", 0) >= 2:
            return True
        if data["stats"].get("messages_received", 0) >= 20:
            return True
        return False

    def _format_stats(self, stats: dict) -> list[str]:
        """Format activity stats as Markdown."""
        lines = [
            "## \U0001F4CA Activity Stats",
            "",
            f"- **Messages sent:** {stats.get('messages_sent', 0)}",
            f"- **Messages received:** {stats.get('messages_received', 0)}",
            f"- **Direct @mentions:** {stats.get('direct_mentions', 0)}",
            f"- **Threads tagged in:** {stats.get('threads_tagged', 0)}",
            f"- **Awaiting response:** {stats.get('threads_awaiting_response', 0)}",
            f"- **TODOs created:** {stats.get('todos_created', 0)}",
            f"- **TODOs resolved:** {stats.get('todos_resolved', 0)}",
            "",
        ]

        channel_volumes = stats.get("channel_volumes", {})
        if channel_volumes:
            lines.append("### Channel Activity")
            lines.append("")
            max_vol = max(channel_volumes.values()) if channel_volumes else 1
            for channel, count in sorted(
                channel_volumes.items(), key=lambda x: x[1], reverse=True
            ):
                bar_len = int((count / max_vol) * 12)
                bar = "\u2588" * bar_len + "\u2591" * (12 - bar_len)
                lines.append(f"- {channel}: {bar} {count} msgs")
            lines.append("")

        return lines
