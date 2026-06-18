"""Issue-tracker seam — how the Platform agent files bug/feature tracker issues.

A Protocol plus the real adapter (:class:`GitHubIssueTracker`), which talks to the
GitHub REST API and is credential-gated (``ABOS_GITHUB_TOKEN`` + ``ABOS_GITHUB_REPO``);
without a token it raises :class:`IssueTrackerError` rather than hitting the network.

Deduplication: agents hit the same gaps, so :meth:`GitHubIssueTracker.report_issue`
first looks for an existing OPEN issue with the same title. If one is found it adds a
👍 reaction instead of opening a duplicate, and returns the current 👍 count — a
running demand signal for how many want that capability/fix. Only when there is no
match does it open a new issue (seeded with a 👍 so demand starts at 1).

There is deliberately NO simulated tracker that fabricates an external issue
number/URL. When no real tracker is configured, :func:`get_issue_tracker` returns
``None`` and ``open_issue`` records the bug/feature request to the company's own
memory instead (deduped + counted the same way) — a durable, honest internal
artifact — so the ``request_capability`` → ``open_issue`` escalation loop still works
offline. Enable real GitHub issues with ``ABOS_ISSUE_TRACKER=github`` (or a
per-company token).
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
    #: ``False`` when an existing duplicate was upvoted instead of a new issue filed.
    created: bool = True
    #: Current 👍 count on the issue — how many have requested this capability/fix.
    upvotes: int = 0


class IssueTrackerError(RuntimeError):
    """Raised when an issue cannot be opened (missing creds, API error)."""


@runtime_checkable
class IssueTracker(Protocol):
    async def open_issue(
        self, *, title: str, body: str, labels: list[str] | None = None
    ) -> IssueResult:
        """Open a tracker issue. Raises :class:`IssueTrackerError` on failure."""
        ...

    async def report_issue(
        self, *, title: str, body: str, labels: list[str] | None = None
    ) -> IssueResult:
        """Open an issue, or upvote (👍) an existing open duplicate with the same title.

        Returns the resulting issue with ``created`` indicating whether it was newly
        opened and ``upvotes`` the current demand count.
        """
        ...


class GitHubIssueTracker:
    """Real GitHub issue tracker via the REST API (credential-gated)."""

    def __init__(
        self,
        token: str | None = None,
        *,
        repo: str | None = None,
        timeout: float | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._token = token if token is not None else settings.github_token
        self._repo = repo if repo is not None else settings.github_repo
        self._timeout = timeout if timeout is not None else settings.web_search_timeout_seconds
        # Test seam: inject an httpx transport so the API dance can be exercised
        # without the network. Production leaves it ``None`` (real transport).
        self._transport = transport

    def _require_config(self) -> tuple[str, str]:
        if not self._token:
            raise IssueTrackerError("GitHub token missing (set ABOS_GITHUB_TOKEN).")
        if not self._repo:
            raise IssueTrackerError("GitHub repo missing (set ABOS_GITHUB_REPO).")
        return self._token, self._repo

    def _headers(self, token: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=self._timeout, transport=self._transport)

    async def open_issue(
        self, *, title: str, body: str, labels: list[str] | None = None
    ) -> IssueResult:
        token, repo = self._require_config()
        headers = self._headers(token)
        try:
            async with self._client() as client:
                return await self._create_issue(client, repo, headers, title, body, labels)
        except httpx.HTTPError as exc:
            raise IssueTrackerError(f"GitHub request failed: {exc}") from exc
        except ValueError as exc:  # non-JSON body
            raise IssueTrackerError(f"GitHub returned non-JSON: {exc}") from exc

    async def report_issue(
        self, *, title: str, body: str, labels: list[str] | None = None
    ) -> IssueResult:
        token, repo = self._require_config()
        headers = self._headers(token)
        try:
            async with self._client() as client:
                existing = await self._find_open_issue_by_title(client, repo, headers, title)
                if existing is not None:
                    number = int(existing.get("number") or 0)
                    upvotes = await self._upvote(client, repo, headers, number)
                    return IssueResult(
                        id=str(existing.get("id") or ""),
                        number=number,
                        url=str(existing.get("html_url") or ""),
                        provider="github",
                        created=False,
                        upvotes=upvotes,
                    )
                created = await self._create_issue(client, repo, headers, title, body, labels)
                # Seed demand at 1 so the 👍 count tracks how many reported it.
                upvotes = await self._upvote(client, repo, headers, created.number)
                return IssueResult(
                    id=created.id,
                    number=created.number,
                    url=created.url,
                    provider="github",
                    created=True,
                    upvotes=upvotes,
                )
        except httpx.HTTPError as exc:
            raise IssueTrackerError(f"GitHub request failed: {exc}") from exc
        except ValueError as exc:  # non-JSON body
            raise IssueTrackerError(f"GitHub returned non-JSON: {exc}") from exc

    async def _create_issue(
        self,
        client: httpx.AsyncClient,
        repo: str,
        headers: dict[str, str],
        title: str,
        body: str,
        labels: list[str] | None,
    ) -> IssueResult:
        payload: dict = {"title": title, "body": body}
        if labels:
            payload["labels"] = labels
        resp = await client.post(
            f"{_GITHUB_API}/repos/{repo}/issues", json=payload, headers=headers
        )
        resp.raise_for_status()
        data = resp.json()
        return IssueResult(
            id=str(data.get("id") or ""),
            number=int(data.get("number") or 0),
            url=str(data.get("html_url") or ""),
            provider="github",
        )

    async def _find_open_issue_by_title(
        self, client: httpx.AsyncClient, repo: str, headers: dict[str, str], title: str
    ) -> dict | None:
        """Return an open issue dict whose title exactly matches, or ``None``.

        Best-effort: the search API is fuzzy and eventually consistent, so we match
        the title exactly (trimmed, case-insensitive) and treat any non-200 as "no
        duplicate found" rather than failing the report.
        """
        query = f'repo:{repo} is:issue is:open in:title "{title}"'
        resp = await client.get(
            f"{_GITHUB_API}/search/issues",
            params={"q": query, "per_page": 20},
            headers=headers,
        )
        if resp.status_code != 200:
            return None
        wanted = title.strip().lower()
        for item in resp.json().get("items", []):
            if str(item.get("title") or "").strip().lower() == wanted:
                return item
        return None

    async def _upvote(
        self, client: httpx.AsyncClient, repo: str, headers: dict[str, str], number: int
    ) -> int:
        """Add a 👍 reaction (best-effort) and return the current 👍 count.

        Note: GitHub reactions are idempotent per authenticated account, so repeated
        👍 from the same bot token do not double-count; the figure reflects DISTINCT
        reacting accounts plus any human upvotes.
        """
        try:
            await client.post(
                f"{_GITHUB_API}/repos/{repo}/issues/{number}/reactions",
                json={"content": "+1"},
                headers=headers,
            )
        except httpx.HTTPError:
            pass  # reacting is best-effort; the dedupe itself already succeeded
        try:
            resp = await client.get(
                f"{_GITHUB_API}/repos/{repo}/issues/{number}", headers=headers
            )
            if resp.status_code != 200:
                return 0
            return int((resp.json().get("reactions") or {}).get("+1") or 0)
        except (httpx.HTTPError, ValueError):
            return 0


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
