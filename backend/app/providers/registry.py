"""Provider registry: name → :class:`LLMProvider` instance.

Adding OpenAI/Gemini later = implement the Protocol in a new module and register
it here. No call-site changes.
"""

from __future__ import annotations

from app.config import settings
from app.providers.anthropic import AnthropicProvider
from app.providers.base import LLMProvider
from app.providers.openai import OpenAIProvider
from app.providers.oss import (
    GroqProvider,
    OpenAICompatProvider,
    OpenRouterProvider,
    TogetherProvider,
)

_PROVIDERS: dict[str, LLMProvider] = {
    "anthropic": AnthropicProvider(),
    "openai": OpenAIProvider(),
    # Open-source models over OpenAI-compatible hosts (BYOK, no infra).
    "openrouter": OpenRouterProvider(),
    "groq": GroqProvider(),
    "together": TogetherProvider(),
}

# The generic self-hosted endpoint is only usable when an endpoint URL is
# configured. Registering it unconditionally would let a founder store a key
# that get_active_key() accepts (it filters on supported_providers()) but that
# resolves to a dead endpoint, so gate it on the setting.
if settings.openai_compat_base_url:
    _PROVIDERS["openai_compat"] = OpenAICompatProvider()


def get_provider(name: str) -> LLMProvider:
    try:
        return _PROVIDERS[name]
    except KeyError as exc:
        raise ValueError(f"Unknown LLM provider: {name!r}") from exc


def supported_providers() -> list[str]:
    return list(_PROVIDERS)
