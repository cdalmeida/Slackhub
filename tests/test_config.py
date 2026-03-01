"""
Tests for configuration loading
"""

import os
import pytest
from config import Config


def test_config_from_env(monkeypatch):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "secret123")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_test")
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "whsecret")
    monkeypatch.setenv("REPO_CHANNEL_MAP", "owner/repo:#general, owner/other:#dev")
    monkeypatch.setenv("DEBUG", "true")
    monkeypatch.setenv("PORT", "8080")

    cfg = Config.from_env()

    assert cfg.slack_bot_token == "xoxb-test"
    assert cfg.slack_signing_secret == "secret123"
    assert cfg.github_token == "ghp_test"
    assert cfg.github_webhook_secret == "whsecret"
    assert cfg.debug is True
    assert cfg.port == 8080
    assert cfg.repo_channel_map == {
        "owner/repo": "#general",
        "owner/other": "#dev",
    }


def test_get_channel_for_repo(monkeypatch):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "secret")
    monkeypatch.setenv("REPO_CHANNEL_MAP", "myorg/myrepo:#myteam")
    cfg = Config.from_env()

    assert cfg.get_channel_for_repo("myorg/myrepo") == "#myteam"
    assert cfg.get_channel_for_repo("other/repo") is None


def test_empty_repo_channel_map(monkeypatch):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "x")
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "s")
    monkeypatch.delenv("REPO_CHANNEL_MAP", raising=False)
    cfg = Config.from_env()
    assert cfg.repo_channel_map == {}
