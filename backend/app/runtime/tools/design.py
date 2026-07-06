"""Design area tools: generate on-brand photos and videos with Google Nano Banana.

These are how the **design** agent turns a brief into a real visual asset. Image
synthesis goes through Google's **Nano Banana** (the Gemini image model) and short
clips through **Veo**, behind the credential-gated media-generation seam
(:mod:`app.integrations.mediagen`). Generation is a real, billable side effect, so it
is metered through ``ctx.cost_meter`` exactly like a web search or a domain purchase,
and the finished asset is filed into the company's external store (Drive) so it is
durable, shareable, and reusable — never a phantom result.

Both tools steer generation toward the company's brand: before rendering they pull the
brand/design guidelines out of the company file store (the ``brand`` category) and
prepend them to the prompt, so the output is consistent with the brand by default.

Without a connected media provider (or file store to hold the binary) the tools report
the capability is unsupported via ``unsupported_capability`` rather than inventing an
asset — keeping the audit trail honest, like every other ABOS seam.
"""

from __future__ import annotations

from app.config import settings
from app.integrations.files import FileProviderError
from app.integrations.mediagen import GeneratedMedia, MediaGen, MediaGenError, get_media_gen
from app.models import Agent, Company, Task
from app.models.enums import FileCategory, MemoryType
from app.providers.base import ToolSpec
from app.runtime.tools.base import ToolOutcome, unsupported_capability
from app.runtime.tools.critique import visual_gate
from app.services import files as files_svc
from app.services import memory as memory_svc
from app.services.integrations import resolve_file_provider

#: BYOK provider slot under which a company's Google Generative Language API key
#: (Nano Banana / Veo) is stored. Mirrors how web search resolves a per-company key.
MEDIA_GEN_PROVIDER = "nano_banana"

#: File extension to give a saved asset, by MIME type (so Drive shows it usefully and
#: it round-trips as the right media type).
_EXT_BY_MIME = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/webp": "webp",
    "image/gif": "gif",
    "video/mp4": "mp4",
    "video/webm": "webm",
    "video/quicktime": "mov",
}

# How much of the brand guideline to fold into a generation prompt. Enough to carry
# palette/voice/visual rules without blowing up the request.
_BRAND_CONTEXT_CHARS = 2_000


SPECS: list[ToolSpec] = [
    ToolSpec(
        name="generate_image",
        description=(
            "Generate a photo / still image from a text prompt using Google's Nano "
            "Banana (Gemini image) model, on-brand by default. The company's brand & "
            "design guidelines (filed in the brand folder) are automatically blended "
            "into the prompt, so the result matches the brand's palette, style, and "
            "voice. SPENDS real budget (metered) and FILES the rendered image into the "
            "company's store, returning its link. Describe the subject, composition, "
            "mood, and any text to include."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "What to render (subject, composition, mood, on-image text).",
                },
                "filename": {
                    "type": "string",
                    "description": "Optional name for the saved asset, e.g. 'hero-banner'.",
                },
                "aspect_ratio": {
                    "type": "string",
                    "description": "Optional aspect ratio, e.g. '16:9', '1:1', '9:16'.",
                },
                "on_brand": {
                    "type": "boolean",
                    "description": "Blend in the brand guidelines (default true). Set false for an off-brand exploration.",
                },
            },
            "required": ["prompt"],
        },
    ),
    ToolSpec(
        name="generate_video",
        description=(
            "Generate a short video clip from a text prompt using Google's Veo model, "
            "on-brand by default. The company's brand & design guidelines are blended "
            "into the prompt automatically. SPENDS real budget (metered, and a clip is "
            "materially pricier than an image) and FILES the rendered clip into the "
            "company's store, returning its link. Video generation can take a while. "
            "Describe the scene, motion, pacing, and any on-screen text."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "The scene to render (motion, pacing, on-screen text).",
                },
                "filename": {
                    "type": "string",
                    "description": "Optional name for the saved asset, e.g. 'launch-teaser'.",
                },
                "seconds": {
                    "type": "integer",
                    "description": "Optional target clip length in seconds (provider may clamp it).",
                },
                "on_brand": {
                    "type": "boolean",
                    "description": "Blend in the brand guidelines (default true).",
                },
            },
            "required": ["prompt"],
        },
    ),
]

_UNSUPPORTED_HINT = (
    "No media generator is connected. Ask the founder to set ABOS_MEDIA_GEN_PROVIDER "
    "and a Google API key (or add a per-company Nano Banana key), or call "
    "`request_capability`."
)
_NO_STORE_HINT = (
    "A generated image/video needs somewhere to live: ask the founder to connect "
    "Google Drive in Settings so the asset can be filed (or call `request_capability`)."
)


async def _resolve_media_gen(db, company_id) -> MediaGen | None:
    """The company's media generator — a per-company BYO Google key first, else global.

    Returns ``None`` (so the tool reports the capability unsupported) when neither a
    per-company key nor a globally configured provider is available.
    """
    from app.services import apikeys

    key = await apikeys.get_plaintext_key(db, company_id=company_id, provider=MEDIA_GEN_PROVIDER)
    if key:
        from app.integrations.nano_banana import NanoBananaMediaGen

        return NanoBananaMediaGen(api_key=key)
    return get_media_gen()


async def _brand_context(db, *, company_id, provider) -> str:
    """A clipped excerpt of the company's brand guidelines to steer generation.

    Best-effort: pulls the most recent readable text file from the ``brand`` folder.
    Returns ``""`` when there's no brand doc or it can't be read — generation still
    proceeds from the agent's prompt alone.
    """
    try:
        rows = await files_svc.list_files(db, company_id=company_id, category=FileCategory.brand)
    except Exception:  # noqa: BLE001 - brand context is optional; never block a render
        return ""
    for row in rows:
        if not row.external_id or not (row.mime_type or "").startswith("text"):
            continue
        try:
            data = await provider.download_file(row.external_id)
            return data.decode("utf-8")[:_BRAND_CONTEXT_CHARS]
        except (FileProviderError, UnicodeDecodeError):
            continue
    return ""


def _compose_prompt(prompt: str, brand: str, *, on_brand: bool) -> str:
    """Prepend the brand guidelines to the user's prompt when rendering on-brand."""
    if not on_brand or not brand.strip():
        return prompt
    return (
        "Follow these brand & design guidelines so the result is on-brand "
        f"(palette, typography, tone, visual style):\n{brand.strip()}\n\n"
        f"Now create: {prompt}"
    )


def _asset_filename(raw: str | None, prompt: str, mime_type: str) -> str:
    """A clean filename with the right extension for ``mime_type``."""
    base = (raw or "").strip() or prompt.strip()[:60] or "asset"
    ext = _EXT_BY_MIME.get(mime_type.lower(), "bin")
    base = files_svc.safe_filename(base)
    if base.lower().endswith(f".{ext}"):
        return base
    return f"{base}.{ext}"


async def _generate_and_file(
    db,
    ctx,
    *,
    agent: Agent,
    task: Task,
    args: dict,
    kind: str,
) -> ToolOutcome:
    """Shared flow for image/video: resolve providers, render (metered), file the asset."""
    prompt = str(args.get("prompt") or "").strip()
    if not prompt:
        return ToolOutcome(observation="A prompt is required.", is_error=True)

    media = await _resolve_media_gen(db, task.company_id)
    if media is None:
        return unsupported_capability(
            f"Generating {'a video' if kind == 'video' else 'an image'}",
            hint=_UNSUPPORTED_HINT,
        )
    file_provider = await resolve_file_provider(db, company_id=task.company_id)
    if file_provider is None:
        return unsupported_capability(
            f"Generating {'a video' if kind == 'video' else 'an image'}",
            hint=_NO_STORE_HINT,
        )
    company = await db.get(Company, task.company_id)
    if company is None:
        return ToolOutcome(observation="company not found; cannot generate.", is_error=True)

    on_brand = args.get("on_brand", True) is not False
    brand = await _brand_context(db, company_id=task.company_id, provider=file_provider)
    composed = _compose_prompt(prompt, brand, on_brand=on_brand)

    cost_cents = (
        settings.media_video_cost_cents if kind == "video" else settings.media_image_cost_cents
    )
    captured: dict = {}

    async def _do() -> tuple[int, str | None, dict | None]:
        if kind == "video":
            asset = await media.generate_video(composed, seconds=args.get("seconds"))
        else:
            asset = await media.generate_image(composed, aspect_ratio=args.get("aspect_ratio"))
        captured["asset"] = asset
        return cost_cents, None, {"kind": kind, "bytes": len(asset.data)}

    try:
        await ctx.cost_meter.metered_external(
            company_id=task.company_id,
            agent_id=agent.id,
            task_id=task.id,
            estimated_cents=cost_cents,
            vendor=f"media_gen({settings.media_gen_provider})",
            sku=prompt[:120],
            action=_do,
            description=f"generate {kind}: {prompt[:80]}",
        )
    except MediaGenError as exc:
        return ToolOutcome(observation=f"{kind} generation failed: {exc}", is_error=True)

    asset: GeneratedMedia = captured["asset"]

    # Self-validation: before filing an image, an independent critic actually
    # LOOKS at it (vision) and opinionates on quality/on-brand fit. If it's not
    # good enough (and rounds remain), the agent gets the critique and regenerates
    # with an improved prompt; only an approved image is filed. Videos can't be
    # shown to the vision critic, so they pass through.
    if kind == "image" and (asset.mime_type or "").startswith("image/"):
        brief = f"Prompt the agent used: {prompt}"
        if on_brand and brand.strip():
            brief += "\n(The image was meant to follow the company's brand guidelines.)"
        hold = await visual_gate(
            db,
            ctx,
            agent=agent,
            task=task,
            key="image",
            kind="marketing image",
            brief=brief,
            image=(asset.data, asset.mime_type),
        )
        if hold is not None:
            return hold

    filename = _asset_filename(args.get("filename"), prompt, asset.mime_type)
    try:
        row = await files_svc.archive(
            db,
            file_provider,
            company=company,
            category=FileCategory.brand,
            name=filename,
            content=asset.data,
            mime_type=asset.mime_type,
            source_task_id=task.id,
            description=f"Generated {kind} (Nano Banana): {prompt[:140]}",
        )
    except FileProviderError as exc:
        # The asset was generated and charged, but couldn't be filed — say so plainly
        # rather than implying it's retrievable.
        return ToolOutcome(
            observation=(
                f"generated the {kind} but filing it failed: {exc}. The asset was not "
                "saved — try again or check the file store."
            ),
            is_error=True,
        )

    await memory_svc.write(
        db,
        company_id=task.company_id,
        type=MemoryType.result,
        title=f"Generated {kind}: {row.name}"[:500],
        content=f"On-brand {kind} saved to {row.folder_path}/{row.name}."
        + (f"\nPrompt: {prompt[:300]}" if prompt else ""),
        source_task_id=task.id,
    )
    link = f" ({row.web_url})" if row.web_url else ""
    note = f" Model note: {asset.note}" if asset.note else ""
    return ToolOutcome(
        observation=f"generated {kind} and filed it at {row.folder_path}/{row.name}{link}.{note}"
    )


async def _generate_image(db, ctx, *, agent: Agent, task: Task, args: dict) -> ToolOutcome:
    return await _generate_and_file(db, ctx, agent=agent, task=task, args=args, kind="image")


async def _generate_video(db, ctx, *, agent: Agent, task: Task, args: dict) -> ToolOutcome:
    return await _generate_and_file(db, ctx, agent=agent, task=task, args=args, kind="video")


HANDLERS = {
    "generate_image": _generate_image,
    "generate_video": _generate_video,
}
