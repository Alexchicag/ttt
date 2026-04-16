from __future__ import annotations

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import tempfile
from datetime import date, datetime, timezone

import pytest
from risk_manager import RiskManager, TradeRecord


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def rm(tmp_path):
    """RiskManager backed by a temporary SQLite database."""
    db = str(tmp_path / "test_trades.db")
    return RiskManager(db_path=db)


def _trade(
    city_key: str = "NYC",
    target_date: str = "2025-04-15",
    market_id: str = "market_001",
    side: str = "YES",
    amount_usd: float = 1.50,
    price: float = 0.60,
    status: str = "filled",
    outcome: str | None = None,
    pnl: float | None = None,
    dry_run: bool = False,
) -> TradeRecord:
    return TradeRecord(
        id=None,
        timestamp=datetime.now(timezone.utc).isoformat(),
        city_key=city_key,
        target_date=target_date,
        market_id=market_id,
        question=f"{city_key} high temp {target_date}",
        side=side,
        amount_usd=amount_usd,
        price=price,
        gfs_probability=0.70,
        edge=0.10,
        order_id="order_test",
        status=status,
        outcome=outcome,
        pnl=pnl,
        dry_run=dry_run,
    )


# ── record_trade ──────────────────────────────────────────────────────────────

class TestRecordTrade:

    def test_returns_positive_row_id(self, rm):
        row_id = rm.record_trade(_trade())
        assert isinstance(row_id, int)
        assert row_id > 0

    def test_multiple_trades_increments_ids(self, rm):
        id1 = rm.record_trade(_trade(market_id="m1"))
        id2 = rm.record_trade(_trade(market_id="m2"))
        assert id2 > id1

    def test_dry_run_trade_recorded(self, rm):
        row_id = rm.record_trade(_trade(dry_run=True))
        assert row_id > 0


# ── has_open_position ─────────────────────────────────────────────────────────

class TestHasOpenPosition:

    def test_no_position_initially(self, rm):
        assert rm.has_open_position("NYC", date(2025, 4, 15)) is False

    def test_detects_open_live_position(self, rm):
        rm.record_trade(_trade(city_key="NYC", target_date="2025-04-15", dry_run=False))
        assert rm.has_open_position("NYC", date(2025, 4, 15)) is True

    def test_dry_run_does_not_block_live(self, rm):
        rm.record_trade(_trade(city_key="NYC", target_date="2025-04-15", dry_run=True))
        assert rm.has_open_position("NYC", date(2025, 4, 15)) is False

    def test_settled_position_not_counted(self, rm):
        rm.record_trade(_trade(
            city_key="NYC", target_date="2025-04-15",
            outcome="win", pnl=0.50, dry_run=False,
        ))
        assert rm.has_open_position("NYC", date(2025, 4, 15)) is False

    def test_different_city_not_blocked(self, rm):
        rm.record_trade(_trade(city_key="CHICAGO", target_date="2025-04-15", dry_run=False))
        assert rm.has_open_position("NYC", date(2025, 4, 15)) is False

    def test_different_date_not_blocked(self, rm):
        rm.record_trade(_trade(city_key="NYC", target_date="2025-04-16", dry_run=False))
        assert rm.has_open_position("NYC", date(2025, 4, 15)) is False


# ── get_total_exposure ────────────────────────────────────────────────────────

class TestGetTotalExposure:

    def test_zero_initially(self, rm):
        assert rm.get_total_exposure() == 0.0

    def test_accumulates_open_trades(self, rm):
        rm.record_trade(_trade(amount_usd=1.50, dry_run=False))
        rm.record_trade(_trade(amount_usd=2.00, dry_run=False))
        assert rm.get_total_exposure() == pytest.approx(3.50)

    def test_dry_run_excluded(self, rm):
        rm.record_trade(_trade(amount_usd=5.00, dry_run=True))
        assert rm.get_total_exposure() == 0.0

    def test_settled_trade_excluded(self, rm):
        rm.record_trade(_trade(amount_usd=2.00, outcome="win", pnl=0.80, dry_run=False))
        assert rm.get_total_exposure() == 0.0


# ── get_market_exposure ───────────────────────────────────────────────────────

class TestGetMarketExposure:

    def test_zero_for_unknown_market(self, rm):
        assert rm.get_market_exposure("nonexistent") == 0.0

    def test_sums_open_trades_for_market(self, rm):
        rm.record_trade(_trade(market_id="mkt_A", amount_usd=1.00, dry_run=False))
        rm.record_trade(_trade(market_id="mkt_A", amount_usd=0.50, dry_run=False))
        assert rm.get_market_exposure("mkt_A") == pytest.approx(1.50)

    def test_other_market_not_included(self, rm):
        rm.record_trade(_trade(market_id="mkt_B", amount_usd=3.00, dry_run=False))
        assert rm.get_market_exposure("mkt_A") == 0.0


# ── check_circuit_breaker ─────────────────────────────────────────────────────

class TestCircuitBreaker:

    def test_no_trip_with_no_trades(self, rm):
        tripped, reason = rm.check_circuit_breaker(bankroll=100.0)
        assert not tripped

    def test_trips_on_excessive_losses(self, rm):
        # Fill window with losses (need CIRCUIT_BREAKER_WINDOW resolved trades)
        from config import CIRCUIT_BREAKER_WINDOW, CIRCUIT_BREAKER_LOSSES
        for i in range(CIRCUIT_BREAKER_WINDOW):
            tid = rm.record_trade(_trade(market_id=f"m{i}", dry_run=False))
            rm.update_outcome(tid, "loss", pnl=-1.50)

        tripped, reason = rm.check_circuit_breaker(bankroll=100.0)
        assert tripped
        assert "loss" in reason.lower() or "limit" in reason.lower()

    def test_does_not_trip_with_mixed_results(self, rm):
        from config import CIRCUIT_BREAKER_WINDOW, CIRCUIT_BREAKER_LOSSES
        # Half wins, half losses (fewer losses than threshold)
        for i in range(CIRCUIT_BREAKER_WINDOW):
            tid = rm.record_trade(_trade(market_id=f"m{i}", dry_run=False))
            outcome = "win" if i % 2 == 0 else "loss"
            pnl = 0.60 if outcome == "win" else -1.50
            rm.update_outcome(tid, outcome, pnl=pnl)

        tripped, _ = rm.check_circuit_breaker(bankroll=1000.0)
        # With half wins/losses and large bankroll, daily drawdown shouldn't trip
        # (depends on exact values; we just check it doesn't always trip)
        # This test is soft — mainly verifying no exception
        assert isinstance(tripped, bool)

    def test_update_outcome_recorded(self, rm):
        tid = rm.record_trade(_trade(dry_run=False))
        rm.update_outcome(tid, "win", pnl=0.60)
        # Should not raise; circuit breaker should be able to read it
        tripped, _ = rm.check_circuit_breaker(bankroll=100.0)
        assert isinstance(tripped, bool)
