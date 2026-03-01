"""
Slackhub configuration management
"""

import os
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Config:
    # Slack credentials
    slack_bot_token: str
    slack_signing_secret: str
    slack_app_token: Optional[str] = None

    # GitHub credentials
    github_token: str = ""
    github_webhook_secret: str = ""
    github_app_id: Optional[str] = None
    github_private_key_path: Optional[str] = None

    # Channel mappings: GitHub repo -> Slack channel
    repo_channel_map: dict = field(default_factory=dict)

    # Application settings
    debug: bool = False
    log_level: str = "INFO"
    port: int = 3000

    @classmethod
    def from_env(cls) -> "Config":
        """Load configuration from environment variables."""
        repo_channel_map = {}
        mapping_raw = os.environ.get("REPO_CHANNEL_MAP", "")
        for pair in mapping_raw.split(","):
            pair = pair.strip()
            if ":" in pair:
                repo, channel = pair.split(":", 1)
                repo_channel_map[repo.strip()] = channel.strip()

        return cls(
            slack_bot_token=os.environ.get("SLACK_BOT_TOKEN", ""),
            slack_signing_secret=os.environ.get("SLACK_SIGNING_SECRET", ""),
            slack_app_token=os.environ.get("SLACK_APP_TOKEN"),
            github_token=os.environ.get("GITHUB_TOKEN", ""),
            github_webhook_secret=os.environ.get("GITHUB_WEBHOOK_SECRET", ""),
            github_app_id=os.environ.get("GITHUB_APP_ID"),
            github_private_key_path=os.environ.get("GITHUB_PRIVATE_KEY_PATH"),
            repo_channel_map=repo_channel_map,
            debug=os.environ.get("DEBUG", "false").lower() == "true",
            log_level=os.environ.get("LOG_LEVEL", "INFO"),
            port=int(os.environ.get("PORT", "3000")),
        )

    def get_channel_for_repo(self, repo_full_name: str) -> Optional[str]:
        """Return the Slack channel mapped to a GitHub repository."""
        return self.repo_channel_map.get(repo_full_name)
