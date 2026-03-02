"""SQLite database layer for Slack Hub."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from .config import Config


SCHEMA_VERSION = 1

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    channel_id TEXT NOT NULL,
    channel_name TEXT,
    thread_ts TEXT,
    user_id TEXT,
    user_name TEXT,
    text TEXT,
    ts REAL,
    permalink TEXT,
    mentions_me BOOLEAN DEFAULT 0,
    source_type TEXT DEFAULT 'channel',
    fetched_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS threads (
    id TEXT PRIMARY KEY,
    channel_id TEXT NOT NULL,
    channel_name TEXT,
    root_ts TEXT,
    root_user TEXT,
    root_text TEXT,
    reply_count INTEGER DEFAULT 0,
    i_participated BOOLEAN DEFAULT 0,
    i_was_mentioned BOOLEAN DEFAULT 0,
    source_type TEXT DEFAULT 'channel',
    last_reply_ts REAL,
    classification TEXT,
    summary TEXT,
    classified_at DATETIME
);

CREATE TABLE IF NOT EXISTS todos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_thread_id TEXT,
    source_permalink TEXT,
    title TEXT NOT NULL,
    context TEXT,
    source_message TEXT,
    source_author TEXT,
    owner TEXT,
    due_date TEXT,
    urgency TEXT DEFAULT 'medium',
    status TEXT DEFAULT 'open',
    fingerprint TEXT UNIQUE,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME
);

CREATE TABLE IF NOT EXISTS digests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    generated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    window_start DATETIME,
    window_end DATETIME,
    content_md TEXT
);

CREATE TABLE IF NOT EXISTS watermarks (
    channel_id TEXT PRIMARY KEY,
    last_ts REAL DEFAULT 0,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE INDEX IF NOT EXISTS idx_messages_channel_ts ON messages(channel_id, ts);
CREATE INDEX IF NOT EXISTS idx_messages_mentions ON messages(mentions_me) WHERE mentions_me = 1;
CREATE INDEX IF NOT EXISTS idx_threads_classification ON threads(classification);
CREATE INDEX IF NOT EXISTS idx_threads_unclassified ON threads(classification) WHERE classification IS NULL;
CREATE INDEX IF NOT EXISTS idx_todos_status ON todos(status);
CREATE INDEX IF NOT EXISTS idx_todos_fingerprint ON todos(fingerprint);
"""


class Database:
    """SQLite database manager for Slack Hub."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path).expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: Optional[sqlite3.Connection] = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path))
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
        return self._conn

    @contextmanager
    def transaction(self):
        """Context manager for database transactions."""
        try:
            yield self.conn
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def init_schema(self) -> None:
        """Create all tables and indexes."""
        with self.transaction():
            self.conn.executescript(SCHEMA_SQL)
            self.conn.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
                ("schema_version", str(SCHEMA_VERSION)),
            )

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    # ── Messages ─────────────────────────────────────────────────────────

    def upsert_message(self, msg: dict) -> None:
        """Insert or update a message."""
        self.conn.execute(
            """INSERT INTO messages (id, channel_id, channel_name, thread_ts,
               user_id, user_name, text, ts, permalink, mentions_me, source_type, fetched_at)
               VALUES (:id, :channel_id, :channel_name, :thread_ts,
               :user_id, :user_name, :text, :ts, :permalink, :mentions_me, :source_type, :fetched_at)
               ON CONFLICT(id) DO UPDATE SET
               text=excluded.text, user_name=excluded.user_name,
               mentions_me=excluded.mentions_me, fetched_at=excluded.fetched_at""",
            msg,
        )

    def upsert_messages(self, messages: list[dict]) -> int:
        """Batch upsert messages. Returns count of rows affected."""
        with self.transaction():
            for msg in messages:
                self.upsert_message(msg)
        return len(messages)

    def get_messages_since(
        self,
        channel_id: str,
        since_ts: float,
        limit: int = 1000,
    ) -> list[dict]:
        """Fetch messages from a channel after a given timestamp."""
        rows = self.conn.execute(
            """SELECT * FROM messages WHERE channel_id = ? AND ts > ?
               ORDER BY ts ASC LIMIT ?""",
            (channel_id, since_ts, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_messages_for_thread(self, channel_id: str, thread_ts: str) -> list[dict]:
        """Fetch all messages in a thread."""
        rows = self.conn.execute(
            """SELECT * FROM messages
               WHERE channel_id = ? AND (thread_ts = ? OR (ts = ? AND thread_ts IS NULL))
               ORDER BY ts ASC""",
            (channel_id, thread_ts, float(thread_ts)),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_messages_in_window(
        self,
        start: datetime,
        end: datetime,
        source_type: Optional[str] = None,
    ) -> list[dict]:
        """Fetch all messages within a time window."""
        start_ts = start.timestamp()
        end_ts = end.timestamp()
        if source_type:
            rows = self.conn.execute(
                """SELECT * FROM messages WHERE ts >= ? AND ts < ? AND source_type = ?
                   ORDER BY ts ASC""",
                (start_ts, end_ts, source_type),
            ).fetchall()
        else:
            rows = self.conn.execute(
                """SELECT * FROM messages WHERE ts >= ? AND ts < ? ORDER BY ts ASC""",
                (start_ts, end_ts),
            ).fetchall()
        return [dict(r) for r in rows]

    # ── Threads ──────────────────────────────────────────────────────────

    def upsert_thread(self, thread: dict) -> None:
        """Insert or update a thread."""
        self.conn.execute(
            """INSERT INTO threads (id, channel_id, channel_name, root_ts, root_user,
               root_text, reply_count, i_participated, i_was_mentioned, source_type,
               last_reply_ts)
               VALUES (:id, :channel_id, :channel_name, :root_ts, :root_user,
               :root_text, :reply_count, :i_participated, :i_was_mentioned, :source_type,
               :last_reply_ts)
               ON CONFLICT(id) DO UPDATE SET
               reply_count=excluded.reply_count, i_participated=excluded.i_participated,
               i_was_mentioned=excluded.i_was_mentioned, last_reply_ts=excluded.last_reply_ts,
               root_text=excluded.root_text""",
            thread,
        )

    def get_unclassified_threads(self, limit: int = 100) -> list[dict]:
        """Fetch threads that haven't been classified yet."""
        rows = self.conn.execute(
            """SELECT * FROM threads WHERE classification IS NULL
               ORDER BY last_reply_ts DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def update_thread_classification(
        self,
        thread_id: str,
        classification: str,
        summary: str,
    ) -> None:
        """Set classification and summary for a thread."""
        self.conn.execute(
            """UPDATE threads SET classification = ?, summary = ?,
               classified_at = ? WHERE id = ?""",
            (classification, summary, datetime.utcnow().isoformat(), thread_id),
        )

    def get_threads_in_window(
        self,
        start: datetime,
        end: datetime,
        classification: Optional[str] = None,
    ) -> list[dict]:
        """Fetch threads active within a time window."""
        start_ts = start.timestamp()
        end_ts = end.timestamp()
        if classification:
            rows = self.conn.execute(
                """SELECT * FROM threads WHERE last_reply_ts >= ? AND last_reply_ts < ?
                   AND classification = ? ORDER BY last_reply_ts DESC""",
                (start_ts, end_ts, classification),
            ).fetchall()
        else:
            rows = self.conn.execute(
                """SELECT * FROM threads WHERE last_reply_ts >= ? AND last_reply_ts < ?
                   ORDER BY last_reply_ts DESC""",
                (start_ts, end_ts),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_classified_threads_in_window(
        self,
        start: datetime,
        end: datetime,
    ) -> dict[str, list[dict]]:
        """Get threads grouped by classification within a window."""
        all_threads = self.get_threads_in_window(start, end)
        grouped: dict[str, list[dict]] = {
            "action_required": [],
            "awaiting_response": [],
            "fyi": [],
            "noise": [],
        }
        for t in all_threads:
            cls = t.get("classification", "noise") or "noise"
            if cls in grouped:
                grouped[cls].append(t)
            else:
                grouped["noise"].append(t)
        return grouped

    # ── TODOs ────────────────────────────────────────────────────────────

    def insert_todo(self, todo: dict) -> Optional[int]:
        """Insert a new TODO if fingerprint doesn't exist. Returns ID or None."""
        try:
            cursor = self.conn.execute(
                """INSERT INTO todos (source_thread_id, source_permalink, title,
                   context, source_message, source_author, owner, due_date,
                   urgency, status, fingerprint, created_at, updated_at)
                   VALUES (:source_thread_id, :source_permalink, :title,
                   :context, :source_message, :source_author, :owner, :due_date,
                   :urgency, :status, :fingerprint, :created_at, :updated_at)""",
                todo,
            )
            self.conn.commit()
            return cursor.lastrowid
        except sqlite3.IntegrityError:
            # Duplicate fingerprint — already exists
            return None

    def get_open_todos(self) -> list[dict]:
        """Get all open TODO items."""
        rows = self.conn.execute(
            """SELECT * FROM todos WHERE status = 'open'
               ORDER BY
               CASE urgency WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END,
               due_date ASC NULLS LAST""",
        ).fetchall()
        return [dict(r) for r in rows]

    def get_todos_by_status(self, status: str) -> list[dict]:
        """Get TODOs by status."""
        rows = self.conn.execute(
            "SELECT * FROM todos WHERE status = ? ORDER BY created_at DESC",
            (status,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_all_todos(self) -> list[dict]:
        """Get all TODOs regardless of status."""
        rows = self.conn.execute(
            "SELECT * FROM todos ORDER BY created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def update_todo_status(self, todo_id: int, status: str) -> None:
        """Update a TODO's status."""
        self.conn.execute(
            "UPDATE todos SET status = ?, updated_at = ? WHERE id = ?",
            (status, datetime.utcnow().isoformat(), todo_id),
        )
        self.conn.commit()

    def get_stale_todos(self, days: int = 14) -> list[dict]:
        """Get open TODOs older than the specified number of days."""
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
        rows = self.conn.execute(
            """SELECT * FROM todos WHERE status = 'open' AND created_at < ?""",
            (cutoff,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_recent_todos(self, hours: int = 1) -> list[dict]:
        """Get TODOs created within the last N hours."""
        cutoff = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
        rows = self.conn.execute(
            """SELECT * FROM todos WHERE created_at >= ?
               ORDER BY created_at DESC""",
            (cutoff,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ── Watermarks ───────────────────────────────────────────────────────

    def get_watermark(self, channel_id: str) -> float:
        """Get the last fetched timestamp for a channel."""
        row = self.conn.execute(
            "SELECT last_ts FROM watermarks WHERE channel_id = ?",
            (channel_id,),
        ).fetchone()
        return float(row["last_ts"]) if row else 0.0

    def set_watermark(self, channel_id: str, ts: float) -> None:
        """Update the watermark for a channel."""
        self.conn.execute(
            """INSERT INTO watermarks (channel_id, last_ts, updated_at)
               VALUES (?, ?, ?)
               ON CONFLICT(channel_id) DO UPDATE SET
               last_ts=excluded.last_ts, updated_at=excluded.updated_at""",
            (channel_id, ts, datetime.utcnow().isoformat()),
        )
        self.conn.commit()

    # ── Digests ──────────────────────────────────────────────────────────

    def save_digest(self, window_start: datetime, window_end: datetime, content: str) -> int:
        """Save a generated digest."""
        cursor = self.conn.execute(
            """INSERT INTO digests (window_start, window_end, content_md)
               VALUES (?, ?, ?)""",
            (window_start.isoformat(), window_end.isoformat(), content),
        )
        self.conn.commit()
        return cursor.lastrowid

    # ── Activity Stats ───────────────────────────────────────────────────

    def compute_activity_stats(
        self,
        start: datetime,
        end: datetime,
        user_id: str,
    ) -> dict[str, Any]:
        """Compute activity statistics for a time window."""
        start_ts = start.timestamp()
        end_ts = end.timestamp()

        messages_sent = self.conn.execute(
            "SELECT COUNT(*) as c FROM messages WHERE user_id = ? AND ts >= ? AND ts < ?",
            (user_id, start_ts, end_ts),
        ).fetchone()["c"]

        messages_received = self.conn.execute(
            "SELECT COUNT(*) as c FROM messages WHERE ts >= ? AND ts < ?",
            (start_ts, end_ts),
        ).fetchone()["c"]

        direct_mentions = self.conn.execute(
            "SELECT COUNT(*) as c FROM messages WHERE mentions_me = 1 AND ts >= ? AND ts < ?",
            (start_ts, end_ts),
        ).fetchone()["c"]

        threads_tagged = self.conn.execute(
            """SELECT COUNT(*) as c FROM threads
               WHERE i_was_mentioned = 1 AND last_reply_ts >= ? AND last_reply_ts < ?""",
            (start_ts, end_ts),
        ).fetchone()["c"]

        threads_awaiting = self.conn.execute(
            """SELECT COUNT(*) as c FROM threads
               WHERE classification = 'awaiting_response'
               AND last_reply_ts >= ? AND last_reply_ts < ?""",
            (start_ts, end_ts),
        ).fetchone()["c"]

        start_iso = start.isoformat()
        end_iso = end.isoformat()

        todos_created = self.conn.execute(
            "SELECT COUNT(*) as c FROM todos WHERE created_at >= ? AND created_at < ?",
            (start_iso, end_iso),
        ).fetchone()["c"]

        todos_resolved = self.conn.execute(
            "SELECT COUNT(*) as c FROM todos WHERE updated_at >= ? AND updated_at < ? AND status != 'open'",
            (start_iso, end_iso),
        ).fetchone()["c"]

        # Channel volumes
        channel_rows = self.conn.execute(
            """SELECT channel_name, COUNT(*) as msg_count
               FROM messages WHERE ts >= ? AND ts < ?
               GROUP BY channel_name ORDER BY msg_count DESC""",
            (start_ts, end_ts),
        ).fetchall()

        return {
            "messages_sent": messages_sent,
            "messages_received": messages_received,
            "direct_mentions": direct_mentions,
            "threads_tagged": threads_tagged,
            "threads_awaiting_response": threads_awaiting,
            "todos_created": todos_created,
            "todos_resolved": todos_resolved,
            "channel_volumes": {r["channel_name"]: r["msg_count"] for r in channel_rows},
        }


def get_database(config: Config) -> Database:
    """Create a Database instance from config."""
    return Database(config.db_path_resolved)
