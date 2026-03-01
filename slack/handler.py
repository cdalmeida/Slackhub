"""
Slack event and message handlers for Slackhub
"""

import logging
import re
from typing import Any, Callable

from slack_bolt import App

from github.client import GitHubClient
from models.message import SlackMessage, GitHubReference

logger = logging.getLogger(__name__)

# Pattern to detect GitHub issue/PR references in Slack messages
GITHUB_REF_PATTERN = re.compile(
    r"(?:https?://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/(?:issues|pull)/(?P<number>\d+))"
    r"|(?P<short>(?P<s_owner>[^/\s]+)/(?P<s_repo>[^#\s]+)#(?P<s_number>\d+))"
)


def register_slack_handlers(app: App) -> None:
    """Register all Slack event handlers on the bolt App."""

    @app.event("message")
    def handle_message(event: dict, say: Callable, client: Any) -> None:
        """Handle incoming Slack messages and expand GitHub references."""
        text = event.get("text", "")
        channel = event.get("channel", "")
        thread_ts = event.get("thread_ts") or event.get("ts")

        if event.get("bot_id"):
            return  # ignore bot messages to avoid loops

        references = _extract_github_references(text)
        if not references:
            return

        config = app.installation_store  # type: ignore[attr-defined]
        github = GitHubClient.from_config(config) if hasattr(config, "github_token") else GitHubClient()

        for ref in references:
            try:
                summary = github.get_summary(ref)
                if summary:
                    say(text=summary, channel=channel, thread_ts=thread_ts)
            except Exception as exc:  # pragma: no cover
                logger.warning("Failed to fetch GitHub summary for %s: %s", ref, exc)

    @app.command("/gh-issue")
    def handle_gh_issue(ack: Callable, respond: Callable, command: dict) -> None:
        """
        Slash command: /gh-issue <owner>/<repo> <title>
        Creates a new GitHub issue from Slack.
        """
        ack()
        text = command.get("text", "").strip()
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            respond("Usage: `/gh-issue <owner>/<repo> <issue title>`")
            return

        repo_slug, title = parts[0], parts[1]
        if "/" not in repo_slug:
            respond(f"Invalid repo format `{repo_slug}`. Expected `owner/repo`.")
            return

        owner, repo = repo_slug.split("/", 1)
        config = app.installation_store  # type: ignore[attr-defined]
        github = GitHubClient.from_config(config) if hasattr(config, "github_token") else GitHubClient()

        try:
            issue = github.create_issue(owner=owner, repo=repo, title=title)
            respond(f":white_check_mark: Issue created: <{issue['html_url']}|{issue['title']}> (#{issue['number']})")
        except Exception as exc:
            logger.error("Failed to create GitHub issue: %s", exc)
            respond(f":x: Failed to create issue: {exc}")

    @app.command("/gh-pr")
    def handle_gh_pr(ack: Callable, respond: Callable, command: dict) -> None:
        """
        Slash command: /gh-pr <owner>/<repo> <pr_number>
        Fetches details of a pull request.
        """
        ack()
        text = command.get("text", "").strip()
        parts = text.split()
        if len(parts) < 2:
            respond("Usage: `/gh-pr <owner>/<repo> <pr_number>`")
            return

        repo_slug, number_str = parts[0], parts[1]
        if "/" not in repo_slug or not number_str.isdigit():
            respond("Invalid arguments. Use `/gh-pr owner/repo 42`")
            return

        owner, repo = repo_slug.split("/", 1)
        config = app.installation_store  # type: ignore[attr-defined]
        github = GitHubClient.from_config(config) if hasattr(config, "github_token") else GitHubClient()

        try:
            pr = github.get_pull_request(owner=owner, repo=repo, number=int(number_str))
            blocks = _build_pr_blocks(pr)
            respond(blocks=blocks)
        except Exception as exc:
            logger.error("Failed to fetch PR: %s", exc)
            respond(f":x: Failed to fetch PR: {exc}")

    @app.action("approve_pr")
    def handle_approve_pr(ack: Callable, body: dict, respond: Callable) -> None:
        """Interactive button action: approve a pull request from Slack."""
        ack()
        action = body.get("actions", [{}])[0]
        value = action.get("value", "")  # format: "owner/repo/number"
        parts = value.split("/")
        if len(parts) != 3:
            respond(":x: Invalid action payload.")
            return

        owner, repo, number_str = parts
        config = app.installation_store  # type: ignore[attr-defined]
        github = GitHubClient.from_config(config) if hasattr(config, "github_token") else GitHubClient()

        try:
            github.approve_pull_request(owner=owner, repo=repo, number=int(number_str))
            respond(f":white_check_mark: PR `{owner}/{repo}#{number_str}` approved.")
        except Exception as exc:
            logger.error("Failed to approve PR: %s", exc)
            respond(f":x: Failed to approve PR: {exc}")

    logger.info("Slack handlers registered")


def _extract_github_references(text: str) -> list[GitHubReference]:
    """Parse GitHub issue/PR references from a Slack message."""
    refs: list[GitHubReference] = []
    for match in GITHUB_REF_PATTERN.finditer(text):
        gd = match.groupdict()
        if gd.get("owner"):
            refs.append(GitHubReference(owner=gd["owner"], repo=gd["repo"], number=int(gd["number"])))
        elif gd.get("s_owner"):
            refs.append(GitHubReference(owner=gd["s_owner"], repo=gd["s_repo"], number=int(gd["s_number"])))
    return refs


def _build_pr_blocks(pr: dict) -> list[dict]:
    """Build Slack Block Kit blocks for a pull request summary."""
    state_emoji = ":large_green_circle:" if pr.get("state") == "open" else ":red_circle:"
    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"{state_emoji} *<{pr['html_url']}|{pr['title']}>* (#{pr['number']})\n"
                        f"_{pr.get('body', '')[:200]}..._" if pr.get("body") else "",
            },
        },
        {
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": f"*Author:* {pr['user']['login']}"},
                {"type": "mrkdwn", "text": f"*Branch:* `{pr['head']['ref']}` → `{pr['base']['ref']}`"},
                {"type": "mrkdwn", "text": f"*Changed files:* {pr.get('changed_files', '?')}"},
            ],
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": ":white_check_mark: Approve"},
                    "style": "primary",
                    "action_id": "approve_pr",
                    "value": f"{pr['base']['repo']['owner']['login']}/{pr['base']['repo']['name']}/{pr['number']}",
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": ":link: Open on GitHub"},
                    "url": pr["html_url"],
                    "action_id": "open_pr",
                },
            ],
        },
    ]
