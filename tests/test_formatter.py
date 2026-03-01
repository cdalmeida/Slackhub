"""
Tests for Slack message formatting utilities
"""

import pytest
from slack.formatter import (
    format_issue,
    format_pull_request,
    format_push_event,
    format_release,
    build_notification_blocks,
)


SAMPLE_ISSUE = {
    "number": 42,
    "title": "Bug: something is broken",
    "state": "open",
    "html_url": "https://github.com/owner/repo/issues/42",
    "user": {"login": "alice"},
    "labels": [{"name": "bug"}, {"name": "priority:high"}],
    "assignees": [{"login": "bob"}],
}

SAMPLE_PR = {
    "number": 7,
    "title": "feat: add chat integration",
    "state": "open",
    "merged": False,
    "draft": False,
    "html_url": "https://github.com/owner/repo/pull/7",
    "user": {"login": "carol"},
    "head": {"ref": "feat/chat"},
    "base": {"ref": "main"},
    "requested_reviewers": [{"login": "dave"}],
    "body": "Adds full chat integration.",
}

SAMPLE_PUSH = {
    "pusher": {"name": "alice"},
    "ref": "refs/heads/main",
    "repository": {
        "full_name": "owner/repo",
        "html_url": "https://github.com/owner/repo",
    },
    "commits": [
        {
            "id": "abc1234def5678",
            "message": "fix: correct typo in README",
            "url": "https://github.com/owner/repo/commit/abc1234",
        }
    ],
}


def test_format_issue_open():
    result = format_issue(SAMPLE_ISSUE)
    assert "42" in result
    assert "alice" in result
    assert ":large_green_circle:" in result
    assert "`bug`" in result
    assert "bob" in result


def test_format_issue_closed():
    closed = {**SAMPLE_ISSUE, "state": "closed"}
    result = format_issue(closed)
    assert ":white_circle:" in result


def test_format_pull_request_open():
    result = format_pull_request(SAMPLE_PR)
    assert "7" in result
    assert "carol" in result
    assert "feat/chat" in result
    assert "dave" in result


def test_format_pull_request_merged():
    merged = {**SAMPLE_PR, "state": "closed", "merged": True}
    result = format_pull_request(merged)
    assert ":large_purple_circle:" in result


def test_format_pull_request_draft():
    draft = {**SAMPLE_PR, "draft": True}
    result = format_pull_request(draft)
    assert "Draft" in result


def test_format_push_event():
    result = format_push_event(SAMPLE_PUSH)
    assert "alice" in result
    assert "main" in result
    assert "abc1234" in result
    assert "correct typo" in result


def test_format_push_event_many_commits():
    payload = {
        **SAMPLE_PUSH,
        "commits": [
            {"id": f"sha{i}" * 3, "message": f"commit {i}", "url": f"https://github.com/c/{i}"}
            for i in range(8)
        ],
    }
    result = format_push_event(payload)
    assert "and 3 more" in result


def test_format_release():
    payload = {
        "action": "published",
        "release": {
            "tag_name": "v1.2.0",
            "name": "Version 1.2.0",
            "html_url": "https://github.com/owner/repo/releases/tag/v1.2.0",
        },
        "repository": {
            "full_name": "owner/repo",
            "html_url": "https://github.com/owner/repo",
        },
    }
    result = format_release(payload)
    assert "v1.2.0" in result
    assert "owner/repo" in result


def test_build_notification_blocks_with_url():
    blocks = build_notification_blocks(
        title="Test title",
        body="Test body",
        url="https://github.com/owner/repo/issues/1",
    )
    assert len(blocks) == 2
    assert blocks[0]["type"] == "section"
    assert blocks[1]["type"] == "actions"


def test_build_notification_blocks_no_url():
    blocks = build_notification_blocks(title="Test", body="Body", url="")
    assert len(blocks) == 1
