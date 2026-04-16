from __future__ import annotations

import logging
import sqlite3
from collections import deque
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Optional

from config import (
    CIRCUIT_BREAKER_LOSSES,
    CIRCUIT_BREAKER_WINDOW,
    DAILY_LOSS_LIMIT,
    DB_PATH,
    MAX_TOTAL_EXPOSURE,
)

logger = logging.getLogger(__name__)


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class TradeRecord:
    id: Optional[int]
    timestamp: str          # ISO-8601 UTC
    city_key: str
    target_date: str        # ISO date string "YYYY-MM-DD"
    market_id: str
    question: str
    side: str               # "YES" or "NO"
    amount_usd: float
    price: float            # Execution price (implied probability)
    gfs_probability: float
    edge: float
    order_id: str
    status: str             # "pending" | "filled" | "cancelled" | "failed"
    outcome: Optional[str]  # "win" | "loss" | None (open)
    pnl: Optional[float]    # Realised PnL in USD once settled
    dry_run: bool


# ── Schema ────────────────────────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS trades (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       TEXT    NOT NULL,
    city_key        TEXT    NOT NULL,
    target_date     TEXT    NOT NULL,
    market_id       TEXT    NOT NULL,
    question        TEXT    NOT NULL DEFAULT '',
    side            TEXT    NOT NULL,
    amount_usd      REAL    NOT NULL,
    price           REAL    NOT NULL,
    gfs_probability REAL    NOT NULL,
    edge            REAL    NOT NULL,
    order_id        TEXT    NOT NULL DEFAULT '',
    status          TEXT    NOT NULL,
    outcome         TEXT,
    pnl             REAL,
    dry_run         INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_trades_timestamp  ON trades(timestamp);
CREATE INDEX IF NOT EXISTS idx_trades_market_id  ON trades(market_id);
CREATE INDEX IF NOT EXISTS idx_trades_event      ON trades(city_key, target_date);
"""


# ── Manager ───────────────────────────────────────────────────────────────────

class RiskManager:
    def __init__(self, db_path: str = DB_PATH) -> None:
        self.db_path = db_path
        # deque acts as a sliding window of boolean wins (True) / losses (False)
        self._recent: deque[bool] = deque(maxlen=CIRCUIT_BREAKER_WINDOW)
        self._init_db()
        self._hydrate_recent()

    # ── Initialisation ────────────────────────────────────────────────────────

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            for stmt in _SCHEMA.strip().split(";"):
                stmt = stmt.strip()
                if stmt:
                    conn.execute(stmt)
            conn.commit()

    def _hydrate_recent(self) -> None:
        """Load the tail of the outcome history to warm up the circuit-breaker."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT outcome FROM trades
                WHERE outcome IS NOT NULL AND dry_run = 0
                ORDER BY id DESC
                LIMIT ?
                """,
                (CIRCUIT_BREAKER_WINDOW,),
            ).fetchall()
        for (outcome,) in reversed(rows):
            self._recent.append(outcome == "win")

    # ── Write operations ──────────────────────────────────────────────────────

    def record_trade(self, trade: TradeRecord) -> int:
        """Insert a new trade row; returns the auto-assigned row ID."""
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                """
                INSERT INTO trades (
                    timestamp, city_key, target_date, market_id, question,
                    side, amount_usd, price, gfs_probability, edge,
                    order_id, status, outcome, pnl, dry_run
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    trade.timestamp,
                    trade.city_key,
                    trade.target_date,
                    trade.market_id,
                    trade.question,
                    trade.side,
                    trade.amount_usd,
                    trade.price,
                    trade.gfs_probability,
                    trade.edge,
                    trade.order_id,
                    trade.status,
                    trade.outcome,
                    trade.pnl,
                    int(trade.dry_run),
                ),
            )
            conn.commit()
            return cur.lastrowid  # type: ignore[return-value]

    def update_outcome(self, trade_id: int, outcome: str, pnl: float) -> None:
        """Record the resolved outcome and PnL for an existing trade."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE trades SET outcome=?, pnl=?, status='filled' WHERE id=?",
                (outcome, pnl, trade_id),
            )
            conn.commit()
        self._recent.append(outcome == "win")

    # ── Read / query operations ───────────────────────────────────────────────

    def has_open_position(self, city_key: str, target_date: date) -> bool:
        """
        Return True if there is already a live (non-dry-run) trade for this
        city + date event.  Dry-run trades do NOT block real trades.
        """
        with sqlite3.connect(self.db_path) as conn:
            (count,) = conn.execute(
                """
                SELECT COUNT(*) FROM trades
                WHERE city_key   = ?
                  AND target_date = ?
                  AND status      IN ('pending', 'filled')
                  AND outcome     IS NULL
                  AND dry_run     = 0
                """,
                (city_key, target_date.isoformat()),
            ).fetchone()
        return count > 0

    def get_total_exposure(self) -> float:
        """Sum of all open (unsettled, non-dry-run) trade amounts."""
        with sqlite3.connect(self.db_path) as conn:
            (total,) = conn.execute(
                """
                SELECT COALESCE(SUM(amount_usd), 0.0) FROM trades
                WHERE status  IN ('pending', 'filled')
                  AND outcome IS NULL
                  AND dry_run = 0
                """,
            ).fetchone()
        return float(total)

    def get_market_exposure(self, market_id: str) -> float:
        """Open exposure for a specific market (non-dry-run)."""
        with sqlite3.connect(self.db_path) as conn:
            (total,) = conn.execute(
                """
                SELECT COALESCE(SUM(amount_usd), 0.0) FROM trades
                WHERE market_id = ?
                  AND status    IN ('pending', 'filled')
                  AND outcome   IS NULL
                  AND dry_run   = 0
                """,
                (market_id,),
            ).fetchone()
        return float(total)

    def get_daily_pnl(self) -> float:
        """Realised PnL for today (UTC) on live trades."""
        today = datetime.now(timezone.utc).date().isoformat()
        with sqlite3.connect(self.db_path) as conn:
            (total,) = conn.execute(
                """
                SELECT COALESCE(SUM(pnl), 0.0) FROM trades
                WHERE DATE(timestamp) = ?
                  AND pnl     IS NOT NULL
                  AND dry_run = 0
                """,
                (today,),
            ).fetchone()
        return float(total)

    def get_daily_summary(self) -> dict:
        """Aggregate stats for today's live trades."""
        today = datetime.now(timezone.utc).date().isoformat()
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT
                    COUNT(*)                                          AS total,
                    SUM(CASE WHEN outcome='win'  THEN 1 ELSE 0 END)  AS wins,
                    SUM(CASE WHEN outcome='loss' THEN 1 ELSE 0 END)  AS losses,
                    COALESCE(SUM(amount_usd), 0.0)                   AS wagered,
                    COALESCE(SUM(pnl), 0.0)                          AS pnl
                FROM trades
                WHERE DATE(timestamp) = ?
                  AND dry_run = 0
                """,
                (today,),
            ).fetchone()
        return {
            "total_trades":  row[0] or 0,
            "wins":          row[1] or 0,
            "losses":        row[2] or 0,
            "total_wagered": row[3] or 0.0,
            "total_pnl":     row[4] or 0.0,
        }

    # ── Circuit-breaker ───────────────────────────────────────────────────────

    def check_circuit_breaker(self, bankroll: float) -> tuple[bool, str]:
        """
        Returns (tripped: bool, reason: str).
        Three independent conditions can trip it:
          1. ≥ CIRCUIT_BREAKER_LOSSES losses in the last CIRCUIT_BREAKER_WINDOW trades.
          2. Daily realised PnL loss exceeds DAILY_LOSS_LIMIT × bankroll.
          3. Total open exposure has reached MAX_TOTAL_EXPOSURE.
        """
        # 1. Rolling loss rate
        if len(self._recent) == CIRCUIT_BREAKER_WINDOW:
            n_losses = sum(1 for win in self._recent if not win)
            if n_losses >= CIRCUIT_BREAKER_LOSSES:
                return (
                    True,
                    f"{n_losses}/{CIRCUIT_BREAKER_WINDOW} recent trades lost "
                    f"(limit {CIRCUIT_BREAKER_LOSSES})",
                )

        # 2. Daily drawdown
        if bankroll > 0:
            daily_loss = -self.get_daily_pnl()   # positive = we lost money
            if daily_loss / bankroll >= DAILY_LOSS_LIMIT:
                return (
                    True,
                    f"Daily loss ${daily_loss:.2f} = "
                    f"{daily_loss / bankroll * 100:.1f}% of bankroll "
                    f"(limit {DAILY_LOSS_LIMIT * 100:.0f}%)",
                )

        # 3. Total exposure cap
        exposure = self.get_total_exposure()
        if exposure >= MAX_TOTAL_EXPOSURE:
            return True, f"Total exposure ${exposure:.2f} ≥ ${MAX_TOTAL_EXPOSURE:.0f} cap"

        return False, ""
