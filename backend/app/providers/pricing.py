"""Model → price table. Single edit point for cost metering.

Prices are in **cents per 1M tokens**. Verified against the current Claude
lineup; update here (and ``config.py`` model defaults) when prices/models rotate.
"""

from __future__ import annotations

from app.providers.base import Price

# Anthropic / Claude (USD cents per 1M tokens)
ANTHROPIC_PRICES: dict[str, Price] = {
    "claude-haiku-4-5": Price(input_cents_per_mtok=100, output_cents_per_mtok=500),
    "claude-sonnet-4-6": Price(input_cents_per_mtok=300, output_cents_per_mtok=1500),
    "claude-opus-4-8": Price(input_cents_per_mtok=500, output_cents_per_mtok=2500),
}

# OpenAI (USD cents per 1M tokens)
OPENAI_PRICES: dict[str, Price] = {
    "gpt-4o": Price(input_cents_per_mtok=250, output_cents_per_mtok=1000),
    "gpt-4o-mini": Price(input_cents_per_mtok=15, output_cents_per_mtok=60),
}

# Conservative fallback for an unknown model id (treat as Opus-tier).
DEFAULT_PRICE = Price(input_cents_per_mtok=500, output_cents_per_mtok=2500)

# Per-provider default when the model id is unknown.
OPENAI_DEFAULT_PRICE = OPENAI_PRICES["gpt-4o"]


def price_for(provider: str, model: str) -> Price:
    if provider == "anthropic":
        return ANTHROPIC_PRICES.get(model, DEFAULT_PRICE)
    if provider == "openai":
        return OPENAI_PRICES.get(model, OPENAI_DEFAULT_PRICE)
    return DEFAULT_PRICE


# Maximum output tokens (per response) each model supports. Used to size
# generous ``max_tokens`` ceilings without exceeding what the model accepts.
ANTHROPIC_MAX_OUTPUT_TOKENS: dict[str, int] = {
    "claude-haiku-4-5": 64_000,
    "claude-sonnet-4-6": 64_000,
    "claude-opus-4-8": 128_000,
}

OPENAI_MAX_OUTPUT_TOKENS: dict[str, int] = {
    "gpt-4o": 16_384,
    "gpt-4o-mini": 16_384,
}

# Conservative fallback for an unknown model id.
DEFAULT_MAX_OUTPUT_TOKENS = 16_384


def max_output_tokens(provider: str, model: str) -> int:
    if provider == "anthropic":
        return ANTHROPIC_MAX_OUTPUT_TOKENS.get(model, DEFAULT_MAX_OUTPUT_TOKENS)
    if provider == "openai":
        return OPENAI_MAX_OUTPUT_TOKENS.get(model, DEFAULT_MAX_OUTPUT_TOKENS)
    return DEFAULT_MAX_OUTPUT_TOKENS


# Total context window (max input tokens) each model accepts. Used to size how
# much text a tool may hand an agent in a single observation — e.g. a file read
# is capped at the reading model's window rather than an arbitrary fixed length.
ANTHROPIC_CONTEXT_WINDOW_TOKENS: dict[str, int] = {
    "claude-haiku-4-5": 200_000,
    "claude-sonnet-4-6": 200_000,
    "claude-opus-4-8": 200_000,
}

OPENAI_CONTEXT_WINDOW_TOKENS: dict[str, int] = {
    "gpt-4o": 128_000,
    "gpt-4o-mini": 128_000,
}

# Conservative fallback for an unknown model id.
DEFAULT_CONTEXT_WINDOW_TOKENS = 128_000


def context_window_tokens(provider: str, model: str) -> int:
    if provider == "anthropic":
        return ANTHROPIC_CONTEXT_WINDOW_TOKENS.get(model, DEFAULT_CONTEXT_WINDOW_TOKENS)
    if provider == "openai":
        return OPENAI_CONTEXT_WINDOW_TOKENS.get(model, DEFAULT_CONTEXT_WINDOW_TOKENS)
    return DEFAULT_CONTEXT_WINDOW_TOKENS
