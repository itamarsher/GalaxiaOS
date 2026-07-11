"""Open-source-model providers over OpenAI-compatible endpoints.

Open-source models (Llama, DeepSeek, Qwen, gpt-oss, Mistral, …) are served
almost universally through an OpenAI-compatible API — by hosted aggregators
(OpenRouter, Groq, Together, Fireworks, DeepInfra) and by self-hosted servers
(vLLM, Ollama, TGI). So the whole "OSS alternative to Anthropic" is not a new
SDK integration: it is the existing :class:`OpenAIProvider` pointed at a
different ``base_url``.

This module imports **no** vendor SDK (only :class:`OpenAIProvider`, which owns
the single permitted ``openai`` import), so it stays on the right side of the
provider-boundary guard. Each provider below is BYOK: the founder stores a key
for the host in Settings and the runtime resolves it exactly like any other
provider (see ``apikeys.resolve_provider``).

Model slugs and prices are best-effort snapshots — aggregators rename/retire
models and change prices. Both are overridable per-agent (``Agent.model_pref``)
and per-deploy, and real spend always reconciles from ``response.usage`` after
the call, so a stale price only affects the pre-call reservation, never billing.
"""

from __future__ import annotations

from app.config import get_settings
from app.providers.base import Price
from app.providers.openai import OpenAIProvider

# Conservative OSS fallback used for a model id we don't have an explicit price
# for. Reservation reconciles from real usage afterwards, so a rough upper-ish
# bound is fine (and safer than under-reserving).
_DEFAULT_OSS_PRICE = Price(input_cents_per_mtok=100, output_cents_per_mtok=300)
_DEFAULT_OSS_MAX_OUTPUT = 16_384


class _OSSOpenAICompatProvider(OpenAIProvider):
    """Base for OSS hosts: same wire protocol as OpenAI, different endpoint.

    Subclasses set ``name``, ``base_url``, ``default_models`` and (optionally)
    their own ``price_table`` / ``max_output_table``. Price and max-output
    lookups read those class tables instead of delegating to ``pricing.py`` —
    that keeps the OSS catalog self-contained here and leaves ``pricing.py``'s
    Anthropic/OpenAI branches untouched.
    """

    #: model id -> price (cents per 1M tokens). Missing ids fall back below.
    price_table: dict[str, Price] = {}
    #: model id -> max output tokens per response. Missing ids fall back below.
    max_output_table: dict[str, int] = {}
    default_price: Price = _DEFAULT_OSS_PRICE
    default_max_output: int = _DEFAULT_OSS_MAX_OUTPUT

    def price(self, model: str) -> Price:
        return self.price_table.get(model, self.default_price)

    def max_output_tokens(self, model: str) -> int:
        return self.max_output_table.get(model, self.default_max_output)


class OpenRouterProvider(_OSSOpenAICompatProvider):
    """OpenRouter — one key routes to 300+ models across hosts (BYOK, no infra).

    The recommended default OSS alternative: passthrough pricing (no markup on
    the model, a small platform fee), ``:free`` model ids for $0 experiments,
    and one key unlocks Llama / DeepSeek / Qwen / gpt-oss / etc.
    """

    name = "openrouter"
    base_url = "https://openrouter.ai/api/v1"
    default_models = {
        "cheap": "openai/gpt-oss-120b",
        "planner": "meta-llama/llama-3.3-70b-instruct",
        "strategic": "deepseek/deepseek-r1",
    }
    # Cents per 1M tokens. Snapshot of OpenRouter list prices (2026-07); the cheap
    # host for each model can vary and OpenRouter adds a small credit fee, so treat
    # these as estimates — the reservation reconciles from real token usage after
    # the call. Refresh when OpenRouter's rates move.
    price_table = {
        "openai/gpt-oss-120b": Price(input_cents_per_mtok=3.6, output_cents_per_mtok=18),
        "meta-llama/llama-3.3-70b-instruct": Price(input_cents_per_mtok=10, output_cents_per_mtok=32),
        "deepseek/deepseek-r1": Price(input_cents_per_mtok=70, output_cents_per_mtok=250),
    }


class GroqProvider(_OSSOpenAICompatProvider):
    """Groq — very low latency OSS inference (BYOK)."""

    name = "groq"
    base_url = "https://api.groq.com/openai/v1"
    default_models = {
        "cheap": "llama-3.1-8b-instant",
        "planner": "llama-3.3-70b-versatile",
        "strategic": "deepseek-r1-distill-llama-70b",
    }
    price_table = {
        "llama-3.1-8b-instant": Price(input_cents_per_mtok=5, output_cents_per_mtok=8),
        "llama-3.3-70b-versatile": Price(input_cents_per_mtok=59, output_cents_per_mtok=79),
        "deepseek-r1-distill-llama-70b": Price(input_cents_per_mtok=75, output_cents_per_mtok=99),
    }


class TogetherProvider(_OSSOpenAICompatProvider):
    """Together AI — direct host with a broad OSS catalog (BYOK)."""

    name = "together"
    base_url = "https://api.together.xyz/v1"
    default_models = {
        "cheap": "meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo",
        "planner": "meta-llama/Llama-3.3-70B-Instruct-Turbo",
        "strategic": "deepseek-ai/DeepSeek-R1",
    }
    price_table = {
        "meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo": Price(input_cents_per_mtok=18, output_cents_per_mtok=18),
        "meta-llama/Llama-3.3-70B-Instruct-Turbo": Price(input_cents_per_mtok=88, output_cents_per_mtok=88),
        "deepseek-ai/DeepSeek-R1": Price(input_cents_per_mtok=300, output_cents_per_mtok=700),
    }


class OpenAICompatProvider(_OSSOpenAICompatProvider):
    """Generic self-hosted OpenAI-compatible endpoint (vLLM / Ollama / TGI).

    Unlike the fixed aggregators, its ``base_url`` and per-tier model slugs are
    deployment-specific, so they come from settings (``ABOS_OPENAI_COMPAT_*``).
    This provider is only registered when ``openai_compat_base_url`` is set (see
    the registry), so a founder can never store a key that resolves to a dead
    endpoint.

    JSON mode is off by default because self-hosted backends disagree on how to
    force structured output (Ollama: ``format: "json"``; vLLM: ``guided_json``),
    so we rely on the prompt's existing "return JSON" instruction rather than
    sending ``response_format`` to a server that may ignore or reject it.
    """

    name = "openai_compat"
    supports_json_mode = False

    def __init__(self) -> None:
        settings = get_settings()
        self.base_url = settings.openai_compat_base_url or None
        self.default_models = {
            "cheap": settings.openai_compat_model_cheap,
            "planner": settings.openai_compat_model_planner,
            "strategic": settings.openai_compat_model_strategic,
        }
