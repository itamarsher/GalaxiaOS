"""Founder decision delegate config: the autonomy slider + notification webhooks.

``GET``/``PUT .../delegate`` let the founder set a single company-wide autonomy
level (1 manual … 4 autonomous — see :class:`app.models.enums.DelegateAutonomy`)
and up to three notification webhooks (Slack/Telegram/phone), each choosing which
events it wants. The autonomy level presets what the Claude delegate may resolve
on the founder's behalf; the webhooks are HMAC-signed with a per-company secret
the founder can read and rotate (see :mod:`app.services.delegate`).
"""

from __future__ import annotations

from fastapi import APIRouter, status
from pydantic import BaseModel, Field, field_validator

from app.deps import CompanyDep, DbDep
from app.security import create_telegram_connect_token
from app.services import delegate as delegate_svc
from app.services import telegram as telegram_svc

router = APIRouter(prefix="/companies/{company_id}", tags=["delegate"])


class WebhookSetting(BaseModel):
    url: str
    events: str = "all"  # all | escalations | auto_handled


class TelegramStatus(BaseModel):
    enabled: bool  # platform bot configured (deployment-level)
    connected: bool
    chat_id: str | None = None
    events: str = "all"


class DelegateSettings(BaseModel):
    autonomy_level: int
    webhooks: list[WebhookSetting] = Field(default_factory=list)
    signing_secret: str | None = None
    telegram: TelegramStatus


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
    """A partial update. The autonomy slider and the notification config are
    edited from separate places, so each field is optional and ``None`` means
    "leave it as-is" — saving one never clobbers the other."""

    #: Company-wide autonomy level (1–4); ``None`` leaves it unchanged.
    autonomy_level: int | None = Field(default=None, ge=1, le=4)
    #: Notification webhooks; ``None`` leaves them unchanged (``[]`` clears them).
    webhooks: list[WebhookUpdate] | None = Field(
        default=None, max_length=delegate_svc.MAX_WEBHOOKS
    )
    #: Mint a fresh signing secret (invalidates the old one on existing receivers).
    rotate_secret: bool = False
    #: Which decisions to send to the connected Telegram chat.
    telegram_events: str | None = None

    @field_validator("telegram_events")
    @classmethod
    def _known_tg_events(cls, v: str | None) -> str | None:
        if v is not None and v not in delegate_svc.WEBHOOK_EVENTS:
            raise ValueError(f"telegram_events must be one of {sorted(delegate_svc.WEBHOOK_EVENTS)}")
        return v


class TelegramConnect(BaseModel):
    connect_url: str | None  # None if the platform bot isn't configured


def _telegram(cfg: delegate_svc.DelegateConfig | None) -> TelegramStatus:
    chat = cfg.telegram_chat_id if cfg else None
    return TelegramStatus(
        enabled=telegram_svc.enabled(),
        connected=bool(chat),
        chat_id=chat,
        events=cfg.telegram_events if cfg else "all",
    )


def _out(cfg: delegate_svc.DelegateConfig | None) -> DelegateSettings:
    if cfg is None:
        return DelegateSettings(autonomy_level=1, telegram=_telegram(None))
    return DelegateSettings(
        autonomy_level=cfg.autonomy_level,
        webhooks=[WebhookSetting(url=w.url, events=w.events) for w in cfg.webhooks],
        signing_secret=cfg.signing_secret,
        telegram=_telegram(cfg),
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
        webhooks=(
            None
            if body.webhooks is None
            else [{"url": w.url, "events": w.events} for w in body.webhooks]
        ),
        rotate_secret=body.rotate_secret,
        telegram_events=body.telegram_events,
    )
    await db.commit()
    return _out(cfg)


@router.get("/delegate/telegram/connect", response_model=TelegramConnect)
async def telegram_connect_link(company: CompanyDep):
    """A one-tap deep link the founder opens to link their Telegram chat. Carries a
    short-lived signed token the inbound webhook validates."""
    username = await telegram_svc.bot_username()
    if not username:
        return TelegramConnect(connect_url=None)  # platform bot not configured
    token = create_telegram_connect_token(company.id)
    return TelegramConnect(connect_url=f"https://t.me/{username}?start={token}")


@router.delete("/delegate/telegram", status_code=status.HTTP_204_NO_CONTENT)
async def telegram_disconnect(company: CompanyDep, db: DbDep):
    await delegate_svc.unlink_telegram(db, company_id=company.id)
    await db.commit()
    return None
