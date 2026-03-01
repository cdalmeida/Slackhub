"""
Tests for Slack message handler utilities
"""

import pytest
from slack.handler import _extract_github_references
from models.message import GitHubReference


def test_extract_full_github_url():
    text = "Check out https://github.com/octocat/Hello-World/issues/42 please"
    refs = _extract_github_references(text)
    assert len(refs) == 1
    assert refs[0] == GitHubReference(owner="octocat", repo="Hello-World", number=42)


def test_extract_short_reference():
    text = "Fixes octocat/Hello-World#99"
    refs = _extract_github_references(text)
    assert len(refs) == 1
    assert refs[0] == GitHubReference(owner="octocat", repo="Hello-World", number=99)


def test_extract_pull_request_url():
    text = "See https://github.com/my-org/my-repo/pull/7 for more details."
    refs = _extract_github_references(text)
    assert len(refs) == 1
    assert refs[0].number == 7
    assert refs[0].repo == "my-repo"


def test_extract_multiple_references():
    text = (
        "Related: octocat/Hello-World#1 and "
        "https://github.com/octocat/Hello-World/issues/2"
    )
    refs = _extract_github_references(text)
    assert len(refs) == 2
    numbers = {r.number for r in refs}
    assert numbers == {1, 2}


def test_no_references():
    refs = _extract_github_references("This message has no GitHub references.")
    assert refs == []


def test_extract_ignores_bot_message():
    # Bot messages should be filtered before reaching _extract_github_references,
    # but the extractor itself should still work on the text.
    text = "Bot says: octocat/repo#5"
    refs = _extract_github_references(text)
    assert len(refs) == 1
