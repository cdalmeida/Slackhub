"""LLM provider abstraction layer."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Protocol


@dataclass
class Classification:
    thread_id: str
    classification: str  # action_required, awaiting_response, fyi, noise
    summary: str
    reasoning: str = ""
    todo: Optional["TodoExtraction"] = None


@dataclass
class TodoExtraction:
    title: str
    context: str
    urgency: str = "medium"  # high, medium, low
    due_date: Optional[str] = None


@dataclass
class ResolutionCheck:
    resolved: bool
    reason: str = ""


class LLMProvider(Protocol):
    """Protocol for LLM provider implementations."""

    async def classify(
        self,
        threads: list[dict],
        user_name: str,
        user_id: str,
        corrections: list[dict] | None = None,
    ) -> list[Classification]:
        """Classify threads into action taxonomy."""
        ...

    async def summarize(
        self,
        threads: list[dict],
        window_label: str,
        user_name: str,
    ) -> str:
        """Generate a narrative summary of threads."""
        ...

    async def check_resolution(
        self,
        todo: dict,
        recent_messages: list[dict],
    ) -> ResolutionCheck:
        """Check if a TODO has been resolved based on recent thread activity."""
        ...
