"""Ollama local LLM provider — for air-gapped or privacy-sensitive environments."""

from __future__ import annotations

import json
import logging

from . import Classification, TodoExtraction, ResolutionCheck

logger = logging.getLogger(__name__)


class OllamaProvider:
    """Local LLM via Ollama. Lower quality but zero data leaves the machine."""

    def __init__(self, model: str = "llama3:70b", host: str = "http://localhost:11434"):
        self.model = model
        self.host = host
        self._client = None

    @property
    def client(self):
        if self._client is None:
            try:
                import ollama
                self._client = ollama.Client(host=self.host)
            except ImportError:
                raise RuntimeError(
                    "ollama package not installed. Run: pip install ollama"
                )
        return self._client

    async def classify(
        self,
        threads: list[dict],
        user_name: str,
        user_id: str,
        corrections: list[dict] | None = None,
    ) -> list[Classification]:
        if not threads:
            return []

        threads_block = "\n".join(
            f"Thread {t['id']}: [{t.get('channel_name', '')}] "
            f"{t.get('root_user', '')}: {t.get('root_text', '')[:300]}"
            for t in threads
        )

        prompt = (
            f"Classify each Slack thread for {user_name} as: "
            f"action_required, awaiting_response, fyi, or noise.\n"
            f"Return JSON array: [{{\"thread_id\": ..., \"classification\": ..., "
            f"\"summary\": ..., \"todo\": null|{{\"title\": ..., \"context\": ..., "
            f"\"urgency\": ..., \"due_date\": ...}}}}]\n\n{threads_block}"
        )

        try:
            response = self.client.chat(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                format="json",
            )
            text = response["message"]["content"].strip()
            results = json.loads(text)
            if isinstance(results, dict):
                results = results.get("threads", results.get("results", [results]))

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
                    thread_id=r.get("thread_id", ""),
                    classification=r.get("classification", "noise"),
                    summary=r.get("summary", ""),
                    reasoning=r.get("reasoning", ""),
                    todo=todo,
                ))
            return classifications
        except Exception as e:
            logger.error(f"Ollama classification failed: {e}")
            return []

    async def summarize(
        self,
        threads: list[dict],
        window_label: str,
        user_name: str,
    ) -> str:
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
            response = self.client.chat(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
            )
            return response["message"]["content"].strip()
        except Exception as e:
            logger.error(f"Ollama summarization failed: {e}")
            return "Summary generation failed."

    async def check_resolution(
        self,
        todo: dict,
        recent_messages: list[dict],
    ) -> ResolutionCheck:
        messages_block = "\n".join(
            f"[{m.get('user_name', '?')}]: {m.get('text', '')[:300]}"
            for m in recent_messages[-10:]
        )
        prompt = (
            f"Is this TODO resolved?\nTitle: {todo.get('title', '')}\n"
            f"Recent messages:\n{messages_block}\n"
            f"Return JSON: {{\"resolved\": true/false, \"reason\": \"...\"}}"
        )
        try:
            response = self.client.chat(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                format="json",
            )
            result = json.loads(response["message"]["content"].strip())
            return ResolutionCheck(
                resolved=result.get("resolved", False),
                reason=result.get("reason", ""),
            )
        except Exception as e:
            logger.error(f"Ollama resolution check failed: {e}")
            return ResolutionCheck(resolved=False)
