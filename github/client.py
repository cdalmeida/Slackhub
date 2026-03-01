"""
GitHub API client for Slackhub
"""

import logging
from typing import Any, Optional

import requests

from models.message import GitHubReference

logger = logging.getLogger(__name__)

GITHUB_API_BASE = "https://api.github.com"


class GitHubClient:
    """Thin wrapper around the GitHub REST API."""

    def __init__(self, token: str = "") -> None:
        self.token = token
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            }
        )
        if token:
            self.session.headers["Authorization"] = f"Bearer {token}"

    @classmethod
    def from_config(cls, config: Any) -> "GitHubClient":
        """Instantiate from a Config object."""
        return cls(token=getattr(config, "github_token", ""))

    # ------------------------------------------------------------------
    # Issues
    # ------------------------------------------------------------------

    def get_issue(self, owner: str, repo: str, number: int) -> dict:
        """Fetch a single issue."""
        return self._get(f"/repos/{owner}/{repo}/issues/{number}")

    def create_issue(
        self,
        owner: str,
        repo: str,
        title: str,
        body: str = "",
        labels: Optional[list[str]] = None,
        assignees: Optional[list[str]] = None,
    ) -> dict:
        """Create a new issue in a repository."""
        payload: dict = {"title": title, "body": body}
        if labels:
            payload["labels"] = labels
        if assignees:
            payload["assignees"] = assignees
        return self._post(f"/repos/{owner}/{repo}/issues", json=payload)

    def close_issue(self, owner: str, repo: str, number: int) -> dict:
        """Close an existing issue."""
        return self._patch(f"/repos/{owner}/{repo}/issues/{number}", json={"state": "closed"})

    def add_issue_comment(self, owner: str, repo: str, number: int, body: str) -> dict:
        """Add a comment to an issue."""
        return self._post(f"/repos/{owner}/{repo}/issues/{number}/comments", json={"body": body})

    # ------------------------------------------------------------------
    # Pull Requests
    # ------------------------------------------------------------------

    def get_pull_request(self, owner: str, repo: str, number: int) -> dict:
        """Fetch a single pull request."""
        return self._get(f"/repos/{owner}/{repo}/pulls/{number}")

    def list_pull_requests(
        self,
        owner: str,
        repo: str,
        state: str = "open",
    ) -> list[dict]:
        """List pull requests for a repository."""
        return self._get(f"/repos/{owner}/{repo}/pulls", params={"state": state, "per_page": 30})

    def approve_pull_request(self, owner: str, repo: str, number: int) -> dict:
        """Submit an approving review on a pull request."""
        return self._post(
            f"/repos/{owner}/{repo}/pulls/{number}/reviews",
            json={"event": "APPROVE"},
        )

    def merge_pull_request(
        self,
        owner: str,
        repo: str,
        number: int,
        merge_method: str = "squash",
    ) -> dict:
        """Merge a pull request."""
        return self._put(
            f"/repos/{owner}/{repo}/pulls/{number}/merge",
            json={"merge_method": merge_method},
        )

    # ------------------------------------------------------------------
    # Repositories
    # ------------------------------------------------------------------

    def get_repo(self, owner: str, repo: str) -> dict:
        """Fetch repository metadata."""
        return self._get(f"/repos/{owner}/{repo}")

    def list_repo_issues(
        self,
        owner: str,
        repo: str,
        state: str = "open",
    ) -> list[dict]:
        """List open issues in a repository."""
        return self._get(f"/repos/{owner}/{repo}/issues", params={"state": state, "per_page": 30})

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------

    def get_summary(self, ref: GitHubReference) -> str:
        """Return a short text summary for a GitHub issue or PR reference."""
        try:
            # Try PR first (issues endpoint also returns PRs, but let's be precise)
            data = self._get(f"/repos/{ref.owner}/{ref.repo}/issues/{ref.number}")
            if "pull_request" in data:
                pr = self.get_pull_request(ref.owner, ref.repo, ref.number)
                from slack.formatter import format_pull_request
                return format_pull_request(pr)
            from slack.formatter import format_issue
            return format_issue(data)
        except Exception as exc:
            logger.warning("Could not fetch summary for %s: %s", ref, exc)
            return ""

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    def _get(self, path: str, params: Optional[dict] = None) -> Any:
        resp = self.session.get(f"{GITHUB_API_BASE}{path}", params=params, timeout=10)
        resp.raise_for_status()
        return resp.json()

    def _post(self, path: str, json: Optional[dict] = None) -> Any:
        resp = self.session.post(f"{GITHUB_API_BASE}{path}", json=json, timeout=10)
        resp.raise_for_status()
        return resp.json()

    def _patch(self, path: str, json: Optional[dict] = None) -> Any:
        resp = self.session.patch(f"{GITHUB_API_BASE}{path}", json=json, timeout=10)
        resp.raise_for_status()
        return resp.json()

    def _put(self, path: str, json: Optional[dict] = None) -> Any:
        resp = self.session.put(f"{GITHUB_API_BASE}{path}", json=json, timeout=10)
        resp.raise_for_status()
        return resp.json()
