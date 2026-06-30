"""Offline unit tests for the Nano Banana / Veo media adapter (no network)."""

from __future__ import annotations

import base64

import pytest

from app.integrations.mediagen import GeneratedMedia, MediaGenError, get_media_gen
from app.integrations.nano_banana import NanoBananaMediaGen

_PNG = b"\x89PNG\r\n\x1a\nfake-bytes"
_B64 = base64.b64encode(_PNG).decode()


def test_parse_image_extracts_inline_data_and_note():
    body = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {"text": "Here is your banner."},
                        {"inlineData": {"mimeType": "image/png", "data": _B64}},
                    ]
                }
            }
        ]
    }
    media = NanoBananaMediaGen._parse_image(body)
    assert isinstance(media, GeneratedMedia)
    assert media.data == _PNG
    assert media.mime_type == "image/png"
    assert media.note == "Here is your banner."


def test_parse_image_tolerates_snake_case_and_defaults_mime():
    body = {"candidates": [{"content": {"parts": [{"inline_data": {"data": _B64}}]}}]}
    media = NanoBananaMediaGen._parse_image(body)
    assert media.data == _PNG
    assert media.mime_type == "image/png"  # default when none reported


def test_parse_image_raises_when_no_image():
    # Model returned only text (e.g. a refusal) -> no phantom asset.
    body = {"candidates": [{"content": {"parts": [{"text": "I can't do that."}]}}]}
    with pytest.raises(MediaGenError):
        NanoBananaMediaGen._parse_image(body)


def test_parse_image_raises_on_bad_base64():
    body = {"candidates": [{"content": {"parts": [{"inlineData": {"data": "!!!not base64!!!"}}]}}]}
    with pytest.raises(MediaGenError):
        NanoBananaMediaGen._parse_image(body)


def test_parse_operation_returns_download_uri():
    op = {
        "done": True,
        "response": {
            "generateVideoResponse": {
                "generatedSamples": [{"video": {"uri": "https://files.test/clip"}}]
            }
        },
    }
    uri, inline = NanoBananaMediaGen._parse_operation(op)
    assert uri == "https://files.test/clip"
    assert inline is None


def test_parse_operation_returns_inline_video():
    op = {
        "done": True,
        "response": {
            "generateVideoResponse": {
                "generatedSamples": [
                    {"video": {"inlineData": {"mimeType": "video/mp4", "data": _B64}}}
                ]
            }
        },
    }
    uri, inline = NanoBananaMediaGen._parse_operation(op)
    assert uri is None
    assert inline is not None
    assert inline.data == _PNG
    assert inline.mime_type == "video/mp4"


def test_parse_operation_raises_on_error_or_empty():
    with pytest.raises(MediaGenError):
        NanoBananaMediaGen._parse_operation({"error": {"message": "blocked"}})
    with pytest.raises(MediaGenError):
        NanoBananaMediaGen._parse_operation({"response": {"generateVideoResponse": {}}})


@pytest.mark.asyncio
async def test_missing_key_raises_without_network():
    gen = NanoBananaMediaGen(api_key="")  # explicit empty -> no settings, no HTTP
    with pytest.raises(MediaGenError):
        await gen.generate_image("a logo")
    with pytest.raises(MediaGenError):
        await gen.generate_video("a clip")


def test_resolver_selects_google_and_simulated_is_none():
    assert isinstance(get_media_gen("google"), NanoBananaMediaGen)
    assert isinstance(get_media_gen("nano_banana"), NanoBananaMediaGen)
    assert get_media_gen("simulated") is None
    assert get_media_gen("none") is None


def test_resolver_rejects_unknown_provider():
    with pytest.raises(ValueError):
        get_media_gen("midjourney")
