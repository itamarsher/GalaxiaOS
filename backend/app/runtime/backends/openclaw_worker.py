"""OpenClawWorker — a push :class:`WorkerClient` backed by an OpenClaw Gateway.

RFC 0001, migration step 5 (push posture): :class:`ConnectedBackend` hands this
worker a function's mandate + initiative; it drives an external **OpenClaw**
Gateway over its OpenAI-compatible HTTP API (``POST /v1/chat/completions``) and
returns a :class:`WorkerReport`. Galaxia calls *out* — so there is no inbound auth
boundary here; Galaxia authenticates to the Gateway with a bearer token, and each
business function routes to its own OpenClaw agent persona
(``model="openclaw/<function>"``) so tenancy/identity live in the route
(``<company>:<function>`` is the persona id the Gateway is provisioned with).

The mandate becomes the system briefing; the initiative becomes the task. The
worker asks the agent to end with a small JSON verdict so we can map the outcome
onto the Business-Function report vocabulary; absent a parseable verdict, a
completed reply is treated as ``done`` with its text as the summary (never
fabricating a failure). Fully unit-testable offline by injecting an
``httpx.AsyncClient`` with a mock transport — no live Gateway required.
"""

from __future__ import annotations

import json
import re

import httpx

from app.config import settings
from app.observability import get_logger
from app.runtime.backends.connected import WorkerReport
from app.services import business_function

_log = get_logger("abos.openclaw_worker")

# Outcomes the agent may declare; anything else (or nothing) falls back to `done`.
_VALID_OUTCOMES = {"done", "failed", "blocked", "needs_decision"}
# Grab the last JSON object in the reply (the verdict is asked for at the end).
_JSON_OBJ_RE = re.compile(r"\{[^{}]*\}", re.S)

_VERDICT_INSTRUCTION = (
    "\n\nWhen you have finished, end your reply with a single JSON object on its own "
    'line: {"outcome": "done|failed|blocked|needs_decision", "summary": "<one line>"}. '
    'Use "needs_decision" only if you cannot proceed without a founder decision.'
)


class OpenClawWorker:
    """Drives an OpenClaw Gateway agent for one initiative (push posture)."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str | None = None,
        timeout: float | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model or ""
        self._timeout = timeout if timeout is not None else settings.openclaw_timeout_seconds
        self._client = client  # injectable for tests; otherwise created per call

    def _route(self, mandate: business_function.Mandate) -> str:
        # Explicit model override wins; otherwise route to the per-function persona
        # (``openclaw/<function>``), each backed by its own isolated workspace in the
        # Gateway config (gateway/config/openclaw.json) — so Growth and Finance never
        # share memory/workspace (RFC 0001 §6, function-level isolation).
        #
        # NB: OpenClaw serves only statically-defined agents (no per-id
        # auto-creation) and rejects ':' / '/' in an agent id, so we key on the
        # function alone. Full per-(company, function) isolation across MANY companies
        # needs the Gateway's agent roster generated from Galaxia's org — a follow-up;
        # today's single-tenant deployment gets full per-function isolation.
        return self._model or f"openclaw/{mandate.function}"

    @staticmethod
    def _briefing(mandate: business_function.Mandate) -> str:
        lines = [
            f"You are the {mandate.function_title} ({mandate.function}) for this company.",
            f"\nMission:\n{mandate.mission}",
        ]
        if mandate.objectives:
            lines.append(f"\nObjectives:\n{mandate.objectives}")
        if mandate.metrics:
            lines.append(f"\nRecent metrics:\n{mandate.metrics}")
        if mandate.constraints:
            lines.append("\nConstraints:\n" + "\n".join(f"- {c}" for c in mandate.constraints))
        if mandate.budget.function_remaining_cents is not None:
            lines.append(
                f"\nBudget remaining for this function: "
                f"{mandate.budget.function_remaining_cents}c."
            )
        return "\n".join(lines)

    async def execute(
        self,
        *,
        mandate: business_function.Mandate,
        initiative: business_function.Initiative,
    ) -> WorkerReport:
        payload = {
            "model": self._route(mandate),
            "messages": [
                {"role": "system", "content": self._briefing(mandate)},
                {"role": "user", "content": initiative.goal + _VERDICT_INSTRUCTION},
            ],
        }
        client = self._client or httpx.AsyncClient(timeout=self._timeout)
        owns = self._client is None
        try:
            resp = await client.post(
                f"{self._base_url}/v1/chat/completions",
                json=payload,
                headers={"Authorization": f"Bearer {self._api_key}"},
            )
            resp.raise_for_status()
            data = resp.json()
        finally:
            if owns:
                await client.aclose()
        return self._parse(data)

    @staticmethod
    def _parse(data: dict) -> WorkerReport:
        """Map an OpenAI-compatible completion to a WorkerReport.

        Prefers the agent's own JSON verdict; falls back to treating a completed
        reply as ``done`` (never inventing a failure the agent didn't report).
        """
        try:
            content = data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError):
            content = ""
        if isinstance(content, list):  # some providers return content blocks
            content = " ".join(
                b.get("text", "") for b in content if isinstance(b, dict)
            )
        content = content.strip()

        for match in reversed(_JSON_OBJ_RE.findall(content)):
            try:
                obj = json.loads(match)
            except ValueError:
                continue
            outcome = str(obj.get("outcome", "")).lower()
            if outcome in _VALID_OUTCOMES:
                summary = str(obj.get("summary") or "").strip() or content
                return WorkerReport(outcome=outcome, output={"summary": summary})
        # No parseable verdict: a reply we got back means the agent did the work.
        return WorkerReport(outcome="done", output={"summary": content or "(no output)"})


def default_openclaw_worker() -> OpenClawWorker | None:
    """The configured OpenClaw worker, or ``None`` when no Gateway is set up."""
    if not settings.openclaw_base_url:
        return None
    return OpenClawWorker(
        base_url=settings.openclaw_base_url,
        api_key=settings.openclaw_api_key,
        model=settings.openclaw_model or None,
    )
