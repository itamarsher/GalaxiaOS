"""Issue-tracker seam — how the Platform agent files bug/feature tracker issues.

Mirrors the other integration seams: a Protocol plus a ``simulated`` default that
is deterministic and network-free, so the agent loop and tests never open a real
issue. The real adapter (:class:`GitHubIssueTracker`) POSTs to the GitHub REST
API and is credential-gated (``ABOS_GITHUB_TOKEN`` + ``ABOS_GITHUB_REPO``);
without a token it raises :class:`IssueTrackerError` rather than hitting the
network.

Off by default (``ABOS_ISSUE_TRACKER=simulated``); enable with
``ABOS_ISSUE_TRACKER=github``.
"""

from __future__ import annotations

import hashlib
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


class SimulatedIssueTracker:
    """Deterministic, offline tracker. Same inputs -> same id/url; no network."""

    async def open_issue(
        self, *, title: str, body: str, labels: list[str] | None = None
    ) -> IssueResult:
        label_part = ",".join(sorted(labels or []))
        digest = hashlib.sha256(f"{title}|{body}|{label_part}".encode()).hexdigest()
        # A stable fake issue number derived from the hash (kept human-sized).
        number = int(digest[:6], 16) % 90000 + 1
        repo = settings.github_repo or "simulated/repo"
        return IssueResult(
            id=f"sim:{digest[:12]}",
            number=number,
            url=f"https://example.invalid/{repo}/issues/{number}",
            provider="simulated",
        )


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


def get_issue_tracker(name: str | None = None) -> IssueTracker:
    """Return the configured issue tracker (defaults to simulated)."""
    key = (name or settings.issue_tracker).strip().lower()
    if key in ("", "none", "simulated"):
        return SimulatedIssueTracker()
    if key == "github":
        return GitHubIssueTracker()
    raise ValueError(f"unknown issue tracker: {key!r}")
