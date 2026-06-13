"""Provider registry: name → :class:`LLMProvider` instance.

Adding OpenAI/Gemini later = implement the Protocol in a new module and register
it here. No call-site changes.
"""

from __future__ import annotations

from app.providers.anthropic import AnthropicProvider
from app.providers.base import LLMProvider

_PROVIDERS: dict[str, LLMProvider] = {
    "anthropic": AnthropicProvider(),
}


def get_provider(name: str) -> LLMProvider:
    try:
        return _PROVIDERS[name]
    except KeyError as exc:
        raise ValueError(f"Unknown LLM provider: {name!r}") from exc


def supported_providers() -> list[str]:
    return list(_PROVIDERS)
