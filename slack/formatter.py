"""
Slack message formatting utilities for Slackhub
"""

from typing import Optional


def format_issue(issue: dict) -> str:
    """Format a GitHub issue as a Slack message string."""
    state_emoji = ":large_green_circle:" if issue.get("state") == "open" else ":white_circle:"
    labels = ", ".join(f"`{lbl['name']}`" for lbl in issue.get("labels", []))
    label_str = f"\n*Labels:* {labels}" if labels else ""
    assignees = ", ".join(a["login"] for a in issue.get("assignees", []))
    assignee_str = f"\n*Assignees:* {assignees}" if assignees else ""

    return (
        f"{state_emoji} *Issue #{issue['number']}:* <{issue['html_url']}|{issue['title']}>\n"
        f"*Author:* {issue['user']['login']}"
        f"{label_str}"
        f"{assignee_str}"
    )


def format_pull_request(pr: dict) -> str:
    """Format a GitHub pull request as a Slack message string."""
    state_emoji = ":large_green_circle:" if pr.get("state") == "open" else ":red_circle:"
    if pr.get("merged"):
        state_emoji = ":large_purple_circle:"

    draft_tag = " _(Draft)_" if pr.get("draft") else ""
    reviews = pr.get("requested_reviewers", [])
    reviewer_str = ""
    if reviews:
        reviewer_str = "\n*Reviewers:* " + ", ".join(r["login"] for r in reviews)

    return (
        f"{state_emoji} *PR #{pr['number']}:* <{pr['html_url']}|{pr['title']}>{draft_tag}\n"
        f"*Author:* {pr['user']['login']}"
        f"{reviewer_str}\n"
        f"`{pr['head']['ref']}` → `{pr['base']['ref']}`"
    )


def format_push_event(payload: dict) -> str:
    """Format a GitHub push event for posting to Slack."""
    pusher = payload.get("pusher", {}).get("name", "unknown")
    ref = payload.get("ref", "").replace("refs/heads/", "")
    repo = payload.get("repository", {})
    repo_name = repo.get("full_name", "unknown")
    repo_url = repo.get("html_url", "")
    commits = payload.get("commits", [])
    commit_lines = []
    for c in commits[:5]:
        sha_short = c["id"][:7]
        message_first_line = c["message"].splitlines()[0]
        commit_lines.append(f"  • <{c['url']}|`{sha_short}`> {message_first_line}")
    commit_summary = "\n".join(commit_lines) if commit_lines else "  (no commits)"
    more = f"\n  _...and {len(commits) - 5} more_" if len(commits) > 5 else ""

    return (
        f":arrow_up: *Push* to <{repo_url}|{repo_name}> on `{ref}` by *{pusher}*\n"
        f"{commit_summary}{more}"
    )


def format_release(payload: dict) -> str:
    """Format a GitHub release event for posting to Slack."""
    release = payload.get("release", {})
    repo = payload.get("repository", {})
    action = payload.get("action", "published")
    return (
        f":rocket: *Release {action}:* <{release.get('html_url', '')}|{release.get('tag_name', '')}> "
        f"for <{repo.get('html_url', '')}|{repo.get('full_name', '')}>\n"
        f"_{release.get('name', '')}_"
    )


def build_notification_blocks(title: str, body: str, url: str, emoji: str = ":bell:") -> list[dict]:
    """Build generic Slack Block Kit notification blocks."""
    blocks: list[dict] = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"{emoji} *{title}*\n{body[:500]}",
            },
        },
    ]
    if url:
        blocks.append(
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "View on GitHub"},
                        "url": url,
                        "action_id": "open_github_link",
                    }
                ],
            }
        )
    return blocks
