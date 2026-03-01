"""
Data models for Slackhub message processing
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class GitHubReference:
    """Represents a reference to a GitHub issue or pull request."""
    owner: str
    repo: str
    number: int

    def __str__(self) -> str:
        return f"{self.owner}/{self.repo}#{self.number}"


@dataclass
class SlackMessage:
    """Represents an incoming Slack message that may contain GitHub references."""
    channel: str
    user: str
    text: str
    ts: str
    thread_ts: Optional[str] = None
    references: list[GitHubReference] = field(default_factory=list)

    @property
    def is_threaded(self) -> bool:
        return self.thread_ts is not None and self.thread_ts != self.ts


@dataclass
class NotificationPayload:
    """Represents a notification to be sent to a Slack channel."""
    channel: str
    text: str
    blocks: Optional[list] = None
    thread_ts: Optional[str] = None
    repo_full_name: str = ""
    event_type: str = ""
    event_action: str = ""
