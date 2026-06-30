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
                resp = await client.post(url, json=body)
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as exc:
            raise MediaGenError(f"Nano Banana image request failed: {exc}") from exc
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
                resp = await client.post(start_url, json=body)
                resp.raise_for_status()
                op = resp.json()
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
            raise MediaGenError(f"Veo video request failed: {exc}") from exc
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
