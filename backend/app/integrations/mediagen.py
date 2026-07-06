"""Brand media-generation seam — the design agent's window onto image/video synthesis.

A small Protocol plus the real, credential-gated adapter that satisfies it. Like the
web-search and file seams there is deliberately NO simulated/offline provider:
fabricating an image or video would hand the design agent a phantom asset it then
files and references as if it existed. When no real provider is configured,
:func:`get_media_gen` returns ``None`` and the ``generate_image`` / ``generate_video``
tools report the capability is unsupported (and the agent can request it).

The only adapter today is Google's **Nano Banana** (the Gemini image model) for stills
and **Veo** for short clips — both reached through Google's Generative Language API
(:mod:`app.integrations.nano_banana`). Swap in a real provider via
``ABOS_MEDIA_GEN_PROVIDER`` (e.g. ``google``); a per-company BYO key (stored under the
``nano_banana`` provider slot) takes precedence over the global one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class GeneratedMedia:
    """A piece of media a provider synthesized: the raw bytes plus its MIME type.

    ``note`` carries any short text the model returned alongside the asset (e.g. a
    caption or a revised-prompt note); ``None`` when the provider returned only bytes.
    """

    data: bytes
    mime_type: str
    note: str | None = None


class MediaGenError(RuntimeError):
    """Raised when a real provider fails (missing creds, HTTP error, no media in body)."""


@runtime_checkable
class MediaGen(Protocol):
    async def generate_image(
        self, prompt: str, *, aspect_ratio: str | None = None
    ) -> GeneratedMedia:
        """Render a still image for ``prompt``. Raises :class:`MediaGenError` on failure."""
        ...

    async def generate_video(self, prompt: str, *, seconds: int | None = None) -> GeneratedMedia:
        """Render a short video clip for ``prompt``. Raises :class:`MediaGenError`."""
        ...


def get_media_gen(name: str | None = None) -> MediaGen | None:
    """Return the configured media-generation provider, or ``None`` if none is wired.

    There is no simulated fallback: an unconfigured environment returns ``None`` so the
    design tools report the capability is unsupported instead of fabricating an asset.
    Unknown names raise ``ValueError`` so a misconfiguration fails loudly rather than
    silently doing nothing.
    """
    from app.config import settings

    key = (name or settings.media_gen_provider).strip().lower()
    if key in ("", "none", "simulated"):
        return None
    if key in ("google", "gemini", "nano_banana"):
        from app.integrations.nano_banana import NanoBananaMediaGen

        return NanoBananaMediaGen()
    raise ValueError(f"unknown media-generation provider: {key!r}")
