"""OpenAI LLM provider — GPT-4o for summarization, GPT-4o-mini for classification/extraction."""

from __future__ import annotations

import json
import logging
from typing import Optional

from . import Classification, TodoExtraction, ResolutionCheck

logger = logging.getLogger(__name__)


CLASSIFICATION_PROMPT = """You are an executive assistant triaging Slack threads for a Group Product Manager named {user_name} (user_id: {user_id}).

For each thread, return a JSON array of objects with these fields:
- thread_id: the thread ID provided
- classification: one of "action_required", "awaiting_response", "fyi", "noise"
- summary: 1-2 sentence summary
- reasoning: brief explanation of your classification
- todo: null OR an object with {{ "title": str, "context": str, "urgency": "high"|"medium"|"low", "due_date": str|null }}

Classification definitions:
- action_required: {user_name} was asked to do something, approve something, make a decision, or provide input by a deadline
- awaiting_response: {user_name} was tagged or asked a direct question and hasn't replied
- fyi: {user_name} was CC'd or the topic is relevant but no action needed
- noise: General chatter, off-topic, already resolved, bot notifications

{corrections_block}

Return ONLY valid JSON — no markdown, no backticks, no extra text.

Threads to classify:
{threads_block}"""

SUMMARY_PROMPT = """You are writing a brief digest summary for a Group Product Manager named {user_name}.

Summarize the following Slack activity from {window_label} in 3-5 sentences. Focus on:
1. New action items that came in
2. Threads that were resolved
3. Notable developments or decisions

Be concise and specific. Use names and channel references where helpful.

Activity:
{threads_block}"""

RESOLUTION_PROMPT = """Given this TODO item:
Title: "{title}"
Context: "{context}"
Source message: "{source_message}"

And the latest thread activity:
{messages_block}

Has this item been resolved, completed, or made irrelevant?
Signals of resolution: the user replied addressing the request, someone confirmed completion, the thread went inactive for 48+ hours, or the request was explicitly cancelled.

Return ONLY JSON: {{ "resolved": true|false, "reason": "..." }}"""


class OpenAIProvider:
    """OpenAI API provider for GPT models."""

    def __init__(
        self,
        api_key: str,
        classification_model: str = "gpt-4o-mini",
        summary_model: str = "gpt-4o",
        base_url: Optional[str] = None,
    ):
        import openai

        kwargs = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        self.client = openai.OpenAI(**kwargs)
        self.classification_model = classification_model
        self.summary_model = summary_model

    async def classify(
        self,
        threads: list[dict],
        user_name: str,
        user_id: str,
        corrections: list[dict] | None = None,
    ) -> list[Classification]:
        """Classify threads using GPT-4o-mini."""
        if not threads:
            return []

        corrections_block = ""
        if corrections:
            corrections_block = (
                "IMPORTANT — Learn from these past corrections:\n\n"
            )
            for c in corrections[:20]:
                corrections_block += (
                    f"Thread: \"{c.get('source_message', '')[:200]}\"\n"
                    f"Channel: {c.get('source_channel', '')}\n"
                    f"System classified as: {c.get('original_classification', '')}\n"
                    f"User correction: {c.get('correction_notes', '')}\n\n"
                )

        threads_block = ""
        for t in threads:
            threads_block += (
                f"\n--- Thread {t['id']} ---\n"
                f"Channel: {t.get('channel_name', '')}\n"
                f"Root message by {t.get('root_user', 'unknown')}: "
                f"{t.get('root_text', '')}\n"
                f"Replies: {t.get('reply_count', 0)}\n"
                f"I participated: {t.get('i_participated', False)}\n"
                f"I was mentioned: {t.get('i_was_mentioned', False)}\n"
            )

        prompt = CLASSIFICATION_PROMPT.format(
            user_name=user_name,
            user_id=user_id,
            corrections_block=corrections_block,
            threads_block=threads_block,
        )

        try:
            response = self.client.chat.completions.create(
                model=self.classification_model,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                max_tokens=4096,
            )
            text = response.choices[0].message.content.strip()
            # OpenAI json_object mode wraps arrays in an object sometimes
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                # Try common wrapper keys
                results = (
                    parsed.get("threads")
                    or parsed.get("results")
                    or parsed.get("classifications")
                    or [parsed]
                )
            else:
                results = parsed

            classifications = []
            for r in results:
                todo = None
                if r.get("todo"):
                    todo = TodoExtraction(
                        title=r["todo"]["title"],
                        context=r["todo"].get("context", ""),
                        urgency=r["todo"].get("urgency", "medium"),
                        due_date=r["todo"].get("due_date"),
                    )
                classifications.append(Classification(
                    thread_id=r["thread_id"],
                    classification=r["classification"],
                    summary=r.get("summary", ""),
                    reasoning=r.get("reasoning", ""),
                    todo=todo,
                ))
            return classifications

        except (json.JSONDecodeError, KeyError, IndexError) as e:
            logger.error(f"Failed to parse OpenAI classification response: {e}")
            return []
        except Exception as e:
            logger.error(f"OpenAI API error during classification: {e}")
            return []

    async def summarize(
        self,
        threads: list[dict],
        window_label: str,
        user_name: str,
    ) -> str:
        """Generate narrative summary using GPT-4o."""
        if not threads:
            return "No notable activity in this period."

        threads_block = ""
        for t in threads:
            cls = t.get("classification", "unclassified")
            threads_block += (
                f"[{cls}] #{t.get('channel_name', '')}: "
                f"{t.get('summary', t.get('root_text', '')[:200])}\n"
            )

        prompt = SUMMARY_PROMPT.format(
            user_name=user_name,
            window_label=window_label,
            threads_block=threads_block,
        )

        try:
            response = self.client.chat.completions.create(
                model=self.summary_model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1024,
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            logger.error(f"OpenAI API error during summarization: {e}")
            return "Summary generation failed."

    async def check_resolution(
        self,
        todo: dict,
        recent_messages: list[dict],
    ) -> ResolutionCheck:
        """Check if a TODO is resolved using GPT-4o-mini."""
        messages_block = ""
        for msg in recent_messages[-10:]:
            messages_block += (
                f"[{msg.get('user_name', 'unknown')}]: {msg.get('text', '')[:300]}\n"
            )

        prompt = RESOLUTION_PROMPT.format(
            title=todo.get("title", ""),
            context=todo.get("context", ""),
            source_message=todo.get("source_message", "")[:300],
            messages_block=messages_block,
        )

        try:
            response = self.client.chat.completions.create(
                model=self.classification_model,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                max_tokens=256,
            )
            text = response.choices[0].message.content.strip()
            result = json.loads(text)
            return ResolutionCheck(
                resolved=result.get("resolved", False),
                reason=result.get("reason", ""),
            )
        except Exception as e:
            logger.error(f"OpenAI resolution check failed: {e}")
            return ResolutionCheck(resolved=False, reason=f"Check failed: {e}")
