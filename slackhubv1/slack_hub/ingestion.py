"""Slack message ingestion — fetches, normalizes, and stores messages and threads."""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timedelta
from typing import Optional

try:
    import emoji as emoji_lib
except ImportError:
    emoji_lib = None
try:
    from slack_sdk import WebClient
    from slack_sdk.errors import SlackApiError
except ImportError:
    WebClient = None  # type: ignore
    SlackApiError = Exception  # type: ignore

from .config import Config, ChannelEntry, DMEntry
from .db import Database

logger = logging.getLogger(__name__)


# ── Slack text normalization ────────────────────────────────────────────────

def resolve_slack_text(
    text: str,
    user_cache: dict[str, str],
) -> str:
    """Convert Slack mrkdwn to human-readable plain text.

    Resolves <@U0ABC123> user mentions, <#C0ABC|general> channel refs,
    and emoji shortcodes.
    """
    if not text:
        return ""
    # User mentions
    text = re.sub(
        r"<@(U\w+)>",
        lambda m: f"@{user_cache.get(m.group(1), m.group(1))}",
        text,
    )
    # Channel references
    text = re.sub(r"<#\w+\|([^>]+)>", r"#\1", text)
    # URLs: <https://example.com|label> → label, <https://example.com> → url
    text = re.sub(r"<(https?://[^|>]+)\|([^>]+)>", r"\2", text)
    text = re.sub(r"<(https?://[^>]+)>", r"\1", text)
    # Emoji shortcodes
    try:
        if emoji_lib is not None:
            text = emoji_lib.emojize(text, language="alias")
    except Exception:
        pass
    return text


def truncate_text(text: str, max_len: int = 500) -> str:
    """Truncate text for storage, preserving word boundaries."""
    if not text or len(text) <= max_len:
        return text or ""
    return text[: max_len - 3].rsplit(" ", 1)[0] + "..."


# ── Rate limiter ────────────────────────────────────────────────────────────

class RateLimiter:
    """Simple token-bucket rate limiter for Slack API calls."""

    def __init__(self, max_per_minute: int = 40):
        self.max_per_minute = max_per_minute
        self.timestamps: list[float] = []

    def wait_if_needed(self) -> None:
        """Block until a request slot is available."""
        now = time.time()
        # Prune timestamps older than 60 seconds
        self.timestamps = [t for t in self.timestamps if now - t < 60]
        if len(self.timestamps) >= self.max_per_minute:
            sleep_time = 60 - (now - self.timestamps[0]) + 0.1
            if sleep_time > 0:
                logger.debug(f"Rate limit: sleeping {sleep_time:.1f}s")
                time.sleep(sleep_time)
        self.timestamps.append(time.time())


# ── User cache ──────────────────────────────────────────────────────────────

class UserCache:
    """Caches Slack user ID → display name mappings."""

    def __init__(self, client: WebClient, rate_limiter: RateLimiter):
        self._client = client
        self._rate_limiter = rate_limiter
        self._cache: dict[str, str] = {}

    def get_name(self, user_id: str) -> str:
        if user_id in self._cache:
            return self._cache[user_id]
        try:
            self._rate_limiter.wait_if_needed()
            result = self._client.users_info(user=user_id)
            profile = result["user"]["profile"]
            name = (
                profile.get("display_name")
                or profile.get("real_name")
                or user_id
            )
            self._cache[user_id] = name
            return name
        except SlackApiError as e:
            logger.warning(f"Failed to resolve user {user_id}: {e}")
            self._cache[user_id] = user_id
            return user_id

    def bulk_load(self, user_ids: set[str]) -> None:
        """Pre-fetch names for a batch of user IDs."""
        for uid in user_ids:
            if uid not in self._cache:
                self.get_name(uid)

    @property
    def cache(self) -> dict[str, str]:
        return self._cache


# ── Ingestion engine ────────────────────────────────────────────────────────

class SlackIngester:
    """Fetches Slack messages and threads, normalizes, and stores them."""

    def __init__(self, config: Config, db: Database):
        self.config = config
        self.db = db
        self.client = WebClient(token=config.slack_token)
        self.rate_limiter = RateLimiter(
            max_per_minute=config.polling.get("slack_api", {}).get(
                "max_requests_per_minute", 40
            )
            if isinstance(config.polling, dict)
            else 40
        )
        self.user_cache = UserCache(self.client, self.rate_limiter)

    def run(
        self,
        tier: Optional[str] = None,
        lookback_hours: Optional[int] = None,
    ) -> dict[str, int]:
        """Run a full ingestion sweep.

        Args:
            tier: If set, only fetch channels in this tier.
            lookback_hours: Override default lookback for first-run backfill.

        Returns:
            Dict with counts of messages and threads ingested.
        """
        stats = {"messages": 0, "threads": 0, "channels": 0, "dms": 0}

        # Determine which channels to fetch
        channels = self._get_channels(tier)
        logger.info(f"Ingesting {len(channels)} channels...")

        for channel in channels:
            try:
                msg_count, thread_count = self._ingest_channel(
                    channel_id=channel.id,
                    channel_name=channel.name,
                    source_type="channel",
                    lookback_hours=lookback_hours,
                )
                stats["messages"] += msg_count
                stats["threads"] += thread_count
                stats["channels"] += 1
            except SlackApiError as e:
                logger.error(f"Error ingesting {channel.name}: {e}")
                continue

        # Ingest DMs if enabled
        if self.config.direct_messages.enabled:
            for dm in self.config.all_dm_conversations:
                try:
                    source_type = "mpim" if dm.id.startswith("G") else "im"
                    msg_count, thread_count = self._ingest_channel(
                        channel_id=dm.id,
                        channel_name=dm.name,
                        source_type=source_type,
                        lookback_hours=lookback_hours,
                    )
                    stats["messages"] += msg_count
                    stats["threads"] += thread_count
                    stats["dms"] += 1
                except SlackApiError as e:
                    logger.error(f"Error ingesting DM {dm.name}: {e}")
                    continue

        # Check for :todo: emoji reactions
        self._ingest_todo_reactions()

        logger.info(
            f"Ingestion complete: {stats['messages']} messages, "
            f"{stats['threads']} threads from {stats['channels']} channels "
            f"and {stats['dms']} DMs"
        )
        return stats

    def _get_channels(self, tier: Optional[str]) -> list[ChannelEntry]:
        """Get channels to ingest based on tier filter."""
        if tier:
            return self.config.channels.get(tier, [])
        return self.config.all_channels

    def _ingest_channel(
        self,
        channel_id: str,
        channel_name: str,
        source_type: str = "channel",
        lookback_hours: Optional[int] = None,
    ) -> tuple[int, int]:
        """Ingest messages and threads from a single channel.

        Returns (message_count, thread_count).
        """
        watermark = self.db.get_watermark(channel_id)

        # On first run, use lookback; otherwise use watermark
        if watermark == 0 and lookback_hours:
            oldest = (datetime.utcnow() - timedelta(hours=lookback_hours)).timestamp()
        elif watermark == 0:
            oldest = (
                datetime.utcnow() - timedelta(hours=self.config.lookback_hours)
            ).timestamp()
        else:
            oldest = watermark

        logger.debug(f"Fetching {channel_name} since {oldest}")

        messages = self._fetch_history(channel_id, oldest)
        if not messages:
            return 0, 0

        # Collect user IDs for bulk resolution
        user_ids = {m.get("user", "") for m in messages if m.get("user")}
        self.user_cache.bulk_load(user_ids)

        # Process and store messages
        msg_count = 0
        thread_roots: dict[str, dict] = {}  # thread_ts → root message
        max_ts = watermark

        for msg in messages:
            ts = float(msg.get("ts", 0))
            max_ts = max(max_ts, ts)
            user_id = msg.get("user", "")
            user_name = self.user_cache.get_name(user_id) if user_id else ""
            text = resolve_slack_text(msg.get("text", ""), self.user_cache.cache)

            mentions_me = self.config.user_id in msg.get("text", "")

            msg_id = f"{channel_id}_{msg['ts']}"
            thread_ts = msg.get("thread_ts")

            self.db.upsert_message({
                "id": msg_id,
                "channel_id": channel_id,
                "channel_name": channel_name,
                "thread_ts": thread_ts if thread_ts != msg["ts"] else None,
                "user_id": user_id,
                "user_name": user_name,
                "text": text,
                "ts": ts,
                "permalink": msg.get("permalink", ""),
                "mentions_me": mentions_me,
                "source_type": source_type,
                "fetched_at": datetime.utcnow().isoformat(),
            })
            msg_count += 1

            # Track threads that need reply fetching
            reply_count = msg.get("reply_count", 0)
            if reply_count > 0 and not thread_ts:
                thread_roots[msg["ts"]] = msg

        # Fetch and process thread replies
        thread_count = 0
        for root_ts, root_msg in thread_roots.items():
            try:
                thread_count += 1
                self._ingest_thread_replies(
                    channel_id=channel_id,
                    channel_name=channel_name,
                    root_msg=root_msg,
                    source_type=source_type,
                )
            except SlackApiError as e:
                logger.warning(f"Failed to fetch thread {root_ts}: {e}")

        # Update watermark
        if max_ts > watermark:
            self.db.set_watermark(channel_id, max_ts)

        self.db.conn.commit()
        logger.info(
            f"  {channel_name}: {msg_count} messages, {thread_count} threads"
        )
        return msg_count, thread_count

    def _fetch_history(
        self,
        channel_id: str,
        oldest: float,
        limit: int = 200,
    ) -> list[dict]:
        """Fetch channel history with pagination."""
        all_messages = []
        cursor = None

        while True:
            self.rate_limiter.wait_if_needed()
            kwargs = {
                "channel": channel_id,
                "oldest": str(oldest),
                "limit": min(limit, 200),
            }
            if cursor:
                kwargs["cursor"] = cursor

            try:
                result = self.client.conversations_history(**kwargs)
            except SlackApiError as e:
                if e.response.get("error") == "ratelimited":
                    retry_after = int(e.response.headers.get("Retry-After", 30))
                    logger.warning(f"Rate limited, sleeping {retry_after}s")
                    time.sleep(retry_after)
                    continue
                raise

            all_messages.extend(result.get("messages", []))

            if not result.get("has_more"):
                break
            cursor = result.get("response_metadata", {}).get("next_cursor")
            if not cursor:
                break

        return all_messages

    def _ingest_thread_replies(
        self,
        channel_id: str,
        channel_name: str,
        root_msg: dict,
        source_type: str,
    ) -> None:
        """Fetch and store replies for a thread, then upsert the thread record."""
        root_ts = root_msg["ts"]

        self.rate_limiter.wait_if_needed()
        result = self.client.conversations_replies(
            channel=channel_id,
            ts=root_ts,
            limit=self.config.thread_depth,
        )
        replies = result.get("messages", [])

        i_participated = False
        i_was_mentioned = False
        last_reply_ts = float(root_ts)

        for reply in replies:
            reply_ts = float(reply.get("ts", 0))
            last_reply_ts = max(last_reply_ts, reply_ts)
            user_id = reply.get("user", "")
            user_name = self.user_cache.get_name(user_id) if user_id else ""
            text = resolve_slack_text(reply.get("text", ""), self.user_cache.cache)

            if user_id == self.config.user_id:
                i_participated = True
            if self.config.user_id in reply.get("text", ""):
                i_was_mentioned = True

            msg_id = f"{channel_id}_{reply['ts']}"
            self.db.upsert_message({
                "id": msg_id,
                "channel_id": channel_id,
                "channel_name": channel_name,
                "thread_ts": root_ts if reply["ts"] != root_ts else None,
                "user_id": user_id,
                "user_name": user_name,
                "text": text,
                "ts": reply_ts,
                "permalink": reply.get("permalink", ""),
                "mentions_me": self.config.user_id in reply.get("text", ""),
                "source_type": source_type,
                "fetched_at": datetime.utcnow().isoformat(),
            })

        # Upsert thread record
        root_user = self.user_cache.get_name(root_msg.get("user", ""))
        root_text = resolve_slack_text(root_msg.get("text", ""), self.user_cache.cache)

        self.db.upsert_thread({
            "id": f"{channel_id}_{root_ts}",
            "channel_id": channel_id,
            "channel_name": channel_name,
            "root_ts": root_ts,
            "root_user": root_user,
            "root_text": truncate_text(root_text),
            "reply_count": len(replies) - 1,
            "i_participated": i_participated,
            "i_was_mentioned": i_was_mentioned,
            "source_type": source_type,
            "last_reply_ts": last_reply_ts,
        })

    def _ingest_todo_reactions(self) -> None:
        """Check for :todo: emoji reactions to capture false negatives."""
        try:
            self.rate_limiter.wait_if_needed()
            result = self.client.reactions_list(user=self.config.user_id, count=20)
            items = result.get("items", [])

            for item in items:
                if item.get("type") != "message":
                    continue
                message = item.get("message", {})
                reactions = message.get("reactions", [])
                has_todo = any(
                    r.get("name") in ("todo", "point_right", "white_check_mark")
                    and self.config.user_id in r.get("users", [])
                    for r in reactions
                )
                if has_todo:
                    channel = item.get("channel", "")
                    ts = message.get("ts", "")
                    thread_id = f"{channel}_{ts}"

                    # Check if thread is already classified as action_required
                    existing = self.db.conn.execute(
                        "SELECT classification FROM threads WHERE id = ?",
                        (thread_id,),
                    ).fetchone()

                    if existing and existing["classification"] != "action_required":
                        # Force reclassify
                        self.db.update_thread_classification(
                            thread_id, "action_required",
                            "Manually flagged via :todo: reaction"
                        )
                        logger.info(f"Force-classified thread {thread_id} via reaction")

        except SlackApiError as e:
            logger.debug(f"Could not fetch reactions: {e}")

    # ── Channel discovery (for interactive setup) ───────────────────────

    def list_user_channels(self) -> list[dict]:
        """List all channels the user is a member of, sorted by activity.

        Uses users_conversations instead of conversations_list to work
        on Enterprise Grid workspaces where the latter is restricted.
        """
        channels = []
        cursor = None

        while True:
            self.rate_limiter.wait_if_needed()
            kwargs = {
                "types": "public_channel,private_channel",
                "limit": 200,
                "exclude_archived": True,
            }
            if cursor:
                kwargs["cursor"] = cursor

            result = self.client.users_conversations(**kwargs)

            for ch in result.get("channels", []):
                channels.append({
                    "id": ch["id"],
                    "name": f"#{ch['name']}",
                    "num_members": ch.get("num_members", 0),
                    "topic": ch.get("topic", {}).get("value", ""),
                })

            cursor = result.get("response_metadata", {}).get("next_cursor")
            if not cursor:
                break

        return sorted(channels, key=lambda c: c["num_members"], reverse=True)

    def list_user_dms(self) -> list[dict]:
        """List DM conversations for interactive setup."""
        dms = []

        # 1:1 DMs
        self.rate_limiter.wait_if_needed()
        result = self.client.users_conversations(types="im", limit=200)
        for im in result.get("channels", []):
            user_id = im.get("user", "")
            if user_id and user_id != self.config.user_id:
                name = self.user_cache.get_name(user_id)
                dms.append({
                    "id": im["id"],
                    "name": name,
                    "type": "im",
                })

        # Group DMs
        self.rate_limiter.wait_if_needed()
        result = self.client.users_conversations(types="mpim", limit=200)
        for mpim in result.get("channels", []):
            dms.append({
                "id": mpim["id"],
                "name": mpim.get("name", mpim["id"]),
                "type": "mpim",
            })

        return dms
