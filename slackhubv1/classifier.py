"""Classification module — orchestrates LLM providers for thread triage and TODO extraction."""

from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import datetime
from typing import Optional

from .config import Config
from .db import Database
from .llm import Classification, TodoExtraction

logger = logging.getLogger(__name__)


def _make_openai_provider(config: Config, classification_model: str, summary_model: str):
    """Helper to create an OpenAI provider instance."""
    from .llm.openai_provider import OpenAIProvider
    return OpenAIProvider(
        api_key=config.llm.openai_api_key,
        classification_model=classification_model,
        summary_model=summary_model,
        base_url=config.llm.openai_base_url or None,
    )


def _get_classification_provider(config: Config):
    """Instantiate the provider configured for classification."""
    task = config.llm.classification
    if task.provider == "google":
        from .llm.google_provider import GoogleProvider
        return GoogleProvider(
            api_key=config.llm.google_api_key,
            model=task.model,
        )
    elif task.provider == "anthropic":
        from .llm.anthropic_provider import AnthropicProvider
        return AnthropicProvider(
            api_key=config.llm.anthropic_api_key,
            extraction_model=task.model,
            summary_model=config.llm.summarization.model,
        )
    elif task.provider == "openai":
        return _make_openai_provider(config, task.model, config.llm.summarization.model)
    else:
        from .llm.ollama_provider import OllamaProvider
        return OllamaProvider(model=task.model)


def _get_extraction_provider(config: Config):
    """Instantiate the provider configured for TODO extraction."""
    task = config.llm.extraction
    if task.provider == "anthropic":
        from .llm.anthropic_provider import AnthropicProvider
        return AnthropicProvider(
            api_key=config.llm.anthropic_api_key,
            extraction_model=task.model,
            summary_model=config.llm.summarization.model,
        )
    elif task.provider == "google":
        from .llm.google_provider import GoogleProvider
        return GoogleProvider(api_key=config.llm.google_api_key, model=task.model)
    elif task.provider == "openai":
        return _make_openai_provider(config, task.model, config.llm.summarization.model)
    else:
        from .llm.ollama_provider import OllamaProvider
        return OllamaProvider(model=task.model)


def _get_summary_provider(config: Config):
    """Instantiate the provider configured for summarization."""
    task = config.llm.summarization
    if task.provider == "anthropic":
        from .llm.anthropic_provider import AnthropicProvider
        return AnthropicProvider(
            api_key=config.llm.anthropic_api_key,
            extraction_model=config.llm.extraction.model,
            summary_model=task.model,
        )
    elif task.provider == "google":
        from .llm.google_provider import GoogleProvider
        return GoogleProvider(api_key=config.llm.google_api_key, model=task.model)
    elif task.provider == "openai":
        return _make_openai_provider(config, config.llm.classification.model, task.model)
    else:
        from .llm.ollama_provider import OllamaProvider
        return OllamaProvider(model=task.model)


def _get_resolution_provider(config: Config):
    """Instantiate the provider configured for resolution detection."""
    task = config.llm.resolution
    if task.provider == "google":
        from .llm.google_provider import GoogleProvider
        return GoogleProvider(api_key=config.llm.google_api_key, model=task.model)
    elif task.provider == "anthropic":
        from .llm.anthropic_provider import AnthropicProvider
        return AnthropicProvider(
            api_key=config.llm.anthropic_api_key,
            extraction_model=task.model,
            summary_model=config.llm.summarization.model,
        )
    elif task.provider == "openai":
        return _make_openai_provider(config, task.model, config.llm.summarization.model)
    else:
        from .llm.ollama_provider import OllamaProvider
        return OllamaProvider(model=task.model)


def compute_fingerprint(title: str, channel_id: str, created_at: str) -> str:
    """Compute deduplication fingerprint for a TODO.

    Uses SHA-256 of normalized title + channel + 3-day date bucket.
    """
    # Normalize title: lowercase, strip punctuation, collapse whitespace
    normalized_title = " ".join(title.lower().split())
    # 3-day bucket
    try:
        dt = datetime.fromisoformat(created_at)
        day_bucket = (dt.toordinal() // 3) * 3
    except (ValueError, TypeError):
        day_bucket = 0

    raw = f"{normalized_title}|{channel_id}|{day_bucket}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


class Classifier:
    """Orchestrates classification, TODO extraction, and resolution detection."""

    def __init__(self, config: Config, db: Database):
        self.config = config
        self.db = db

    def classify_unclassified(
        self,
        corrections: list[dict] | None = None,
        dry_run: bool = False,
    ) -> dict[str, int]:
        """Classify all unclassified threads.

        Returns dict with counts per classification category.
        """
        threads = self.db.get_unclassified_threads(limit=100)
        if not threads:
            logger.info("No unclassified threads found.")
            return {}

        logger.info(f"Classifying {len(threads)} threads...")
        provider = _get_classification_provider(self.config)

        classifications = asyncio.run(
            provider.classify(
                threads=threads,
                user_name=self.config.user_display_name,
                user_id=self.config.user_id,
                corrections=corrections,
            )
        )

        stats: dict[str, int] = {}
        todos_created = 0

        with self.db.transaction():
            for cls in classifications:
                cat = cls.classification
                stats[cat] = stats.get(cat, 0) + 1

                if not dry_run:
                    self.db.update_thread_classification(
                        thread_id=cls.thread_id,
                        classification=cat,
                        summary=cls.summary,
                    )

                    # Extract TODO if present
                    if cls.todo and cat in ("action_required", "awaiting_response"):
                        todo_created = self._create_todo(cls)
                        if todo_created:
                            todos_created += 1

        stats["todos_created"] = todos_created
        logger.info(f"Classification complete: {stats}")
        return stats

    def _create_todo(self, cls: Classification) -> bool:
        """Create a TODO from a classification result. Returns True if created."""
        if not cls.todo:
            return False

        # Find the thread to get source details
        thread = self.db.conn.execute(
            "SELECT * FROM threads WHERE id = ?", (cls.thread_id,)
        ).fetchone()

        now = datetime.utcnow().isoformat()
        channel_id = dict(thread)["channel_id"] if thread else ""

        fingerprint = compute_fingerprint(
            cls.todo.title, channel_id, now
        )

        todo_id = self.db.insert_todo({
            "source_thread_id": cls.thread_id,
            "source_permalink": "",  # Will be enriched if available
            "title": cls.todo.title,
            "context": cls.todo.context,
            "source_message": dict(thread).get("root_text", "") if thread else "",
            "source_author": dict(thread).get("root_user", "") if thread else "",
            "owner": self.config.user_display_name,
            "due_date": cls.todo.due_date,
            "urgency": cls.todo.urgency,
            "status": "open",
            "fingerprint": fingerprint,
            "created_at": now,
            "updated_at": now,
        })

        if todo_id:
            logger.info(f"Created TODO-{todo_id:04d}: {cls.todo.title}")
            return True
        else:
            logger.debug(f"Duplicate TODO skipped: {cls.todo.title}")
            return False

    def check_resolutions(self) -> int:
        """Check open TODOs for resolution. Returns count resolved."""
        open_todos = self.db.get_open_todos()
        if not open_todos:
            return 0

        provider = _get_resolution_provider(self.config)
        resolved_count = 0

        for todo in open_todos:
            thread_id = todo.get("source_thread_id")
            if not thread_id:
                continue

            # Parse thread_id to get channel_id and thread_ts
            parts = thread_id.rsplit("_", 1)
            if len(parts) != 2:
                continue
            channel_id, thread_ts = parts

            messages = self.db.get_messages_for_thread(channel_id, thread_ts)
            if not messages:
                continue

            result = asyncio.run(
                provider.check_resolution(todo, messages)
            )

            if result.resolved:
                self.db.update_todo_status(todo["id"], "auto-resolved")
                logger.info(
                    f"Auto-resolved TODO-{todo['id']:04d}: {result.reason}"
                )
                resolved_count += 1

        return resolved_count

    def mark_stale(self) -> int:
        """Mark old open TODOs as stale. Returns count marked."""
        stale = self.db.get_stale_todos(
            days=self.config.todo.auto_complete_after_days
        )
        count = 0
        for todo in stale:
            self.db.update_todo_status(todo["id"], "stale")
            count += 1
        if count:
            logger.info(f"Marked {count} TODOs as stale")
        return count

    def generate_summary(
        self,
        start: datetime,
        end: datetime,
        window_label: str = "",
    ) -> str:
        """Generate a narrative summary for a time window."""
        threads = self.db.get_threads_in_window(start, end)
        classified = [t for t in threads if t.get("classification")]

        if not classified:
            return "No notable activity in this period."

        provider = _get_summary_provider(self.config)
        if not window_label:
            window_label = f"{start.strftime('%I:%M %p')} to {end.strftime('%I:%M %p')}"

        return asyncio.run(
            provider.summarize(classified, window_label, self.config.user_display_name)
        )
