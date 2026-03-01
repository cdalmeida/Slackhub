"""Google Gemini LLM provider — Flash for classification and resolution detection."""

from __future__ import annotations

import json
import logging

import google.generativeai as genai

from . import Classification, TodoExtraction, ResolutionCheck

logger = logging.getLogger(__name__)


CLASSIFICATION_PROMPT = """You are an executive assistant triaging Slack threads for {user_name} (user_id: {user_id}).

For each thread, return a JSON array of objects:
- thread_id: string
- classification: "action_required" | "awaiting_response" | "fyi" | "noise"
- summary: 1-2 sentence summary
- reasoning: brief explanation
- todo: null OR {{ "title": str, "context": str, "urgency": "high"|"medium"|"low", "due_date": str|null }}

Definitions:
- action_required: asked to do/approve/decide something
- awaiting_response: tagged with a question, hasn't replied
- fyi: CC'd, informational only
- noise: chatter, resolved, bot notifications

{corrections_block}

Return ONLY valid JSON.

Threads:
{threads_block}"""

RESOLUTION_PROMPT = """TODO: "{title}"
Context: "{context}"

Recent thread activity:
{messages_block}

Is this resolved? Return JSON: {{ "resolved": true|false, "reason": "..." }}"""


class GoogleProvider:
    """Google Gemini provider for classification and resolution detection."""

    def __init__(self, api_key: str, model: str = "gemini-2.0-flash"):
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel(model)

    async def classify(
        self,
        threads: list[dict],
        user_name: str,
        user_id: str,
        corrections: list[dict] | None = None,
    ) -> list[Classification]:
        """Classify threads using Gemini Flash."""
        if not threads:
            return []

        corrections_block = ""
        if corrections:
            corrections_block = "Learn from these past corrections:\n\n"
            for c in corrections[:20]:
                corrections_block += (
                    f"Thread: \"{c.get('source_message', '')[:200]}\"\n"
                    f"System classified as: {c.get('original_classification', '')}\n"
                    f"Correct: {c.get('correction_notes', '')}\n\n"
                )

        threads_block = ""
        for t in threads:
            threads_block += (
                f"\n--- Thread {t['id']} ---\n"
                f"Channel: {t.get('channel_name', '')}\n"
                f"Root: {t.get('root_user', 'unknown')}: {t.get('root_text', '')}\n"
                f"Replies: {t.get('reply_count', 0)} | "
                f"Mentioned: {t.get('i_was_mentioned', False)}\n"
            )

        prompt = CLASSIFICATION_PROMPT.format(
            user_name=user_name,
            user_id=user_id,
            corrections_block=corrections_block,
            threads_block=threads_block,
        )

        try:
            response = self.model.generate_content(
                prompt,
                generation_config=genai.types.GenerationConfig(
                    response_mime_type="application/json",
                    max_output_tokens=4096,
                ),
            )
            text = response.text.strip()
            results = json.loads(text)

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

        except (json.JSONDecodeError, KeyError) as e:
            logger.error(f"Failed to parse Gemini classification response: {e}")
            return []
        except Exception as e:
            logger.error(f"Gemini API error during classification: {e}")
            return []

    async def check_resolution(
        self,
        todo: dict,
        recent_messages: list[dict],
    ) -> ResolutionCheck:
        """Check resolution using Gemini Flash."""
        messages_block = ""
        for msg in recent_messages[-10:]:
            messages_block += (
                f"[{msg.get('user_name', 'unknown')}]: {msg.get('text', '')[:300]}\n"
            )

        prompt = RESOLUTION_PROMPT.format(
            title=todo.get("title", ""),
            context=todo.get("context", ""),
            messages_block=messages_block,
        )

        try:
            response = self.model.generate_content(
                prompt,
                generation_config=genai.types.GenerationConfig(
                    response_mime_type="application/json",
                    max_output_tokens=256,
                ),
            )
            result = json.loads(response.text.strip())
            return ResolutionCheck(
                resolved=result.get("resolved", False),
                reason=result.get("reason", ""),
            )
        except Exception as e:
            logger.error(f"Gemini resolution check failed: {e}")
            return ResolutionCheck(resolved=False, reason=f"Check failed: {e}")

    async def summarize(
        self,
        threads: list[dict],
        window_label: str,
        user_name: str,
    ) -> str:
        """Summarize using Gemini (fallback if Anthropic unavailable)."""
        if not threads:
            return "No notable activity."

        threads_text = "\n".join(
            f"[{t.get('classification', '?')}] #{t.get('channel_name', '')}: "
            f"{t.get('summary', t.get('root_text', '')[:200])}"
            for t in threads
        )

        prompt = (
            f"Summarize this Slack activity for {user_name} from {window_label} "
            f"in 3-5 sentences:\n\n{threads_text}"
        )

        try:
            response = self.model.generate_content(prompt)
            return response.text.strip()
        except Exception as e:
            logger.error(f"Gemini summarization failed: {e}")
            return "Summary generation failed."
