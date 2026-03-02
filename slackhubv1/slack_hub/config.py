"""Configuration loader and validation for Slack Hub."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml


CONFIG_SEARCH_PATHS = [
    Path("config/config.yaml"),
    Path("~/.slack-hub/config.yaml").expanduser(),
    Path(os.environ.get("SLACK_HUB_CONFIG", "config/config.yaml")),
]


@dataclass
class ChannelEntry:
    name: str
    id: str


@dataclass
class DMEntry:
    name: str
    id: str


@dataclass
class PollingTier:
    interval_min: int


@dataclass
class PollingSchedule:
    active_hours: str = "08:00-19:00"
    evening_hours: str = "19:00-22:00"
    overnight: str = "22:00-08:00"
    timezone: str = "America/Los_Angeles"


@dataclass
class LLMTask:
    provider: str
    model: str


@dataclass
class LLMConfig:
    classification: LLMTask = field(
        default_factory=lambda: LLMTask("google", "gemini-2.0-flash")
    )
    extraction: LLMTask = field(
        default_factory=lambda: LLMTask("anthropic", "claude-haiku-4-5-20251001")
    )
    summarization: LLMTask = field(
        default_factory=lambda: LLMTask("anthropic", "claude-sonnet-4-5-20250929")
    )
    resolution: LLMTask = field(
        default_factory=lambda: LLMTask("google", "gemini-2.0-flash")
    )
    anthropic_api_key: str = ""
    google_api_key: str = ""
    openai_api_key: str = ""
    openai_base_url: str = ""  # For Azure OpenAI or internal gateway


@dataclass
class DirectMessagesConfig:
    enabled: bool = False
    mode: str = "allowlist"
    use_llm: bool = True
    polling_interval_min: int = 10
    allowlist: list[DMEntry] = field(default_factory=list)


@dataclass
class EmailDigestConfig:
    enabled: bool = True
    send_time: str = "07:00"
    days: list[str] = field(
        default_factory=lambda: ["mon", "tue", "wed", "thu", "fri"]
    )


@dataclass
class HourlyPulseConfig:
    enabled: bool = True
    start_hour: int = 11
    end_hour: int = 17
    skip_if_empty: bool = True
    min_notable_items: int = 1
    collapse_quiet_channels: bool = True
    quiet_channel_threshold: int = 3
    days: list[str] = field(
        default_factory=lambda: ["mon", "tue", "wed", "thu", "fri"]
    )


@dataclass
class SMTPConfig:
    host: str = ""
    port: int = 587
    use_tls: bool = True


@dataclass
class EmailConfig:
    daily_digest: EmailDigestConfig = field(default_factory=EmailDigestConfig)
    hourly_pulse: HourlyPulseConfig = field(default_factory=HourlyPulseConfig)
    method: str = "gmail_api"
    recipient: str = ""
    timezone: str = "America/Los_Angeles"
    smtp: SMTPConfig = field(default_factory=SMTPConfig)


@dataclass
class TodoConfig:
    auto_complete_after_days: int = 14
    sheet_id: str = ""
    sheet_name: str = "Slack Hub TODOs"
    google_credentials_path: str = "~/.slack-hub/google-creds.json"
    webhook_url: str = ""


@dataclass
class Config:
    user_id: str = ""
    user_display_name: str = ""
    channels: dict[str, list[ChannelEntry]] = field(default_factory=lambda: {
        "high_priority": [],
        "medium_priority": [],
        "low_priority": [],
    })
    direct_messages: DirectMessagesConfig = field(default_factory=DirectMessagesConfig)
    polling: dict = field(default_factory=dict)
    polling_schedule: PollingSchedule = field(default_factory=PollingSchedule)
    polling_tiers: dict[str, PollingTier] = field(default_factory=lambda: {
        "high_priority": PollingTier(10),
        "medium_priority": PollingTier(30),
        "low_priority": PollingTier(60),
    })
    llm: LLMConfig = field(default_factory=LLMConfig)
    todo: TodoConfig = field(default_factory=TodoConfig)
    email: EmailConfig = field(default_factory=EmailConfig)
    lookback_hours: int = 8
    thread_depth: int = 50
    db_path: str = "~/.slack-hub/slack_hub.db"
    log_level: str = "INFO"
    slack_token: str = ""

    @property
    def db_path_resolved(self) -> Path:
        return Path(self.db_path).expanduser()

    @property
    def all_channels(self) -> list[ChannelEntry]:
        """Flat list of all configured channels across all tiers."""
        result = []
        for tier in ["high_priority", "medium_priority", "low_priority"]:
            result.extend(self.channels.get(tier, []))
        return result

    @property
    def all_dm_conversations(self) -> list[DMEntry]:
        """Flat list of all allowlisted DM conversations."""
        if not self.direct_messages.enabled:
            return []
        return self.direct_messages.allowlist

    def get_tier_for_channel(self, channel_id: str) -> Optional[str]:
        """Return the priority tier for a given channel ID."""
        for tier, channels in self.channels.items():
            for ch in channels:
                if ch.id == channel_id:
                    return tier
        return None

    def get_polling_interval(self, channel_id: str) -> int:
        """Return polling interval in minutes for a channel."""
        tier = self.get_tier_for_channel(channel_id)
        if tier and tier in self.polling_tiers:
            return self.polling_tiers[tier].interval_min
        return 60  # default fallback


def _parse_channels(raw: dict) -> dict[str, list[ChannelEntry]]:
    result = {}
    for tier in ["high_priority", "medium_priority", "low_priority"]:
        entries = raw.get(tier, [])
        if isinstance(entries, list):
            result[tier] = [
                ChannelEntry(name=e["name"], id=e["id"])
                for e in entries
                if isinstance(e, dict) and "name" in e and "id" in e
            ]
        else:
            result[tier] = []
    return result


def _parse_dm_allowlist(raw: list) -> list[DMEntry]:
    if not isinstance(raw, list):
        return []
    return [
        DMEntry(name=e["name"], id=e["id"])
        for e in raw
        if isinstance(e, dict) and "name" in e and "id" in e
    ]


def _parse_llm_task(raw: dict) -> LLMTask:
    return LLMTask(
        provider=raw.get("provider", "anthropic"),
        model=raw.get("model", ""),
    )


def load_config(path: Optional[str | Path] = None) -> Config:
    """Load configuration from YAML file.

    Searches CONFIG_SEARCH_PATHS if no path is specified.
    Falls back to environment variables for sensitive values.
    """
    config_path = None

    if path:
        config_path = Path(path).expanduser()
    else:
        for candidate in CONFIG_SEARCH_PATHS:
            resolved = candidate.expanduser()
            if resolved.exists():
                config_path = resolved
                break

    raw = {}
    if config_path and config_path.exists():
        with open(config_path) as f:
            raw = yaml.safe_load(f) or {}

    # Build config with env var fallbacks
    channels_raw = raw.get("channels", {})
    dm_raw = raw.get("direct_messages", {})
    llm_raw = raw.get("llm", {})

    # Only override LLM task defaults if the config file actually specifies them
    llm_config = LLMConfig(
        anthropic_api_key=(
            llm_raw.get("anthropic_api_key", "")
            or os.environ.get("ANTHROPIC_API_KEY", "")
        ),
        google_api_key=(
            llm_raw.get("google_api_key", "")
            or os.environ.get("GOOGLE_API_KEY", "")
        ),
        openai_api_key=(
            llm_raw.get("openai_api_key", "")
            or os.environ.get("OPENAI_API_KEY", "")
        ),
        openai_base_url=(
            llm_raw.get("openai_base_url", "")
            or os.environ.get("OPENAI_BASE_URL", "")
        ),
    )
    if "classification" in llm_raw:
        llm_config.classification = _parse_llm_task(llm_raw["classification"])
    if "extraction" in llm_raw:
        llm_config.extraction = _parse_llm_task(llm_raw["extraction"])
    if "summarization" in llm_raw:
        llm_config.summarization = _parse_llm_task(llm_raw["summarization"])
    if "resolution" in llm_raw:
        llm_config.resolution = _parse_llm_task(llm_raw["resolution"])
    todo_raw = raw.get("todo", {})
    email_raw = raw.get("email", {})
    polling_raw = raw.get("polling", {})

    config = Config(
        user_id=raw.get("user_id", ""),
        user_display_name=raw.get("user_display_name", ""),
        channels=_parse_channels(channels_raw),
        direct_messages=DirectMessagesConfig(
            enabled=dm_raw.get("enabled", False),
            mode=dm_raw.get("mode", "allowlist"),
            use_llm=dm_raw.get("use_llm", True),
            polling_interval_min=dm_raw.get("polling_interval_min", 10),
            allowlist=_parse_dm_allowlist(dm_raw.get("allowlist", [])),
        ),
        polling_tiers={
            tier: PollingTier(
                interval_min=polling_raw.get("tiers", {})
                .get(tier, {})
                .get("interval_min", default)
            )
            for tier, default in [
                ("high_priority", 10),
                ("medium_priority", 30),
                ("low_priority", 60),
            ]
        },
        polling_schedule=PollingSchedule(
            active_hours=polling_raw.get("schedule", {}).get(
                "active_hours", "08:00-19:00"
            ),
            evening_hours=polling_raw.get("schedule", {}).get(
                "evening_hours", "19:00-22:00"
            ),
            overnight=polling_raw.get("schedule", {}).get(
                "overnight", "22:00-08:00"
            ),
            timezone=polling_raw.get("schedule", {}).get(
                "timezone", "America/Los_Angeles"
            ),
        ),
        llm=llm_config,
        todo=TodoConfig(
            auto_complete_after_days=todo_raw.get("auto_complete_after_days", 14),
            sheet_id=todo_raw.get("sheet_id", ""),
            sheet_name=todo_raw.get("sheet_name", "Slack Hub TODOs"),
            google_credentials_path=todo_raw.get(
                "google_credentials_path", "~/.slack-hub/google-creds.json"
            ),
            webhook_url=todo_raw.get("webhook_url", ""),
        ),
        email=EmailConfig(
            daily_digest=EmailDigestConfig(
                enabled=email_raw.get("daily_digest", {}).get("enabled", True),
                send_time=email_raw.get("daily_digest", {}).get("send_time", "07:00"),
                days=email_raw.get("daily_digest", {}).get(
                    "days", ["mon", "tue", "wed", "thu", "fri"]
                ),
            ),
            hourly_pulse=HourlyPulseConfig(
                enabled=email_raw.get("hourly_pulse", {}).get("enabled", True),
                start_hour=email_raw.get("hourly_pulse", {}).get("start_hour", 11),
                end_hour=email_raw.get("hourly_pulse", {}).get("end_hour", 17),
                skip_if_empty=email_raw.get("hourly_pulse", {}).get(
                    "skip_if_empty", True
                ),
                min_notable_items=email_raw.get("hourly_pulse", {}).get(
                    "min_notable_items", 1
                ),
                collapse_quiet_channels=email_raw.get("hourly_pulse", {}).get(
                    "collapse_quiet_channels", True
                ),
                quiet_channel_threshold=email_raw.get("hourly_pulse", {}).get(
                    "quiet_channel_threshold", 3
                ),
            ),
            method=email_raw.get("method", "gmail_api"),
            recipient=email_raw.get("recipient", ""),
            timezone=email_raw.get("timezone", "America/Los_Angeles"),
            smtp=SMTPConfig(
                host=email_raw.get("smtp", {}).get("host", ""),
                port=email_raw.get("smtp", {}).get("port", 587),
                use_tls=email_raw.get("smtp", {}).get("use_tls", True),
            ),
        ),
        lookback_hours=raw.get("lookback_hours", 8),
        thread_depth=raw.get("thread_depth", 50),
        db_path=raw.get("db_path", "~/.slack-hub/slack_hub.db"),
        log_level=raw.get("log_level", "INFO"),
        slack_token=(
            raw.get("slack_token", "")
            or os.environ.get("SLACK_HUB_TOKEN", "")
            or os.environ.get("SLACK_TOKEN", "")
        ),
    )

    return config


def save_config(config: Config, path: str | Path) -> None:
    """Serialize a Config back to YAML for the init wizard."""
    path = Path(path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)

    data = {
        "user_id": config.user_id,
        "user_display_name": config.user_display_name,
        "channels": {
            tier: [{"name": ch.name, "id": ch.id} for ch in channels]
            for tier, channels in config.channels.items()
        },
        "direct_messages": {
            "enabled": config.direct_messages.enabled,
            "mode": config.direct_messages.mode,
            "use_llm": config.direct_messages.use_llm,
            "polling_interval_min": config.direct_messages.polling_interval_min,
            "allowlist": [
                {"name": dm.name, "id": dm.id}
                for dm in config.direct_messages.allowlist
            ],
        },
        "polling": {
            "tiers": {
                tier: {"interval_min": pt.interval_min}
                for tier, pt in config.polling_tiers.items()
            },
            "schedule": {
                "active_hours": config.polling_schedule.active_hours,
                "evening_hours": config.polling_schedule.evening_hours,
                "overnight": config.polling_schedule.overnight,
                "timezone": config.polling_schedule.timezone,
            },
        },
        "llm": {
            "classification": {
                "provider": config.llm.classification.provider,
                "model": config.llm.classification.model,
            },
            "extraction": {
                "provider": config.llm.extraction.provider,
                "model": config.llm.extraction.model,
            },
            "summarization": {
                "provider": config.llm.summarization.provider,
                "model": config.llm.summarization.model,
            },
            "resolution": {
                "provider": config.llm.resolution.provider,
                "model": config.llm.resolution.model,
            },
            "anthropic_api_key": config.llm.anthropic_api_key,
            "google_api_key": config.llm.google_api_key,
            "openai_api_key": config.llm.openai_api_key,
            "openai_base_url": config.llm.openai_base_url,
        },
        "todo": {
            "auto_complete_after_days": config.todo.auto_complete_after_days,
            "sheet_id": config.todo.sheet_id,
            "sheet_name": config.todo.sheet_name,
            "google_credentials_path": config.todo.google_credentials_path,
            "webhook_url": config.todo.webhook_url,
        },
        "email": {
            "daily_digest": {
                "enabled": config.email.daily_digest.enabled,
                "send_time": config.email.daily_digest.send_time,
                "days": config.email.daily_digest.days,
            },
            "hourly_pulse": {
                "enabled": config.email.hourly_pulse.enabled,
                "start_hour": config.email.hourly_pulse.start_hour,
                "end_hour": config.email.hourly_pulse.end_hour,
                "skip_if_empty": config.email.hourly_pulse.skip_if_empty,
            },
            "method": config.email.method,
            "recipient": config.email.recipient,
            "timezone": config.email.timezone,
        },
        "lookback_hours": config.lookback_hours,
        "thread_depth": config.thread_depth,
        "db_path": config.db_path,
        "log_level": config.log_level,
        "slack_token": config.slack_token,
    }

    with open(path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)
