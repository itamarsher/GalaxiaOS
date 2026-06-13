"""CostMeter — the single mandatory chokepoint for *every* billable action.

Both LLM token spend and external charges (domains, paid APIs, ad spend) flow
through here. The sequence is always: estimate → reserve (atomic, row-locked) →
execute → reconcile actual vs reserved. Reservation and commit run in their own
short transactions so the reservation is durable independently of the action.

Nothing else in the system may spend money: the worker calls
:meth:`CostMeter.run_llm` for completions and :meth:`CostMeter.charge_external`
for tool charges, and there is no other path to ``budgets``.
"""

from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db import set_tenant
from app.models import ExternalCharge, LLMCall
from app.models.enums import SpendCategory
from app.providers.base import LLMProvider, LLMResponse, Message, ToolSpec, Usage
from app.services import budget as budget_svc


@dataclass
class _Reservation:
    budget_id: uuid.UUID
    reserved_cents: int


class CostMeter:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._sf = session_factory

    @asynccontextmanager
    async def _reserve(
        self, *, company_id: uuid.UUID, agent_id: uuid.UUID | None, estimated_cents: int
    ):
        """Reserve ``estimated_cents`` in its own transaction; release on failure."""
        async with self._sf() as db:
            await set_tenant(db, company_id)
            budget = await budget_svc.reserve(
                db, company_id=company_id, cents=estimated_cents, agent_id=agent_id
            )
            res = _Reservation(budget_id=budget.id, reserved_cents=estimated_cents)
            await db.commit()
        committed = {"done": False}
        try:
            yield res, committed
        finally:
            if not committed["done"]:
                async with self._sf() as db:
                    await set_tenant(db, company_id)
                    await budget_svc.release_reservation(
                        db, budget_id=res.budget_id, reserved_cents=res.reserved_cents
                    )
                    await db.commit()

    async def run_llm(
        self,
        provider: LLMProvider,
        *,
        api_key: str,
        company_id: uuid.UUID,
        agent_id: uuid.UUID | None,
        task_id: uuid.UUID | None,
        model: str,
        system: str,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        """Reserve worst-case cost, call the provider, reconcile to actual usage."""
        price = provider.price(model)
        est_in = provider.estimate_input_tokens(
            api_key=api_key, model=model, system=system, messages=messages
        )
        estimated_cents = price.cost_cents(Usage(input_tokens=est_in, output_tokens=max_tokens))
        estimated_cents = max(estimated_cents, 1)

        async with self._reserve(
            company_id=company_id, agent_id=agent_id, estimated_cents=estimated_cents
        ) as (res, committed):
            started = time.monotonic()
            resp = await provider.complete(
                api_key=api_key,
                model=model,
                system=system,
                messages=messages,
                tools=tools,
                max_tokens=max_tokens,
            )
            latency_ms = int((time.monotonic() - started) * 1000)
            actual_cents = price.cost_cents(resp.usage)

            async with self._sf() as db:
                await set_tenant(db, company_id)
                entry = await budget_svc.commit_spend(
                    db,
                    company_id=company_id,
                    budget_id=res.budget_id,
                    reserved_cents=res.reserved_cents,
                    actual_cents=actual_cents,
                    category=SpendCategory.llm,
                    agent_id=agent_id,
                    task_id=task_id,
                    description=f"{provider.name}:{model}",
                )
                db.add(
                    LLMCall(
                        company_id=company_id,
                        spend_entry_id=entry.id,
                        task_id=task_id,
                        agent_id=agent_id,
                        provider=provider.name,
                        model=model,
                        input_tokens=resp.usage.input_tokens,
                        output_tokens=resp.usage.output_tokens,
                        latency_ms=latency_ms,
                    )
                )
                await db.commit()
            committed["done"] = True
        return resp

    async def charge_external(
        self,
        *,
        company_id: uuid.UUID,
        agent_id: uuid.UUID | None,
        task_id: uuid.UUID | None,
        amount_cents: int,
        vendor: str,
        sku: str | None = None,
        external_ref: str | None = None,
        payload: dict | None = None,
        description: str | None = None,
    ) -> None:
        """Reserve and commit a non-LLM charge (e.g. a domain purchase).

        For deterministic charges the estimate equals the actual amount, but the
        full reserve→commit path still runs so the spend breaker and per-agent
        caps apply exactly as they do for LLM calls.
        """
        async with self._reserve(
            company_id=company_id, agent_id=agent_id, estimated_cents=amount_cents
        ) as (res, committed):
            async with self._sf() as db:
                await set_tenant(db, company_id)
                entry = await budget_svc.commit_spend(
                    db,
                    company_id=company_id,
                    budget_id=res.budget_id,
                    reserved_cents=res.reserved_cents,
                    actual_cents=amount_cents,
                    category=SpendCategory.external,
                    agent_id=agent_id,
                    task_id=task_id,
                    vendor=vendor,
                    sku=sku,
                    description=description,
                )
                db.add(
                    ExternalCharge(
                        company_id=company_id,
                        spend_entry_id=entry.id,
                        vendor=vendor,
                        sku=sku,
                        external_ref=external_ref,
                        payload=payload,
                    )
                )
                await db.commit()
            committed["done"] = True

    async def charge_agent_invocation(
        self,
        *,
        company_id: uuid.UUID,
        agent_id: uuid.UUID | None,
        task_id: uuid.UUID | None,
        amount_cents: int,
        vendor: str,
        sku: str | None = None,
        external_ref: str | None = None,
        payload: dict | None = None,
        description: str | None = None,
    ) -> None:
        """Reserve and commit a per-invocation marketplace agent fee.

        Identical reserve→commit path to :meth:`charge_external`, but the ledger
        row is categorised :class:`SpendCategory.agent_invocation` so hired-agent
        spend is reportable separately from raw external charges. An
        ``ExternalCharge`` row is still written for the auditable vendor trail.
        """
        async with self._reserve(
            company_id=company_id, agent_id=agent_id, estimated_cents=amount_cents
        ) as (res, committed):
            async with self._sf() as db:
                await set_tenant(db, company_id)
                entry = await budget_svc.commit_spend(
                    db,
                    company_id=company_id,
                    budget_id=res.budget_id,
                    reserved_cents=res.reserved_cents,
                    actual_cents=amount_cents,
                    category=SpendCategory.agent_invocation,
                    agent_id=agent_id,
                    task_id=task_id,
                    vendor=vendor,
                    sku=sku,
                    description=description,
                )
                db.add(
                    ExternalCharge(
                        company_id=company_id,
                        spend_entry_id=entry.id,
                        vendor=vendor,
                        sku=sku,
                        external_ref=external_ref,
                        payload=payload,
                    )
                )
                await db.commit()
            committed["done"] = True
