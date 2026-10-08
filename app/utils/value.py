"""Rarity score for a username - and nothing that pretends to be a price.

This used to also return an "illustrative TON band" from a hard-coded table by
length. It was not market data: it was a number invented in this file, shown to
users next to a real Fragment listing count, and it read as a valuation. A made-up
price is worse than no price, so it is gone. The only price the bot quotes now
comes from :func:`app.collectible.valuation.price_basis`, which is built from
live Fragment listings and reports the spread and the count it rests on.

What remains is honest and local: a **rarity score** derived from the same rubric
the search itself uses, so the two numbers can never disagree.
"""

from __future__ import annotations

from app.search.pattern import is_real_word, rate

# A short list of well-known brands. Buying a handle that matches one invites a
# trademark complaint, which the market prices as a discount - worth a warning.
BRANDS = {
    "google", "apple", "nike", "adidas", "microsoft", "amazon", "meta",
    "facebook", "instagram", "telegram", "whatsapp", "tiktok", "youtube",
    "netflix", "spotify", "tesla", "openai", "samsung", "intel", "nvidia",
    "paypal", "visa", "mastercard", "binance", "coinbase", "ethereum",
    "bitcoin", "revolut", "uber", "airbnb", "coca", "pepsi", "disney",
}


def is_brand(name: str) -> bool:
    return name.strip().lstrip("@").lower() in BRANDS


def estimate_value(name: str) -> dict:
    """A rarity score (0-100) and whether the name is a real dictionary word.

    ``wordlike`` is :func:`app.search.pattern.is_real_word` - a real membership
    test against the dictionary, not a guess about how the string looks. It is
    what the result screen uses to say "this is a real word", so it must be true
    when it is shown.
    """
    clean = (name or "").strip().lower()
    return {
        "score": rate(clean).total,
        "wordlike": is_real_word(clean),
    }
