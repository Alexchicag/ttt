from __future__ import annotations

import logging
import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Optional

from scipy.stats import norm

from config import CITIES
from polymarket_client import PolymarketMarket, TempRange
from weather_fetcher import WeatherForecast

logger = logging.getLogger(__name__)


@dataclass
class EdgeResult:
    """Edge calculation result for a single market."""

    market: PolymarketMarket
    city_key: str
    target_date: date

    gfs_probability: float  # Our GFS-derived probability for YES
    market_price: float     # The side's current market price (implied prob)
    side: str               # "YES" or "NO"
    edge: float             # Signed: gfs_prob(side) − market_price(side)
    effective_edge: float   # abs(edge) — used for ranking


# ── Probability engine ────────────────────────────────────────────────────────

def _gaussian_prob(tr: TempRange, mean_f: float, sigma_f: float) -> float:
    """
    Probability that the daily high falls in the bracket described by TempRange,
    modelled as Gaussian(mean_f, sigma_f).

    For a discrete 1°F bucket [lo, hi] we integrate over [lo−0.5, hi+0.5].
    For open brackets we integrate to ±∞.
    """
    if sigma_f <= 0.0:
        sigma_f = 0.5  # Guard against zero-sigma

    if tr.is_above and tr.low is not None:
        # P(T ≥ threshold)
        p = 1.0 - norm.cdf(tr.low, loc=mean_f, scale=sigma_f)

    elif tr.is_below and tr.high is not None:
        # P(T < threshold)
        p = norm.cdf(tr.high, loc=mean_f, scale=sigma_f)

    elif tr.low is not None and tr.high is not None:
        # P(lo − 0.5 ≤ T ≤ hi + 0.5)
        p = norm.cdf(tr.high + 0.5, loc=mean_f, scale=sigma_f) - \
            norm.cdf(tr.low - 0.5, loc=mean_f, scale=sigma_f)

    else:
        return 0.5  # Unrecognised bracket

    return float(max(1e-6, min(1.0 - 1e-6, p)))


def _edge_for_market(
    market: PolymarketMarket,
    forecast: WeatherForecast,
) -> Optional[EdgeResult]:
    """
    Compute edge for a single market.
    Total sigma = quadrature sum of ensemble spread + city-specific RMSE.
    We evaluate both YES and NO sides and return the better one.
    """
    city = CITIES.get(market.city_key)
    if city is None:
        return None

    # Combined uncertainty: ensemble spread ⊕ historical RMSE
    sigma = math.sqrt(forecast.temp_std_f ** 2 + city.rmse ** 2)

    # GFS probability for YES outcome
    p_yes = _gaussian_prob(market.temp_range, forecast.temp_mean_f, sigma)
    p_no = 1.0 - p_yes

    # Edge on each side  (gfs_prob − implied_market_prob)
    edge_yes = p_yes - market.yes_price
    edge_no  = p_no  - market.no_price

    if abs(edge_yes) >= abs(edge_no):
        side, edge, market_price, gfs_prob = "YES", edge_yes, market.yes_price, p_yes
    else:
        side, edge, market_price, gfs_prob = "NO",  edge_no,  market.no_price,  p_no

    return EdgeResult(
        market=market,
        city_key=market.city_key,
        target_date=market.target_date,
        gfs_probability=gfs_prob,
        market_price=market_price,
        side=side,
        edge=edge,
        effective_edge=abs(edge),
    )


# ── Public entry point ────────────────────────────────────────────────────────

def find_best_edges(
    markets: list[PolymarketMarket],
    forecasts: dict[str, dict[date, WeatherForecast]],
    edge_threshold: float,
) -> list[EdgeResult]:
    """
    Identify the single best trade per (city, date) event.

    CRITICAL: Temperature markets for the same event (e.g. "NYC April 15") have
    10–15 mutually exclusive brackets.  Only ONE can win; betting multiple
    brackets guarantees net losses (3–4 losing $2 bets vs 1 winning $2 bet).

    Algorithm:
        1. Compute edge for every market.
        2. Group by (city_key, target_date).
        3. Within each group retain only results above edge_threshold.
        4. Return the single highest-edge result per group.

    Returns a list of at most one EdgeResult per (city, date) pair.
    """
    # Group all edge results by event key
    event_buckets: dict[tuple[str, date], list[EdgeResult]] = defaultdict(list)

    for market in markets:
        city_forecasts = forecasts.get(market.city_key, {})
        forecast = city_forecasts.get(market.target_date)
        if forecast is None:
            logger.debug(
                "No forecast for %s on %s — skipping market",
                market.city_key, market.target_date,
            )
            continue

        result = _edge_for_market(market, forecast)
        if result is None:
            continue

        event_buckets[(market.city_key, market.target_date)].append(result)

    # Pick the single best per event
    best_per_event: list[EdgeResult] = []

    for (city_key, target_date), results in event_buckets.items():
        n_total = len(results)
        qualifying = [r for r in results if r.effective_edge >= edge_threshold]

        if not qualifying:
            best_seen = max((r.effective_edge for r in results), default=0.0)
            logger.debug(
                "No qualifying edge for %s %s (best %.1f%% < threshold %.1f%%)",
                city_key, target_date,
                best_seen * 100, edge_threshold * 100,
            )
            continue

        # The one winner
        winner = max(qualifying, key=lambda r: r.effective_edge)
        skipped = n_total - 1

        logger.info(
            "EVENT %s %s → betting %s %s @ %.2f  "
            "edge=+%.1f%%  gfs=%.1f%%  [skipping %d other bracket%s]",
            city_key, target_date,
            winner.side, winner.market.temp_range.label(),
            winner.market_price,
            winner.effective_edge * 100,
            winner.gfs_probability * 100,
            skipped, "s" if skipped != 1 else "",
        )
        best_per_event.append(winner)

    return best_per_event
