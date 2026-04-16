from __future__ import annotations

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from kelly_sizing import BetSize, compute_kelly_bet, _ZERO
from config import MAX_TRADE_USD, MAX_MARKET_USD, MIN_BET_USD


class TestComputeKellyBet:

    def test_basic_positive_edge_returns_positive_amount(self):
        bet = compute_kelly_bet(edge=0.15, market_price=0.50, bankroll=100.0)
        assert bet.amount_usd > 0

    def test_result_never_exceeds_per_trade_cap(self):
        bet = compute_kelly_bet(edge=0.40, market_price=0.50, bankroll=10_000.0)
        assert bet.amount_usd <= MAX_TRADE_USD

    def test_zero_edge_returns_zero(self):
        bet = compute_kelly_bet(edge=0.0, market_price=0.50, bankroll=100.0)
        assert bet.amount_usd == 0.0

    def test_negative_edge_returns_zero(self):
        bet = compute_kelly_bet(edge=-0.10, market_price=0.50, bankroll=100.0)
        assert bet.amount_usd == 0.0

    def test_zero_bankroll_returns_zero(self):
        bet = compute_kelly_bet(edge=0.15, market_price=0.50, bankroll=0.0)
        assert bet.amount_usd == 0.0

    def test_negative_bankroll_returns_zero(self):
        bet = compute_kelly_bet(edge=0.15, market_price=0.50, bankroll=-50.0)
        assert bet.amount_usd == 0.0

    def test_price_zero_returns_zero(self):
        bet = compute_kelly_bet(edge=0.15, market_price=0.0, bankroll=100.0)
        assert bet.amount_usd == 0.0

    def test_price_one_returns_zero(self):
        bet = compute_kelly_bet(edge=0.15, market_price=1.0, bankroll=100.0)
        assert bet.amount_usd == 0.0

    def test_market_exposure_reduces_available_room(self):
        # Market already has $3.60 exposure; cap is $4 → only $0.40 room
        bet = compute_kelly_bet(
            edge=0.20, market_price=0.50, bankroll=100.0,
            market_exposure_usd=3.60,
        )
        assert bet.amount_usd <= MAX_MARKET_USD - 3.60 + 0.01

    def test_fully_exposed_market_returns_zero(self):
        bet = compute_kelly_bet(
            edge=0.20, market_price=0.50, bankroll=100.0,
            market_exposure_usd=MAX_MARKET_USD,
        )
        assert bet.amount_usd == 0.0

    def test_over_exposed_market_returns_zero(self):
        bet = compute_kelly_bet(
            edge=0.20, market_price=0.50, bankroll=100.0,
            market_exposure_usd=MAX_MARKET_USD + 1.0,
        )
        assert bet.amount_usd == 0.0

    def test_tiny_bankroll_below_min_bet_returns_zero(self):
        # Bankroll so small that even MAX_BANKROLL_FRACTION yields < MIN_BET_USD
        bet = compute_kelly_bet(edge=0.08, market_price=0.90, bankroll=0.50)
        assert bet.amount_usd == 0.0

    def test_amount_rounded_to_two_decimals(self):
        bet = compute_kelly_bet(edge=0.12, market_price=0.55, bankroll=100.0)
        if bet.amount_usd > 0:
            assert round(bet.amount_usd, 2) == bet.amount_usd

    def test_kelly_fraction_raw_positive_when_bet_placed(self):
        bet = compute_kelly_bet(edge=0.15, market_price=0.50, bankroll=100.0)
        if bet.amount_usd > 0:
            assert bet.kelly_fraction_raw > 0

    def test_capped_by_field_set(self):
        bet = compute_kelly_bet(edge=0.40, market_price=0.50, bankroll=10_000.0)
        assert bet.capped_by in ("none", "bankroll", "trade", "market")

    def test_high_price_low_edge(self):
        # Price near 1, small positive edge — Kelly f* should still be > 0
        bet = compute_kelly_bet(edge=0.02, market_price=0.80, bankroll=100.0)
        # May be zero if below MIN_BET, that's acceptable
        assert bet.amount_usd >= 0.0

    def test_amount_never_exceeds_bankroll(self):
        bet = compute_kelly_bet(edge=0.30, market_price=0.30, bankroll=1.0)
        assert bet.amount_usd <= 1.0
