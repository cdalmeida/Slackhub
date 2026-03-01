"""
GitHub webhook event handler for Slackhub
Registers Flask routes for receiving and processing GitHub webhook payloads.
"""

import hashlib
import hmac
import json
import logging
from typing import Optional

from flask import Flask, request, jsonify, abort

logger = logging.getLogger(__name__)

SUPPORTED_EVENTS = {
    "issues",
    "pull_request",
    "push",
    "release",
    "issue_comment",
    "pull_request_review",
}


def register_github_routes(app: Flask, config) -> None:
    """Register the GitHub webhook endpoint on a Flask app."""

    @app.route("/github/webhook", methods=["POST"])
    def github_webhook():
        event_type = request.headers.get("X-GitHub-Event", "")
        delivery_id = request.headers.get("X-GitHub-Delivery", "")

        if event_type not in SUPPORTED_EVENTS:
            logger.debug("Ignoring unsupported GitHub event: %s", event_type)
            return jsonify({"status": "ignored", "event": event_type}), 200

        raw_body = request.get_data()

        if not _verify_signature(raw_body, request.headers.get("X-Hub-Signature-256", ""), config.github_webhook_secret):
            logger.warning("Invalid GitHub webhook signature for delivery %s", delivery_id)
            abort(403)

        try:
            payload = json.loads(raw_body)
        except json.JSONDecodeError:
            abort(400)

        logger.info("Received GitHub event: %s (delivery=%s)", event_type, delivery_id)
        _dispatch_event(event_type, payload, config)

        return jsonify({"status": "ok", "event": event_type}), 200


def _verify_signature(body: bytes, signature_header: str, secret: str) -> bool:
    """Validate the HMAC-SHA256 signature of an incoming GitHub webhook."""
    if not secret:
        return True  # signature checking disabled
    if not signature_header.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header)


def _dispatch_event(event_type: str, payload: dict, config) -> None:
    """Route a GitHub webhook event to the appropriate handler."""
    from slack.notifier import SlackNotifier

    notifier = SlackNotifier(token=config.slack_bot_token)
    repo = payload.get("repository", {})
    repo_full_name = repo.get("full_name", "")
    channel = config.get_channel_for_repo(repo_full_name)

    if not channel:
        logger.debug("No Slack channel mapped for repo %s; skipping notification", repo_full_name)
        return

    if event_type == "issues":
        _handle_issues(payload, repo, channel, notifier)
    elif event_type == "pull_request":
        _handle_pull_request(payload, repo, channel, notifier)
    elif event_type == "push":
        notifier.post_push_notification(channel=channel, payload=payload)
    elif event_type == "release":
        if payload.get("action") == "published":
            notifier.post_release_notification(channel=channel, payload=payload)
    elif event_type == "issue_comment":
        _handle_issue_comment(payload, repo, channel, notifier)
    elif event_type == "pull_request_review":
        _handle_pr_review(payload, repo, channel, notifier)


def _handle_issues(payload: dict, repo: dict, channel: str, notifier) -> None:
    action = payload.get("action", "")
    if action in {"opened", "closed", "reopened", "assigned"}:
        notifier.post_issue_notification(
            channel=channel,
            action=action,
            issue=payload["issue"],
            repo=repo,
        )


def _handle_pull_request(payload: dict, repo: dict, channel: str, notifier) -> None:
    action = payload.get("action", "")
    if action in {"opened", "closed", "ready_for_review", "review_requested", "synchronize"}:
        notifier.post_pr_notification(
            channel=channel,
            action=action,
            pr=payload["pull_request"],
            repo=repo,
        )


def _handle_issue_comment(payload: dict, repo: dict, channel: str, notifier) -> None:
    action = payload.get("action", "")
    if action != "created":
        return
    comment = payload.get("comment", {})
    issue = payload.get("issue", {})
    text = (
        f":speech_balloon: *New comment* on "
        f"<{issue.get('html_url', '')}|#{issue['number']} {issue['title']}> "
        f"by *{comment['user']['login']}*:\n>{comment['body'][:300]}"
    )
    notifier.post_message(channel=channel, text=text)


def _handle_pr_review(payload: dict, repo: dict, channel: str, notifier) -> None:
    action = payload.get("action", "")
    review = payload.get("review", {})
    pr = payload.get("pull_request", {})
    if action == "submitted" and review.get("state") in {"approved", "changes_requested"}:
        state_str = ":white_check_mark: Approved" if review["state"] == "approved" else ":x: Changes requested"
        text = (
            f"{state_str} by *{review['user']['login']}* on "
            f"<{pr.get('html_url', '')}|PR #{pr['number']} {pr['title']}>"
        )
        notifier.post_message(channel=channel, text=text)
