"""
Slack notification sender for Slackhub
Handles posting GitHub event notifications to Slack channels.
"""

import logging
from typing import Optional

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

logger = logging.getLogger(__name__)


class SlackNotifier:
    """Sends formatted GitHub event notifications to Slack channels."""

    def __init__(self, token: str) -> None:
        self.client = WebClient(token=token)

    def post_message(
        self,
        channel: str,
        text: str,
        blocks: Optional[list] = None,
        thread_ts: Optional[str] = None,
    ) -> Optional[dict]:
        """Post a message to a Slack channel."""
        try:
            kwargs: dict = {"channel": channel, "text": text}
            if blocks:
                kwargs["blocks"] = blocks
            if thread_ts:
                kwargs["thread_ts"] = thread_ts
            response = self.client.chat_postMessage(**kwargs)
            logger.debug("Message posted to %s: ts=%s", channel, response["ts"])
            return response.data
        except SlackApiError as exc:
            logger.error("Slack API error posting to %s: %s", channel, exc.response["error"])
            return None

    def post_issue_notification(
        self,
        channel: str,
        action: str,
        issue: dict,
        repo: dict,
    ) -> Optional[dict]:
        """Notify a Slack channel about a GitHub issue event."""
        from slack.formatter import format_issue, build_notification_blocks

        emoji_map = {
            "opened": ":white_check_mark:",
            "closed": ":octagonal_sign:",
            "reopened": ":recycle:",
            "assigned": ":bust_in_silhouette:",
            "labeled": ":label:",
        }
        emoji = emoji_map.get(action, ":bell:")
        title = f"Issue {action}: #{issue['number']} in {repo['full_name']}"
        body = format_issue(issue)
        blocks = build_notification_blocks(title=title, body=body, url=issue["html_url"], emoji=emoji)
        return self.post_message(channel=channel, text=title, blocks=blocks)

    def post_pr_notification(
        self,
        channel: str,
        action: str,
        pr: dict,
        repo: dict,
    ) -> Optional[dict]:
        """Notify a Slack channel about a GitHub pull request event."""
        from slack.formatter import format_pull_request, build_notification_blocks

        emoji_map = {
            "opened": ":arrow_heading_up:",
            "closed": ":white_check_mark:" if pr.get("merged") else ":octagonal_sign:",
            "review_requested": ":eyes:",
            "ready_for_review": ":mag:",
            "synchronize": ":arrows_counterclockwise:",
        }
        emoji = emoji_map.get(action, ":bell:")
        title = f"PR {action}: #{pr['number']} in {repo['full_name']}"
        body = format_pull_request(pr)
        blocks = build_notification_blocks(title=title, body=body, url=pr["html_url"], emoji=emoji)
        return self.post_message(channel=channel, text=title, blocks=blocks)

    def post_push_notification(self, channel: str, payload: dict) -> Optional[dict]:
        """Notify a Slack channel about a push event."""
        from slack.formatter import format_push_event

        text = format_push_event(payload)
        return self.post_message(channel=channel, text=text)

    def post_release_notification(self, channel: str, payload: dict) -> Optional[dict]:
        """Notify a Slack channel about a release event."""
        from slack.formatter import format_release

        text = format_release(payload)
        return self.post_message(channel=channel, text=text)
