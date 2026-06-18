"""Issue-tracker seam — how the Platform agent files bug/feature tracker issues.

A Protocol plus the real adapter (:class:`GitHubIssueTracker`), which POSTs to the
GitHub REST API and is credential-gated (``ABOS_GITHUB_TOKEN`` + ``ABOS_GITHUB_REPO``);
without a token it raises :class:`IssueTrackerError` rather than hitting the network.

There is deliberately NO simulated tracker that fabricates an external issue
number/URL. When no real tracker is configured, :func:`get_issue_tracker` returns
``None`` and ``open_issue`` records the bug/feature request to the company's own
memory instead — a durable, honest internal artifact — so the
``request_capability`` → ``open_issue`` escalation loop still works offline. Enable
real GitHub issues with ``ABOS_ISSUE_TRACKER=github`` (or a per-company token).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import httpx

from app.config import settings

_GITHUB_API = "https://api.github.com"


@dataclass(frozen=True)
class IssueResult:
    id: str
    number: int
    url: str
    provider: str


class IssueTrackerError(RuntimeError):
    """Raised when an issue cannot be opened (missing creds, API error)."""


@runtime_checkable
class IssueTracker(Protocol):
    async def open_issue(
        self, *, title: str, body: str, labels: list[str] | None = None
    ) -> IssueResult:
        """Open a tracker issue. Raises :class:`IssueTrackerError` on failure."""
        ...


class GitHubIssueTracker:
    """Real GitHub issue tracker via the REST API (credential-gated)."""

    def __init__(
        self,
        token: str | None = None,
        *,
        repo: str | None = None,
        timeout: float | None = None,
    ) -> None:
        self._token = token if token is not None else settings.github_token
        self._repo = repo if repo is not None else settings.github_repo
        self._timeout = timeout if timeout is not None else settings.web_search_timeout_seconds

    def _require_config(self) -> tuple[str, str]:
        if not self._token:
            raise IssueTrackerError("GitHub token missing (set ABOS_GITHUB_TOKEN).")
        if not self._repo:
            raise IssueTrackerError("GitHub repo missing (set ABOS_GITHUB_REPO).")
        return self._token, self._repo

    async def open_issue(
        self, *, title: str, body: str, labels: list[str] | None = None
    ) -> IssueResult:
        token, repo = self._require_config()
        payload: dict = {"title": title, "body": body}
        if labels:
            payload["labels"] = labels
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    f"{_GITHUB_API}/repos/{repo}/issues", json=payload, headers=headers
                )
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as exc:
            raise IssueTrackerError(f"GitHub request failed: {exc}") from exc
        except ValueError as exc:  # non-JSON body
            raise IssueTrackerError(f"GitHub returned non-JSON: {exc}") from exc
        return IssueResult(
            id=str(data.get("id") or ""),
            number=int(data.get("number") or 0),
            url=str(data.get("html_url") or ""),
            provider="github",
        )


def get_issue_tracker(name: str | None = None) -> IssueTracker | None:
    """Return the configured issue tracker, or ``None`` if none is wired.

    There is no simulated fallback: an unconfigured environment returns ``None`` so
    ``open_issue`` records the request to company memory instead of fabricating an
    external issue.
    """
    key = (name or settings.issue_tracker).strip().lower()
    if key in ("", "none", "simulated"):
        return None
    if key == "github":
        return GitHubIssueTracker()
    raise ValueError(f"unknown issue tracker: {key!r}")
