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

# Conservative fallback for an unknown model id (treat as Opus-tier).
DEFAULT_PRICE = Price(input_cents_per_mtok=500, output_cents_per_mtok=2500)


def price_for(provider: str, model: str) -> Price:
    if provider == "anthropic":
        return ANTHROPIC_PRICES.get(model, DEFAULT_PRICE)
    return DEFAULT_PRICE
