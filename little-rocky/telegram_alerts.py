from __future__ import annotations

"""
Telegram alert module — strict minimal-noise policy:

  • alert_trade_executed  → fires ONLY when a real order is confirmed filled/pending.
                            Never fires in dry-run mode.
  • alert_daily_summary   → fires once per calendar day, from the main loop.
  • alert_circuit_breaker → fires when the circuit breaker trips (live mode only).

Everything else (skipped markets, slippage, low-edge scans, dry-run activity)
is intentionally silent.  The user asked: "No spam.  Only real money."
"""

import logging
import os
from typing import Optional

import requests

from config import MAX_TOTAL_EXPOSURE

logger = logging.getLogger(__name__)

_TOKEN: Optional[str] = None
_CHAT:  Optional[str] = None


def _credentials() -> tuple[str, str] | None:
    """Return (bot_token, chat_id) from env, or None if not configured."""
    global _TOKEN, _CHAT
    if _TOKEN and _CHAT:
        return _TOKEN, _CHAT
    _TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    _CHAT  = os.getenv("TELEGRAM_CHAT_ID",  "").strip()
    if _TOKEN and _CHAT:
        return _TOKEN, _CHAT
    return None


def _send(text: str) -> None:
    """Best-effort delivery — logs errors but never raises."""
    creds = _credentials()
    if creds is None:
        logger.debug("Telegram not configured; skipping message")
        return
    token, chat_id = creds
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=10,
        )
        resp.raise_for_status()
    except Exception as exc:
        logger.error("Telegram delivery failed: %s", exc)


# ── Public alert functions ────────────────────────────────────────────────────

def alert_trade_executed(
    *,
    city_key: str,
    target_date: str,
    side: str,
    temp_label: str,
    market_question: str,
    amount_usd: float,
    price: float,
    gfs_probability: float,
    edge: float,
    order_id: str,
    order_status: str,
    dry_run: bool,
) -> None:
    """
    Send a trade notification.
    Silenced entirely in dry-run mode — no exceptions.
    """
    if dry_run:
        return

    status_tag = "✅ Filled" if order_status == "filled" else "⏳ Pending (GTC)"
    text = (
        f"<b>🎯 Trade Executed</b>  {status_tag}\n"
        f"City   : {city_key}\n"
        f"Date   : {target_date}\n"
        f"Bracket: {temp_label}\n"
        f"Side   : <b>{side}</b>\n"
        f"Amount : <b>${amount_usd:.2f}</b>\n"
        f"Price  : {price * 100:.1f}¢  "
        f"GFS: {gfs_probability * 100:.1f}%  "
        f"Edge: {edge * 100:+.1f}%\n"
        f"Order  : <code>{order_id}</code>\n"
        f"Market : {market_question[:80]}"
    )
    _send(text)


def alert_daily_summary(
    *,
    summary: dict,
    bankroll: float,
    total_exposure: float,
) -> None:
    """
    End-of-day summary for live mode.
    Called once per calendar day from the main loop only when trades occurred.
    """
    pnl = summary.get("total_pnl", 0.0)
    sign = "+" if pnl >= 0 else ""
    wins   = summary.get("wins", 0)
    losses = summary.get("losses", 0)
    total  = summary.get("total_trades", 0)
    wagered = summary.get("total_wagered", 0.0)

    win_rate = f"{wins / total * 100:.0f}%" if total > 0 else "—"

    text = (
        f"<b>📊 Daily Summary</b>\n"
        f"Trades  : {total}  (W {wins} / L {losses}  {win_rate})\n"
        f"Wagered : ${wagered:.2f}\n"
        f"PnL     : {sign}${pnl:.2f}\n"
        f"Bankroll: ${bankroll:.2f}\n"
        f"Exposure: ${total_exposure:.2f} / ${MAX_TOTAL_EXPOSURE:.0f}"
    )
    _send(text)


def alert_circuit_breaker(reason: str) -> None:
    """Alert when the circuit breaker trips — always sent in live mode."""
    _send(f"<b>🚨 Circuit Breaker Tripped</b>\n{reason}")
