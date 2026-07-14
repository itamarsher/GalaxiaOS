"""Founder decision delegate config: the autonomy slider + notification webhooks.

``GET``/``PUT .../delegate`` let the founder set a single company-wide autonomy
level (1 manual … 4 autonomous — see :class:`app.models.enums.DelegateAutonomy`)
and up to three notification webhooks (Slack/Telegram/phone), each choosing which
events it wants. The autonomy level presets what the Claude delegate may resolve
on the founder's behalf; the webhooks are HMAC-signed with a per-company secret
the founder can read and rotate (see :mod:`app.services.delegate`).
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field, field_validator

from app.deps import CompanyDep, DbDep
from app.services import delegate as delegate_svc

router = APIRouter(prefix="/companies/{company_id}", tags=["delegate"])


class WebhookSetting(BaseModel):
    url: str
    events: str = "all"  # all | escalations | auto_handled


class DelegateSettings(BaseModel):
    autonomy_level: int
    webhooks: list[WebhookSetting] = Field(default_factory=list)
    signing_secret: str | None = None


class WebhookUpdate(BaseModel):
    url: str
    events: str = "all"

    @field_validator("url")
    @classmethod
    def _http_only(cls, v: str) -> str:
        if not v.startswith(("https://", "http://")):
            raise ValueError("webhook url must be an http(s) URL")
        return v

    @field_validator("events")
    @classmethod
    def _known_events(cls, v: str) -> str:
        if v not in delegate_svc.WEBHOOK_EVENTS:
            raise ValueError(f"events must be one of {sorted(delegate_svc.WEBHOOK_EVENTS)}")
        return v


class DelegateUpdate(BaseModel):
    autonomy_level: int = Field(ge=1, le=4)
    webhooks: list[WebhookUpdate] = Field(default_factory=list, max_length=delegate_svc.MAX_WEBHOOKS)
    #: Mint a fresh signing secret (invalidates the old one on existing receivers).
    rotate_secret: bool = False


def _out(cfg: delegate_svc.DelegateConfig | None) -> DelegateSettings:
    if cfg is None:
        return DelegateSettings(autonomy_level=1)
    return DelegateSettings(
        autonomy_level=cfg.autonomy_level,
        webhooks=[WebhookSetting(url=w.url, events=w.events) for w in cfg.webhooks],
        signing_secret=cfg.signing_secret,
    )


@router.get("/delegate", response_model=DelegateSettings)
async def get_delegate(company: CompanyDep, db: DbDep):
    return _out(await delegate_svc.get_config(db, company.id))


@router.put("/delegate", response_model=DelegateSettings)
async def put_delegate(company: CompanyDep, body: DelegateUpdate, db: DbDep):
    cfg = await delegate_svc.set_config(
        db,
        company_id=company.id,
        autonomy_level=body.autonomy_level,
        webhooks=[{"url": w.url, "events": w.events} for w in body.webhooks],
        rotate_secret=body.rotate_secret,
    )
    await db.commit()
    return _out(cfg)
