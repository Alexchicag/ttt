from __future__ import annotations

import logging
from dataclasses import dataclass

from config import (
    KELLY_FRACTION,
    MAX_BANKROLL_FRACTION,
    MAX_MARKET_USD,
    MAX_TRADE_USD,
    MIN_BET_USD,
)

logger = logging.getLogger(__name__)


@dataclass
class BetSize:
    amount_usd: float           # Final bet amount after all caps
    kelly_fraction_raw: float   # Full (un-fractioned) Kelly f*
    kelly_fraction_used: float  # Fractional Kelly after caps
    capped_by: str              # Which cap limited the size ("none", "bankroll", "trade", "market")


_ZERO = BetSize(
    amount_usd=0.0,
    kelly_fraction_raw=0.0,
    kelly_fraction_used=0.0,
    capped_by="zero",
)


def compute_kelly_bet(
    edge: float,
    market_price: float,
    bankroll: float,
    market_exposure_usd: float = 0.0,
) -> BetSize:
    """
    Compute the optimal bet size using fractional Kelly criterion.

    Parameters
    ----------
    edge : float
        Raw edge = gfs_probability − market_price  (already directional for the
        chosen side, so must be > 0 for a sensible bet).
    market_price : float
        Implied probability of the outcome we are buying (0 < price < 1).
    bankroll : float
        Current liquid USDC balance.
    market_exposure_usd : float
        USD already risked in this specific market (for per-market cap).

    Kelly formula (binary outcome)
    ──────────────────────────────
        b  = net decimal odds  = (1 / price) − 1
        p  = our probability   = market_price + edge
        q  = 1 − p
        f* = (b·p − q) / b

    We apply:
        1. KELLY_FRACTION multiplier  (fractional Kelly, default 15 %)
        2. MAX_BANKROLL_FRACTION cap  (5 % of bankroll)
        3. MAX_TRADE_USD hard cap     ($2)
        4. MAX_MARKET_USD per-market  (remaining room up to $4)
    """
    if bankroll <= 0.0 or market_price <= 0.0 or market_price >= 1.0:
        return _ZERO

    if edge <= 0.0:
        logger.debug("Non-positive edge (%.4f) — no bet", edge)
        return _ZERO

    # Decimal odds (net) for the favourable outcome
    b = (1.0 / market_price) - 1.0
    if b <= 0.0:
        return _ZERO

    # Our true probability estimate
    p = market_price + edge
    p = max(1e-6, min(1.0 - 1e-6, p))
    q = 1.0 - p

    # Full Kelly fraction
    kelly_f = (b * p - q) / b
    if kelly_f <= 0.0:
        logger.debug("Kelly f* ≤ 0 (%.4f) — no edge after odds adjustment", kelly_f)
        return _ZERO

    # ── Apply fractional Kelly ────────────────────────────────────────────────
    fractional_f = kelly_f * KELLY_FRACTION

    # ── Bankroll cap ──────────────────────────────────────────────────────────
    capped_by = "none"
    if fractional_f > MAX_BANKROLL_FRACTION:
        fractional_f = MAX_BANKROLL_FRACTION
        capped_by = "bankroll"

    amount = fractional_f * bankroll

    # ── Per-trade USD cap ─────────────────────────────────────────────────────
    if amount > MAX_TRADE_USD:
        amount = MAX_TRADE_USD
        capped_by = "trade"

    # ── Per-market USD cap ────────────────────────────────────────────────────
    market_room = MAX_MARKET_USD - market_exposure_usd
    if amount > market_room:
        amount = market_room
        capped_by = "market"

    amount = max(0.0, round(amount, 2))

    if amount < MIN_BET_USD:
        logger.debug(
            "Bet amount $%.2f below minimum $%.2f — skipping",
            amount, MIN_BET_USD,
        )
        return _ZERO

    logger.debug(
        "Kelly sizing: f*=%.4f  fractional=%.4f  amount=$%.2f  capped_by=%s",
        kelly_f, fractional_f, amount, capped_by,
    )

    return BetSize(
        amount_usd=amount,
        kelly_fraction_raw=kelly_f,
        kelly_fraction_used=fractional_f,
        capped_by=capped_by,
    )
