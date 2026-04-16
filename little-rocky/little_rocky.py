from __future__ import annotations

"""
Little Rocky — Polymarket Weather Trading Bot
──────────────────────────────────────────────
Usage:
    python little_rocky.py            # dry-run, loops every 5 min
    python little_rocky.py --once     # dry-run, single cycle
    python little_rocky.py --live     # LIVE trading, loops every 5 min
    python little_rocky.py --live --once  # LIVE, single cycle
"""

import argparse
import logging
import os
import sys
import time
from datetime import datetime, timezone

from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

from config import (
    EDGE_THRESHOLD,
    MAX_TOTAL_EXPOSURE,
    MIN_BET_USD,
    SCAN_INTERVAL_SECONDS,
    SLIPPAGE_TOLERANCE,
    GTC_SLIPPAGE,
    LOG_FILE,
)
from edge_calculator import EdgeResult, find_best_edges
from kelly_sizing import compute_kelly_bet
from polymarket_client import fetch_temperature_markets
from risk_manager import RiskManager, TradeRecord
from telegram_alerts import (
    alert_circuit_breaker,
    alert_daily_summary,
    alert_trade_executed,
)
from weather_fetcher import fetch_all_forecasts

load_dotenv()
console = Console()
logger = logging.getLogger(__name__)


# ── CLOB client helpers ───────────────────────────────────────────────────────

def _build_clob_client():
    """Initialise and authenticate a py-clob-client ClobClient."""
    try:
        from py_clob_client.client import ClobClient
        from py_clob_client.constants import POLYGON

        pk = os.getenv("POLYMARKET_PRIVATE_KEY", "").strip()
        if not pk:
            raise ValueError("POLYMARKET_PRIVATE_KEY is not set in .env")

        client = ClobClient(
            host="https://clob.polymarket.com",
            key=pk,
            chain_id=POLYGON,
        )
        client.set_api_creds(client.create_or_derive_api_creds())
        logger.info("CLOB client initialised")
        return client

    except Exception as exc:
        logger.error("CLOB client init failed: %s", exc)
        return None


def _get_usdc_balance(client) -> float:
    """Return available USDC balance (human-readable, not micro-units)."""
    try:
        raw = client.get_balance()
        # py-clob-client may return a numeric string or a dict
        if isinstance(raw, dict):
            raw = raw.get("balance", raw.get("availableBalance", 0))
        value = float(raw)
        # If the value looks like it's in micro-USDC (> 1 000 000) normalise it
        if value > 1_000_000:
            value /= 1_000_000
        return value
    except Exception as exc:
        logger.error("get_usdc_balance failed: %s", exc)
        return 0.0


def _get_open_token_ids(client) -> set[str]:
    """Return the set of token_ids with live open orders on the CLOB."""
    try:
        orders = client.get_orders() or []
        return {str(o.get("asset_id", "")) for o in orders if o.get("asset_id")}
    except Exception as exc:
        logger.error("get_orders failed: %s", exc)
        return set()


def _place_order(
    client,
    token_id: str,
    side: str,
    size: float,
    mid_price: float,
    dry_run: bool,
) -> dict:
    """
    Attempt a FOK order; fall back to GTC if FOK is not filled.

    Returns dict: { "order_id": str, "status": "filled"|"pending"|"failed",
                    "fill_price": float }

    In dry-run mode returns a synthetic filled result immediately.
    """
    if dry_run:
        return {"order_id": "DRY_RUN", "status": "filled", "fill_price": mid_price}

    try:
        from py_clob_client.clob_types import OrderArgs, OrderType
        from py_clob_client.order_builder.constants import BUY, SELL

        side_const = BUY if side == "YES" else SELL

        # ── FOK: accept up to SLIPPAGE_TOLERANCE away from mid ───────────────
        if side == "YES":
            fok_price = min(0.99, round(mid_price * (1 + SLIPPAGE_TOLERANCE), 4))
        else:
            fok_price = max(0.01, round(mid_price * (1 - SLIPPAGE_TOLERANCE), 4))

        order_args = OrderArgs(
            price=fok_price,
            size=round(size, 2),
            side=side_const,
            token_id=token_id,
        )

        try:
            signed = client.create_order(order_args)
            resp   = client.post_order(signed, OrderType.FOK)

            if resp and resp.get("status") in ("matched", "filled"):
                oid = resp.get("orderID") or resp.get("id") or ""
                logger.info("FOK filled: order_id=%s", oid)
                return {"order_id": oid, "status": "filled", "fill_price": fok_price}

            logger.info("FOK not filled (status=%s), trying GTC", resp)

        except Exception as fok_exc:
            logger.warning("FOK order exception: %s — falling back to GTC", fok_exc)

        # ── GTC fallback: tighter slippage ────────────────────────────────────
        if side == "YES":
            gtc_price = min(0.99, round(mid_price * (1 + GTC_SLIPPAGE), 4))
        else:
            gtc_price = max(0.01, round(mid_price * (1 - GTC_SLIPPAGE), 4))

        gtc_args = OrderArgs(
            price=gtc_price,
            size=round(size, 2),
            side=side_const,
            token_id=token_id,
        )
        signed_gtc = client.create_order(gtc_args)
        resp_gtc   = client.post_order(signed_gtc, OrderType.GTC)

        if resp_gtc:
            oid = resp_gtc.get("orderID") or resp_gtc.get("id") or ""
            logger.info("GTC order placed: order_id=%s", oid)
            return {"order_id": oid, "status": "pending", "fill_price": gtc_price}

        return {"order_id": "", "status": "failed", "fill_price": mid_price}

    except Exception as exc:
        logger.error("Order placement error: %s", exc)
        return {"order_id": "", "status": "failed", "fill_price": mid_price}


# ── Display helpers ───────────────────────────────────────────────────────────

def _print_opportunities(results: list[EdgeResult]) -> None:
    if not results:
        console.print("[dim]No qualifying edges this cycle.[/dim]")
        return

    tbl = Table(title="Edge Opportunities — Best per Event", show_lines=False)
    tbl.add_column("City",    style="cyan",  no_wrap=True)
    tbl.add_column("Date",    no_wrap=True)
    tbl.add_column("Bracket", no_wrap=True)
    tbl.add_column("Side",    style="bold",  no_wrap=True)
    tbl.add_column("Price",   justify="right")
    tbl.add_column("GFS %",   justify="right")
    tbl.add_column("Edge %",  justify="right", style="green")
    tbl.add_column("Market",  max_width=45)

    for r in sorted(results, key=lambda x: -x.effective_edge):
        tbl.add_row(
            r.city_key,
            str(r.target_date),
            r.market.temp_range.label(),
            r.side,
            f"{r.market_price:.3f}",
            f"{r.gfs_probability * 100:.1f}%",
            f"{r.effective_edge * 100:+.1f}%",
            r.market.question[:45],
        )

    console.print(tbl)


# ── Trading cycle ─────────────────────────────────────────────────────────────

def run_cycle(
    risk_manager: RiskManager,
    dry_run: bool,
    clob_client,
) -> int:
    """
    Execute one full scan-and-trade cycle.
    Returns the number of orders placed (0 in most cycles).
    """
    now = datetime.now(timezone.utc)
    console.rule(f"[bold]Cycle[/bold]  {now.strftime('%Y-%m-%d %H:%M:%S UTC')}")

    # ── 1. Bankroll ───────────────────────────────────────────────────────────
    if dry_run:
        bankroll = 100.0
    else:
        bankroll = _get_usdc_balance(clob_client)
        if bankroll < MIN_BET_USD:
            logger.warning("Insufficient USDC balance ($%.2f) — skipping cycle", bankroll)
            return 0

    console.print(
        f"Bankroll: [bold green]${bankroll:.2f}[/bold green]  "
        f"({'dry-run' if dry_run else 'LIVE'})"
    )

    # ── 2. Circuit-breaker ────────────────────────────────────────────────────
    tripped, reason = risk_manager.check_circuit_breaker(bankroll)
    if tripped:
        console.print(f"[bold red]CIRCUIT BREAKER:[/bold red] {reason}")
        logger.warning("Circuit breaker: %s", reason)
        if not dry_run:
            alert_circuit_breaker(reason)
        return 0

    # ── 3. Exposure check ─────────────────────────────────────────────────────
    total_exposure = risk_manager.get_total_exposure()
    if total_exposure >= MAX_TOTAL_EXPOSURE:
        console.print(
            f"[yellow]Max exposure reached (${total_exposure:.2f}) — skipping cycle[/yellow]"
        )
        return 0

    # ── 4. Weather forecasts ──────────────────────────────────────────────────
    console.print("[cyan]Fetching GFS forecasts…[/cyan]")
    forecasts = fetch_all_forecasts()
    if not forecasts:
        logger.error("No forecasts available — aborting cycle")
        return 0

    # ── 5. Polymarket scan ────────────────────────────────────────────────────
    console.print("[cyan]Scanning Polymarket (30 pages)…[/cyan]")
    markets = fetch_temperature_markets()
    if not markets:
        console.print("[dim]No temperature markets found.[/dim]")
        return 0

    console.print(f"[dim]{len(markets)} temperature markets found.[/dim]")

    # ── 6. Edge calculation (ONE best per city+date event) ────────────────────
    best_edges = find_best_edges(markets, forecasts, EDGE_THRESHOLD)
    _print_opportunities(best_edges)

    if not best_edges:
        return 0

    # ── 7. Pre-fetch open orders to avoid duplicates ──────────────────────────
    open_token_ids: set[str] = set()
    if not dry_run and clob_client:
        open_token_ids = _get_open_token_ids(clob_client)

    # ── 8. Execute trades ─────────────────────────────────────────────────────
    trades_placed = 0

    for result in best_edges:
        market = result.market

        # Skip if we already hold a position for this event
        if not dry_run and risk_manager.has_open_position(
            result.city_key, result.target_date
        ):
            logger.info(
                "Skipping %s %s — position already open",
                result.city_key, result.target_date,
            )
            continue

        # Refresh exposure (may have changed within the loop)
        total_exposure = risk_manager.get_total_exposure()
        if total_exposure >= MAX_TOTAL_EXPOSURE:
            logger.info("Max total exposure reached — stopping execution")
            break

        market_exposure = risk_manager.get_market_exposure(market.market_id)

        # Determine which token we're buying
        if result.side == "YES":
            token_id   = market.token_id_yes
            mid_price  = market.yes_price
        else:
            token_id   = market.token_id_no
            mid_price  = market.no_price

        # Skip if there's already an open order for this token
        if token_id in open_token_ids:
            logger.info("Open order exists for token %s — skipping", token_id[:16])
            continue

        # Kelly sizing
        bet = compute_kelly_bet(
            edge=result.edge,
            market_price=mid_price,
            bankroll=bankroll,
            market_exposure_usd=market_exposure,
        )

        if bet.amount_usd < MIN_BET_USD:
            logger.info(
                "Bet size $%.2f below minimum — skipping %s %s",
                bet.amount_usd, result.city_key, result.target_date,
            )
            continue

        logger.info(
            "Placing %s $%.2f on [%s] %s %s  mid=%.3f  edge=+%.1f%%",
            result.side, bet.amount_usd,
            result.market.temp_range.label(),
            result.city_key, result.target_date,
            mid_price, result.effective_edge * 100,
        )

        # Place the order
        order = _place_order(
            clob_client, token_id, result.side,
            bet.amount_usd, mid_price, dry_run,
        )

        if order["status"] == "failed":
            logger.warning(
                "Order failed for %s %s — not recording",
                result.city_key, result.target_date,
            )
            continue

        # ── Record in SQLite ──────────────────────────────────────────────────
        record = TradeRecord(
            id=None,
            timestamp=now.isoformat(),
            city_key=result.city_key,
            target_date=result.target_date.isoformat(),
            market_id=market.market_id,
            question=market.question,
            side=result.side,
            amount_usd=bet.amount_usd,
            price=order["fill_price"],
            gfs_probability=result.gfs_probability,
            edge=result.edge,
            order_id=order["order_id"],
            status=order["status"],
            outcome=None,
            pnl=None,
            dry_run=dry_run,
        )
        risk_manager.record_trade(record)

        # ── Telegram alert (live only) ────────────────────────────────────────
        alert_trade_executed(
            city_key=result.city_key,
            target_date=result.target_date.isoformat(),
            side=result.side,
            temp_label=market.temp_range.label(),
            market_question=market.question,
            amount_usd=bet.amount_usd,
            price=order["fill_price"],
            gfs_probability=result.gfs_probability,
            edge=result.edge,
            order_id=order["order_id"],
            order_status=order["status"],
            dry_run=dry_run,
        )

        console.print(
            f"[green]✓ {'DRY' if dry_run else 'LIVE'}[/green] "
            f"{result.side} ${bet.amount_usd:.2f}  "
            f"[{market.temp_range.label()}]  "
            f"{result.city_key} {result.target_date}  "
            f"@ {order['fill_price']:.3f}  "
            f"edge {result.effective_edge * 100:+.1f}%"
        )

        trades_placed += 1

    logger.info("Cycle complete — %d order(s) placed", trades_placed)
    return trades_placed


# ── Entry point ───────────────────────────────────────────────────────────────

def _setup_logging(level_name: str) -> None:
    level = getattr(logging, level_name.upper(), logging.INFO)
    fmt   = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    logging.basicConfig(
        level=level,
        format=fmt,
        handlers=[
            logging.FileHandler(LOG_FILE, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Little Rocky — Polymarket Weather Trading Bot"
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Enable live order execution (default: dry-run)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single cycle and exit",
    )
    parser.add_argument(
        "--settings",
        action="store_true",
        help="Open the interactive settings menu",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity (default: INFO)",
    )
    args = parser.parse_args()

    if args.settings:
        from settings_menu import run_settings_menu
        run_settings_menu()
        return

    _setup_logging(args.log_level)
    load_dotenv()

    dry_run = not args.live

    console.print(
        f"\n[bold white]Little Rocky[/bold white] "
        f"— Polymarket Weather Trading Bot\n"
        f"Mode     : [{'bold red]LIVE' if not dry_run else 'bold yellow]DRY-RUN'}[/]\n"
        f"Threshold: {EDGE_THRESHOLD * 100:.0f}% edge  |  "
        f"Max exposure: ${MAX_TOTAL_EXPOSURE:.0f}  |  "
        f"Interval: {SCAN_INTERVAL_SECONDS}s\n"
    )

    risk_manager = RiskManager()

    # ── Build CLOB client for live mode ───────────────────────────────────────
    clob_client = None
    if not dry_run:
        clob_client = _build_clob_client()
        if clob_client is None:
            console.print("[bold red]Cannot initialise CLOB client — aborting.[/bold red]")
            sys.exit(1)

        balance = _get_usdc_balance(clob_client)
        console.print(f"USDC balance: [bold green]${balance:.2f}[/bold green]\n")

        if balance < MIN_BET_USD:
            console.print("[red]Insufficient balance to trade.[/red]")
            sys.exit(1)

    # ── Single-cycle mode ─────────────────────────────────────────────────────
    if args.once:
        run_cycle(risk_manager, dry_run, clob_client)
        return

    # ── Main loop ─────────────────────────────────────────────────────────────
    last_summary_date: str | None = None

    while True:
        try:
            run_cycle(risk_manager, dry_run, clob_client)

            # Once-per-day summary (live mode, if any trades occurred today)
            today_str = datetime.now(timezone.utc).date().isoformat()
            if not dry_run and last_summary_date != today_str:
                summary = risk_manager.get_daily_summary()
                if summary["total_trades"] > 0:
                    exposure = risk_manager.get_total_exposure()
                    bankroll = _get_usdc_balance(clob_client) if clob_client else 0.0
                    alert_daily_summary(
                        summary=summary,
                        bankroll=bankroll,
                        total_exposure=exposure,
                    )
                last_summary_date = today_str

        except KeyboardInterrupt:
            console.print("\n[yellow]Stopped by user.[/yellow]")
            break
        except Exception as exc:
            logger.exception("Unhandled exception in main loop: %s", exc)

        logger.info("Sleeping %d seconds…", SCAN_INTERVAL_SECONDS)
        time.sleep(SCAN_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
