"""Google **Nano Banana** (+ Veo) media adapter — REAL brand media (credential-gated).

Nano Banana is Google's Gemini image model; it returns the rendered image inline as
base64 in the ``generateContent`` response, which maps directly onto
:class:`GeneratedMedia`. Short video clips go through **Veo**, whose generation is a
long-running operation: we kick it off with ``predictLongRunning`` and poll the
operation until it reports ``done`` (bounded by a timeout), then download the produced
clip. Both calls use the company's Generative Language API key
(``ABOS_GOOGLE_API_KEY``, or a per-company BYO key); without it the methods raise
:class:`MediaGenError` rather than hitting the network.

Off by default (``ABOS_MEDIA_GEN_PROVIDER=simulated``). Enable with
``ABOS_MEDIA_GEN_PROVIDER=google`` and a key. The response shapes are parsed by the
pure :meth:`_parse_image` / :meth:`_parse_operation` staticmethods so media extraction
is unit-testable offline.
"""

from __future__ import annotations

import asyncio
import base64
import binascii

import httpx

from app.config import settings
from app.integrations.mediagen import GeneratedMedia, MediaGenError

_API_ROOT = "https://generativelanguage.googleapis.com/v1beta"


def _explain_http_error(exc: httpx.HTTPError, *, what: str, retries: int = 0) -> MediaGenError:
    """Turn a raw Google API HTTP error into an actionable :class:`MediaGenError`.

    The bare httpx message (e.g. "Client error '429 Too Many Requests'") hides the
    reason. A 429 on the image model can mean two different things: the key's project
    has genuinely no image quota — the Gemini **free tier allows 0 image-generation
    requests**, so it needs billing enabled rather than a retry — or it's ordinary
    transient per-minute rate limiting on a paid project, which a short backoff clears.
    Only the former is diagnosed from Google's error detail (a ``free_tier`` marker or
    a ``limit: 0``-style quota); anything else after retries are exhausted is reported
    as genuine rate-limiting instead, so the agent doesn't chase a billing fix that
    won't help.
    """
    resp = getattr(exc, "response", None)
    status = getattr(resp, "status_code", None)
    detail = ""
    if resp is not None:
        try:
            detail = (resp.json().get("error", {}) or {}).get("message", "") or ""
        except Exception:  # noqa: BLE001 - best-effort detail extraction
            detail = (getattr(resp, "text", "") or "")[:300]
    said = f" Google said: {detail[:220]}" if detail else ""
    if status == 429:
        lowered = detail.lower()
        if "free_tier" in lowered or "limit: 0" in lowered or "limit:0" in lowered:
            return MediaGenError(
                f"{what} was refused for lack of quota (HTTP 429). Image/video generation "
                "is not available on the Gemini free tier — enable billing on the Google AI "
                "(Gemini API) project behind this key, or use a key from a paid project."
                + said
            )
        retried_note = f" after {retries} retr{'y' if retries == 1 else 'ies'}" if retries else ""
        return MediaGenError(
            f"{what} is still rate-limited (HTTP 429){retried_note} — this looks like "
            "transient per-minute throttling rather than a quota block. Check the "
            "project's Generative Language API quota, or try again shortly." + said
        )
    if status in (401, 403):
        return MediaGenError(
            f"{what} was rejected (HTTP {status}) — the media key is invalid or lacks "
            "access to this model." + said
        )
    return MediaGenError(f"{what} failed: {exc}")


def _retry_delay(resp: httpx.Response, attempt: int, backoff_seconds: float) -> float:
    """Delay before the next attempt: honor ``Retry-After`` if present, else backoff."""
    retry_after = resp.headers.get("Retry-After")
    if retry_after:
        try:
            return max(0.0, float(retry_after))
        except ValueError:
            pass
    return backoff_seconds * (2**attempt)


async def _post_json_with_retry(
    client: httpx.AsyncClient, url: str, body: dict, *, what: str
) -> dict:
    """POST expecting a JSON body, retrying a bounded number of times on HTTP 429.

    Other statuses fail fast via :func:`_explain_http_error`; only 429 is retried,
    since it's the sole status that can mean transient rate-limiting rather than a
    permanent problem with the request or key.
    """
    max_retries = settings.media_gen_max_retries
    backoff = settings.media_gen_retry_backoff_seconds
    attempt = 0
    while True:
        resp = await client.post(url, json=body)
        if resp.status_code == 429 and attempt < max_retries:
            await asyncio.sleep(_retry_delay(resp, attempt, backoff))
            attempt += 1
            continue
        try:
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise _explain_http_error(exc, what=what, retries=attempt) from exc
        return resp.json()


class NanoBananaMediaGen:
    def __init__(
        self,
        api_key: str | None = None,
        *,
        image_model: str | None = None,
        video_model: str | None = None,
        timeout: float | None = None,
    ) -> None:
        self._api_key = api_key if api_key is not None else settings.google_api_key
        self._image_model = image_model or settings.nano_banana_image_model
        self._video_model = video_model or settings.nano_banana_video_model
        self._timeout = timeout if timeout is not None else settings.media_gen_timeout_seconds

    def _require_key(self) -> str:
        if not self._api_key:
            raise MediaGenError(
                "Google API key missing (set ABOS_GOOGLE_API_KEY or add a per-company key)."
            )
        return self._api_key

    async def generate_image(
        self, prompt: str, *, aspect_ratio: str | None = None
    ) -> GeneratedMedia:
        key = self._require_key()
        # Aspect ratio is steered in-prompt rather than via a config field so the call
        # stays valid across API revisions of the image model.
        full_prompt = prompt
        if aspect_ratio:
            full_prompt = f"{prompt}\n\nRender this image with a {aspect_ratio} aspect ratio."
        url = f"{_API_ROOT}/models/{self._image_model}:generateContent?key={key}"
        body = {"contents": [{"parts": [{"text": full_prompt}]}]}
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                data = await _post_json_with_retry(
                    client, url, body, what="Nano Banana image generation"
                )
        except ValueError as exc:  # non-JSON body
            raise MediaGenError(f"Nano Banana returned non-JSON: {exc}") from exc
        return self._parse_image(data)

    async def generate_video(self, prompt: str, *, seconds: int | None = None) -> GeneratedMedia:
        key = self._require_key()
        params: dict = {}
        if seconds:
            params["durationSeconds"] = int(seconds)
        start_url = f"{_API_ROOT}/models/{self._video_model}:predictLongRunning?key={key}"
        body: dict = {"instances": [{"prompt": prompt}]}
        if params:
            body["parameters"] = params
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                op = await _post_json_with_retry(
                    client, start_url, body, what="Veo video generation"
                )
                op_name = op.get("name")
                if not op_name:
                    raise MediaGenError("Veo did not return an operation to poll.")
                # Poll the long-running operation until it completes or we time out.
                deadline = settings.media_gen_video_max_wait_seconds
                waited = 0.0
                interval = max(1.0, settings.media_gen_video_poll_seconds)
                op_url = f"{_API_ROOT}/{op_name}?key={key}"
                while not op.get("done"):
                    if waited >= deadline:
                        raise MediaGenError(
                            f"Veo video generation timed out after {int(deadline)}s."
                        )
                    await asyncio.sleep(interval)
                    waited += interval
                    poll = await client.get(op_url)
                    poll.raise_for_status()
                    op = poll.json()
                uri, inline = self._parse_operation(op)
                if inline is not None:
                    return inline
                # Veo commonly returns a file URI we must download (auth via the key).
                dl = await client.get(f"{uri}&key={key}" if "?" in uri else f"{uri}?key={key}")
                dl.raise_for_status()
                mime = dl.headers.get("content-type", "video/mp4").split(";")[0].strip()
                return GeneratedMedia(data=dl.content, mime_type=mime or "video/mp4")
        except httpx.HTTPError as exc:
            raise _explain_http_error(exc, what="Veo video generation") from exc
        except ValueError as exc:  # non-JSON body
            raise MediaGenError(f"Veo returned non-JSON: {exc}") from exc

    @staticmethod
    def _parse_image(body: dict) -> GeneratedMedia:
        """Pull the first inline image out of a ``generateContent`` response.

        The image model returns its render as ``inlineData`` (base64 + mimeType) inside
        a candidate's content parts; a leading text part may carry a caption. Raises
        :class:`MediaGenError` when the body carries no decodable image (e.g. the model
        refused or only returned text) so the tool never reports a phantom asset.
        """
        note: str | None = None
        for candidate in body.get("candidates") or []:
            parts = ((candidate.get("content") or {}).get("parts")) or []
            for part in parts:
                inline = part.get("inlineData") or part.get("inline_data")
                if inline and inline.get("data"):
                    try:
                        raw = base64.b64decode(inline["data"])
                    except (binascii.Error, ValueError) as exc:
                        raise MediaGenError(f"image data was not valid base64: {exc}") from exc
                    mime = inline.get("mimeType") or inline.get("mime_type") or "image/png"
                    return GeneratedMedia(data=raw, mime_type=mime, note=note)
                if part.get("text") and note is None:
                    note = str(part["text"]).strip() or None
        raise MediaGenError("the model returned no image (it may have refused the prompt).")

    @staticmethod
    def _parse_operation(op: dict) -> tuple[str | None, GeneratedMedia | None]:
        """From a completed Veo operation, return ``(download_uri, inline_media)``.

        Veo returns either a file URI to fetch or, less commonly, the bytes inline.
        Returns the URI to download when present, or a ready :class:`GeneratedMedia`
        when the clip is inline; raises :class:`MediaGenError` if the operation errored
        or carries no video.
        """
        if op.get("error"):
            msg = (op["error"] or {}).get("message", "unknown error")
            raise MediaGenError(f"Veo reported an error: {msg}")
        resp = op.get("response") or {}
        gen = resp.get("generateVideoResponse") or resp
        samples = gen.get("generatedSamples") or gen.get("generated_samples") or []
        for sample in samples:
            video = sample.get("video") or {}
            uri = video.get("uri") or video.get("url")
            if uri:
                return uri, None
            inline = video.get("inlineData") or video.get("data")
            if isinstance(inline, dict) and inline.get("data"):
                try:
                    raw = base64.b64decode(inline["data"])
                except (binascii.Error, ValueError) as exc:
                    raise MediaGenError(f"video data was not valid base64: {exc}") from exc
                mime = inline.get("mimeType") or inline.get("mime_type") or "video/mp4"
                return None, GeneratedMedia(data=raw, mime_type=mime)
        raise MediaGenError("Veo completed but returned no video sample.")
