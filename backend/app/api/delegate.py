"""Founder decision delegate config: the notify webhook + opt-in Claude auto-pilot.

``GET``/``PUT .../delegate`` let the founder point a webhook (Slack/Telegram/phone)
at their decision inbox and, optionally, authorise the Claude delegate to resolve
routine decisions on their behalf — bounded by an allow-list of kinds and a spend
cap the delegate can never exceed (see :mod:`app.services.delegate`).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field, field_validator

from app.deps import CompanyDep, DbDep
from app.services import delegate as delegate_svc

router = APIRouter(prefix="/companies/{company_id}", tags=["delegate"])


class DelegateSettings(BaseModel):
    webhook_url: str | None = None
    auto_pilot_enabled: bool = False
    auto_kinds: list[str] = Field(default_factory=list)
    max_auto_spend_cents: int = 0


class DelegateUpdate(BaseModel):
    webhook_url: str | None = None
    auto_pilot_enabled: bool = False
    auto_kinds: list[str] = Field(default_factory=list)
    max_auto_spend_cents: int = Field(default=0, ge=0)

    @field_validator("auto_kinds")
    @classmethod
    def _known_kinds(cls, v: list[str]) -> list[str]:
        bad = [k for k in v if k not in delegate_svc.ALLOWED_AUTO_KINDS]
        if bad:
            raise ValueError(
                f"auto_kinds may only include {sorted(delegate_svc.ALLOWED_AUTO_KINDS)}; "
                f"got disallowed {bad}. External messages are never auto-resolvable."
            )
        return v

    @field_validator("webhook_url")
    @classmethod
    def _https_only(cls, v: str | None) -> str | None:
        if v and not v.startswith(("https://", "http://")):
            raise ValueError("webhook_url must be an http(s) URL")
        return v or None


def _out(cfg: delegate_svc.DelegateConfig | None) -> DelegateSettings:
    if cfg is None:
        return DelegateSettings()
    return DelegateSettings(
        webhook_url=cfg.webhook_url,
        auto_pilot_enabled=cfg.auto_pilot_enabled,
        auto_kinds=list(cfg.auto_kinds),
        max_auto_spend_cents=cfg.max_auto_spend_cents,
    )


@router.get("/delegate", response_model=DelegateSettings)
async def get_delegate(company: CompanyDep, db: DbDep):
    return _out(await delegate_svc.get_config(db, company.id))


@router.put("/delegate", response_model=DelegateSettings)
async def put_delegate(company: CompanyDep, body: DelegateUpdate, db: DbDep):
    # Enabling auto-pilot with no allowed kinds is a no-op that reads as "on" —
    # reject it so the founder doesn't think Claude is handling things when it
    # can't touch anything.
    if body.auto_pilot_enabled and not body.auto_kinds:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "auto_pilot_enabled requires at least one auto_kinds entry.",
        )
    cfg = await delegate_svc.set_config(
        db,
        company_id=company.id,
        webhook_url=body.webhook_url,
        auto_pilot_enabled=body.auto_pilot_enabled,
        auto_kinds=body.auto_kinds,
        max_auto_spend_cents=body.max_auto_spend_cents,
    )
    await db.commit()
    return _out(cfg)
