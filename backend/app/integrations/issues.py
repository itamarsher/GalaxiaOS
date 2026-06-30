"""Issue-tracker seam — how the Platform agent files bug/feature tracker issues.

A Protocol plus the real adapter (:class:`GitHubIssueTracker`), which talks to the
GitHub REST API and is credential-gated (``ABOS_GITHUB_TOKEN`` + ``ABOS_GITHUB_REPO``);
without a token it raises :class:`IssueTrackerError` rather than hitting the network.

Deduplication & demand: agents hit the same gaps, so
:meth:`GitHubIssueTracker.report_issue` first looks for an existing OPEN issue with
the same title. Rather than open a duplicate, it posts a marked "+1" comment and
returns how many such demand comments the issue now has — a running tally of how
many want that capability/fix. Comments are counted (not reactions) so demand keeps
climbing even when every agent acts through the same bot token. A newly opened issue
gets its first "+1" comment too, so demand starts at 1. The marker
(:data:`_DEMAND_MARKER`) is a hidden HTML comment, so the count ignores ordinary
human discussion on the thread.

There is deliberately NO simulated tracker that fabricates an external issue
number/URL. GitHub is the default tracker, authenticated with a centralized global
``ABOS_GITHUB_TOKEN`` set in the deployment env. If that yields no usable tracker
(``ABOS_ISSUE_TRACKER=none``, or the legacy ``simulated`` value with no token),
:func:`get_issue_tracker` returns ``None`` and ``open_issue`` records the bug/feature
request to the company's own memory instead (deduped + counted the same way) — a
durable, honest internal artifact — so the ``request_capability`` → ``open_issue``
escalation loop still works offline.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import httpx

from app.config import settings

_GITHUB_API = "https://api.github.com"

#: Hidden marker on demand "+1" comments so they can be counted regardless of any
#: ordinary human discussion on the thread.
_DEMAND_MARKER = "<!-- abos:capability-demand -->"
_DEMAND_COMMENT = (
    f"{_DEMAND_MARKER}\n+1 — another agent reported needing this "
    "(logged automatically by the Platform agent)."
)
#: Safety cap on comment pagination when tallying demand (100 comments/page).
_MAX_COMMENT_PAGES = 10


@dataclass(frozen=True)
class IssueResult:
    id: str
    number: int
    url: str
    provider: str
    #: ``False`` when an existing duplicate was +1'd instead of a new issue filed.
    created: bool = True
    #: Number of "+1" demand comments — how many have requested this capability/fix.
    demand: int = 0


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
        """Open an issue, or +1 an existing open duplicate with the same title.

        Returns the resulting issue with ``created`` indicating whether it was newly
        opened and ``demand`` the current "+1" comment count.
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
        except httpx.HTTPStatusError as exc:
            raise IssueTrackerError(self._explain_status(exc, repo)) from exc
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
                    demand = await self._register_demand(client, repo, headers, number)
                    return IssueResult(
                        id=str(existing.get("id") or ""),
                        number=number,
                        url=str(existing.get("html_url") or ""),
                        provider="github",
                        created=False,
                        demand=demand,
                    )
                created = await self._create_issue(client, repo, headers, title, body, labels)
                # Seed demand at 1 so the "+1" comment count tracks how many reported it.
                demand = await self._register_demand(client, repo, headers, created.number)
                return IssueResult(
                    id=created.id,
                    number=created.number,
                    url=created.url,
                    provider="github",
                    created=True,
                    demand=demand,
                )
        except httpx.HTTPStatusError as exc:
            raise IssueTrackerError(self._explain_status(exc, repo)) from exc
        except httpx.HTTPError as exc:
            raise IssueTrackerError(f"GitHub request failed: {exc}") from exc
        except ValueError as exc:  # non-JSON body
            raise IssueTrackerError(f"GitHub returned non-JSON: {exc}") from exc

    @staticmethod
    def _explain_status(exc: httpx.HTTPStatusError, repo: str) -> str:
        """Turn a GitHub HTTP error into an actionable message.

        The token *is* set (we only get here after the credential check), so the
        Platform agent must not report it as missing. Distinguish "rejected" (bad/
        expired token), "forbidden" (insufficient scope or rate limit) and "not
        found" (token can't see the repo) so the founder fixes the right thing.
        """
        status = exc.response.status_code
        if status == 401:
            return (
                "GitHub rejected the token (401 Unauthorized): it is set but invalid "
                "or expired — regenerate the GitHub token in Settings."
            )
        if status == 403:
            return (
                "GitHub denied the request (403 Forbidden): the token is set but lacks "
                f"permission to open issues on {repo} (it needs the 'repo'/'issues' "
                "scope), or it is rate-limited."
            )
        if status == 404:
            return (
                f"GitHub returned 404 for {repo}: the token is set but cannot see that "
                "repository — check the repo name and that the token has access to it."
            )
        return f"GitHub request failed ({status}): {exc}"

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

    async def _register_demand(
        self, client: httpx.AsyncClient, repo: str, headers: dict[str, str], number: int
    ) -> int:
        """Post a marked "+1" demand comment, then return the current demand count."""
        await self._add_demand_comment(client, repo, headers, number)
        return await self._count_demand_comments(client, repo, headers, number)

    async def _add_demand_comment(
        self, client: httpx.AsyncClient, repo: str, headers: dict[str, str], number: int
    ) -> None:
        try:
            await client.post(
                f"{_GITHUB_API}/repos/{repo}/issues/{number}/comments",
                json={"body": _DEMAND_COMMENT},
                headers=headers,
            )
        except httpx.HTTPError:
            pass  # commenting is best-effort; the dedupe itself already succeeded

    async def _count_demand_comments(
        self, client: httpx.AsyncClient, repo: str, headers: dict[str, str], number: int
    ) -> int:
        """Tally "+1" demand comments (those carrying :data:`_DEMAND_MARKER`)."""
        count = 0
        for page in range(1, _MAX_COMMENT_PAGES + 1):
            try:
                resp = await client.get(
                    f"{_GITHUB_API}/repos/{repo}/issues/{number}/comments",
                    params={"per_page": 100, "page": page},
                    headers=headers,
                )
            except httpx.HTTPError:
                break
            if resp.status_code != 200:
                break
            try:
                items = resp.json()
            except ValueError:
                break
            if not items:
                break
            count += sum(1 for c in items if _DEMAND_MARKER in str(c.get("body") or ""))
            if len(items) < 100:
                break
        return count


def get_issue_tracker(name: str | None = None) -> IssueTracker | None:
    """Return the configured issue tracker, or ``None`` if none is wired.

    There is no simulated fallback: an unconfigured environment returns ``None`` so
    ``open_issue`` records the request to company memory instead of fabricating an
    external issue.

    GitHub is the default tracker, so any value other than an explicit
    ``ABOS_ISSUE_TRACKER=none`` (and the legacy ``simulated``) routes here. We file
    real issues whenever a global ``ABOS_GITHUB_TOKEN`` is configured; without any
    token we return ``None`` so ``open_issue`` records the request to company memory
    instead of 401-ing against GitHub. In production the centralized token is always
    set, so this is effectively always-GitHub.
    """
    key = (name or settings.issue_tracker).strip().lower()
    if key == "none":
        return None
    if key in ("github", "", "simulated"):
        return GitHubIssueTracker() if settings.github_token.strip() else None
    raise ValueError(f"unknown issue tracker: {key!r}")
