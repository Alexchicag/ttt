from __future__ import annotations

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import date
import pytest
from edge_calculator import _gaussian_prob, _edge_for_market, find_best_edges
from polymarket_client import PolymarketMarket, TempRange
from weather_fetcher import WeatherForecast


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_market(
    city_key: str,
    target_date: date,
    low: float,
    high: float,
    yes_price: float = 0.50,
    is_above: bool = False,
    is_below: bool = False,
) -> PolymarketMarket:
    no_price = round(1.0 - yes_price, 4)
    tr = TempRange(
        low=low if not is_below else None,
        high=high if not is_above else None,
        is_above=is_above,
        is_below=is_below,
    )
    return PolymarketMarket(
        market_id=f"{city_key}_{target_date}_{low}_{high}",
        condition_id="cond_test",
        question=f"{city_key} high {low}-{high}°F on {target_date}",
        city_key=city_key,
        target_date=target_date,
        temp_range=tr,
        yes_price=yes_price,
        no_price=no_price,
        token_id_yes="tok_yes",
        token_id_no="tok_no",
        end_date_iso="2025-04-15T00:00:00Z",
    )


def _make_forecast(city_key: str, target_date: date, mean_f: float, std_f: float = 2.0) -> WeatherForecast:
    return WeatherForecast(
        city_key=city_key,
        date=target_date,
        temp_mean_f=mean_f,
        temp_std_f=std_f,
        source="ensemble",
        member_count=31,
    )


# ── _gaussian_prob ────────────────────────────────────────────────────────────

class TestGaussianProb:

    def test_range_centered_high_probability(self):
        tr = TempRange(low=68.0, high=72.0)
        p = _gaussian_prob(tr, mean_f=70.0, sigma_f=3.0)
        assert p > 0.3  # centered on bracket → reasonably likely

    def test_range_far_from_mean_low_probability(self):
        tr = TempRange(low=90.0, high=100.0)
        p = _gaussian_prob(tr, mean_f=60.0, sigma_f=3.0)
        assert p < 0.01

    def test_above_threshold_above_mean(self):
        tr = TempRange(low=65.0, high=None, is_above=True)
        p = _gaussian_prob(tr, mean_f=70.0, sigma_f=3.0)
        assert p > 0.85  # mean is above threshold → high probability

    def test_above_threshold_below_mean(self):
        tr = TempRange(low=80.0, high=None, is_above=True)
        p = _gaussian_prob(tr, mean_f=60.0, sigma_f=3.0)
        assert p < 0.01

    def test_below_threshold_below_mean(self):
        tr = TempRange(low=None, high=50.0, is_below=True)
        p = _gaussian_prob(tr, mean_f=45.0, sigma_f=3.0)
        assert p > 0.7

    def test_below_threshold_above_mean(self):
        tr = TempRange(low=None, high=40.0, is_below=True)
        p = _gaussian_prob(tr, mean_f=70.0, sigma_f=3.0)
        assert p < 0.01

    def test_zero_sigma_guarded(self):
        tr = TempRange(low=69.0, high=71.0)
        p = _gaussian_prob(tr, mean_f=70.0, sigma_f=0.0)
        assert 0 < p <= 1.0

    def test_probability_clamped_between_0_and_1(self):
        tr = TempRange(low=69.0, high=71.0)
        p = _gaussian_prob(tr, mean_f=70.0, sigma_f=3.0)
        assert 1e-6 <= p <= 1.0 - 1e-6

    def test_symmetry_above_below(self):
        mean = 70.0
        threshold = 70.0
        sigma = 5.0
        p_above = _gaussian_prob(TempRange(low=threshold, high=None, is_above=True), mean, sigma)
        p_below = _gaussian_prob(TempRange(low=None, high=threshold, is_below=True), mean, sigma)
        assert abs(p_above + p_below - 1.0) < 0.02  # should sum to ~1


# ── _edge_for_market ──────────────────────────────────────────────────────────

class TestEdgeForMarket:

    def test_positive_edge_detected(self):
        market = _make_market("NYC", date(2025, 4, 15), 68.0, 72.0, yes_price=0.20)
        forecast = _make_forecast("NYC", date(2025, 4, 15), mean_f=70.0, std_f=2.0)
        result = _edge_for_market(market, forecast)
        assert result is not None
        # GFS says ~high prob for 68-72 range; market price is only 0.20 → positive YES edge
        assert result.edge > 0

    def test_negative_edge_detected(self):
        market = _make_market("NYC", date(2025, 4, 15), 68.0, 72.0, yes_price=0.90)
        forecast = _make_forecast("NYC", date(2025, 4, 15), mean_f=70.0, std_f=2.0)
        result = _edge_for_market(market, forecast)
        assert result is not None
        # Market overprices YES → NO side has edge
        assert result.side == "NO"

    def test_unknown_city_returns_none(self):
        market = _make_market("UNKNOWN", date(2025, 4, 15), 68.0, 72.0)
        forecast = _make_forecast("UNKNOWN", date(2025, 4, 15), mean_f=70.0)
        result = _edge_for_market(market, forecast)
        assert result is None

    def test_result_fields_populated(self):
        market = _make_market("MIAMI", date(2025, 6, 1), 85.0, 90.0, yes_price=0.40)
        forecast = _make_forecast("MIAMI", date(2025, 6, 1), mean_f=87.0, std_f=2.0)
        result = _edge_for_market(market, forecast)
        assert result is not None
        assert result.city_key == "MIAMI"
        assert result.target_date == date(2025, 6, 1)
        assert result.side in ("YES", "NO")
        assert 0 < result.gfs_probability < 1


# ── find_best_edges ───────────────────────────────────────────────────────────

class TestFindBestEdges:

    def _forecasts(self, city: str, d: date, mean: float):
        return {city: {d: _make_forecast(city, d, mean, std_f=2.0)}}

    def test_returns_one_winner_per_event(self):
        d = date(2025, 4, 20)
        # Create several brackets for NYC on same date
        markets = [
            _make_market("NYC", d, 60.0, 65.0, yes_price=0.05),
            _make_market("NYC", d, 65.0, 70.0, yes_price=0.20),  # should win (underpriced near mean)
            _make_market("NYC", d, 70.0, 75.0, yes_price=0.60),
            _make_market("NYC", d, 75.0, 80.0, yes_price=0.05),
        ]
        forecasts = self._forecasts("NYC", d, mean=67.0)
        results = find_best_edges(markets, forecasts, edge_threshold=0.0)
        assert len(results) <= 1  # at most one per event

    def test_below_threshold_returns_empty(self):
        d = date(2025, 4, 20)
        market = _make_market("NYC", d, 68.0, 72.0, yes_price=0.50)
        # GFS mean ~70 → p_yes ≈ 0.5, edge ≈ 0 → below any reasonable threshold
        forecasts = self._forecasts("NYC", d, mean=70.0)
        results = find_best_edges([market], forecasts, edge_threshold=0.30)
        assert results == []

    def test_missing_forecast_skips_market(self):
        d = date(2025, 4, 20)
        market = _make_market("CHICAGO", d, 60.0, 65.0, yes_price=0.10)
        forecasts: dict = {}  # no forecasts at all
        results = find_best_edges([market], forecasts, edge_threshold=0.0)
        assert results == []

    def test_multiple_cities_each_get_winner(self):
        d = date(2025, 5, 1)
        markets = [
            _make_market("NYC",     d, 65.0, 70.0, yes_price=0.20),
            _make_market("CHICAGO", d, 55.0, 60.0, yes_price=0.15),
        ]
        forecasts = {
            "NYC":     {d: _make_forecast("NYC",     d, 67.0)},
            "CHICAGO": {d: _make_forecast("CHICAGO", d, 57.0)},
        }
        results = find_best_edges(markets, forecasts, edge_threshold=0.0)
        cities = {r.city_key for r in results}
        assert "NYC" in cities
        assert "CHICAGO" in cities
        assert len(results) == 2
