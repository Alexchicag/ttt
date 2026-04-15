from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import requests

from config import (
    CITIES,
    GAMMA_API_URL,
    GAMMA_MAX_PAGES,
    GAMMA_PAGE_SIZE,
    MAX_HOURS_TO_RESOLUTION,
)

logger = logging.getLogger(__name__)

# ── City alias table ──────────────────────────────────────────────────────────
# Built once at import time: longest aliases first so regex matches greedily.
_ALIAS_TO_KEY: dict[str, str] = {}
for _key, _city in CITIES.items():
    for _alias in _city.aliases:
        _ALIAS_TO_KEY[_alias.lower()] = _key

_CITY_ALIASES_BY_LENGTH = sorted(_ALIAS_TO_KEY.keys(), key=len, reverse=True)

# ── Month name table ──────────────────────────────────────────────────────────
_MONTHS: dict[str, int] = {
    "january": 1, "jan": 1,
    "february": 2, "feb": 2,
    "march": 3,    "mar": 3,
    "april": 4,    "apr": 4,
    "may": 5,
    "june": 6,     "jun": 6,
    "july": 7,     "jul": 7,
    "august": 8,   "aug": 8,
    "september": 9, "sep": 9, "sept": 9,
    "october": 10, "oct": 10,
    "november": 11, "nov": 11,
    "december": 12, "dec": 12,
}

# ── Temperature range type ────────────────────────────────────────────────────

@dataclass
class TempRange:
    low: Optional[float]   # None for pure "above" brackets
    high: Optional[float]  # None for pure "below" brackets
    is_above: bool = False  # "above X" / "X or higher"
    is_below: bool = False  # "below X" / "X or lower"

    def label(self) -> str:
        if self.is_above and self.low is not None:
            return f">{self.low:.0f}°F"
        if self.is_below and self.high is not None:
            return f"<{self.high:.0f}°F"
        return f"{self.low:.0f}–{self.high:.0f}°F"


# ── Market dataclass ──────────────────────────────────────────────────────────

@dataclass
class PolymarketMarket:
    market_id: str
    condition_id: str
    question: str
    city_key: str
    target_date: date
    temp_range: TempRange
    yes_price: float        # Implied YES probability
    no_price: float
    token_id_yes: str       # CLOB token ID for YES leg
    token_id_no: str        # CLOB token ID for NO leg
    end_date_iso: str
    volume_usd: float = 0.0


# ── Parsing helpers ───────────────────────────────────────────────────────────

def _parse_city(title: str) -> Optional[str]:
    tl = title.lower()
    for alias in _CITY_ALIASES_BY_LENGTH:
        if alias in tl:
            return _ALIAS_TO_KEY[alias]
    return None


def _parse_date(title: str) -> Optional[date]:
    today = datetime.now(timezone.utc).date()
    tl = title.lower()

    # Pattern 1: "April 15", "Apr 15th", "April 15, 2025"
    m = re.search(
        r"\b(january|february|march|april|may|june|july|august|september|"
        r"october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)"
        r"\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s*(\d{4}))?",
        tl,
    )
    if m:
        month = _MONTHS.get(m.group(1))
        day = int(m.group(2))
        year = int(m.group(3)) if m.group(3) else today.year
        if year < 100:
            year += 2000
        try:
            d = date(year, month, day)
            if d < today and not m.group(3):
                d = date(year + 1, month, day)
            return d
        except ValueError:
            pass

    # Pattern 2: "15 April" / "15th April"
    m = re.search(
        r"\b(\d{1,2})(?:st|nd|rd|th)?\s+"
        r"(january|february|march|april|may|june|july|august|september|"
        r"october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)\b",
        tl,
    )
    if m:
        day = int(m.group(1))
        month = _MONTHS.get(m.group(2))
        try:
            d = date(today.year, month, day)
            if d < today:
                d = date(today.year + 1, month, day)
            return d
        except ValueError:
            pass

    # Pattern 3: MM/DD or MM/DD/YYYY
    m = re.search(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b", title)
    if m:
        month, day = int(m.group(1)), int(m.group(2))
        year = int(m.group(3)) if m.group(3) else today.year
        if year < 100:
            year += 2000
        try:
            d = date(year, month, day)
            if d < today and not m.group(3):
                d = date(year + 1, month, day)
            return d
        except ValueError:
            pass

    return None


def _parse_temp_range(title: str) -> Optional[TempRange]:
    tl = title.lower()

    # "between X and Y°F" / "X–Y°F" / "X to Y°F"
    range_pats = [
        r"between\s+(-?\d+(?:\.\d+)?)\s*(?:°?f?)?\s+and\s+(-?\d+(?:\.\d+)?)\s*°?f?",
        r"(-?\d+(?:\.\d+)?)\s*°?f?\s*[-–—]\s*(-?\d+(?:\.\d+)?)\s*°?f?",
        r"(-?\d+(?:\.\d+)?)\s*°?f?\s+(?:to|-)\s+(-?\d+(?:\.\d+)?)\s*°?f?",
        r"(-?\d+(?:\.\d+)?)\s+and\s+(-?\d+(?:\.\d+)?)\s*°?f?",
    ]
    for pat in range_pats:
        m = re.search(pat, tl)
        if m:
            lo, hi = float(m.group(1)), float(m.group(2))
            if lo > hi:
                lo, hi = hi, lo
            return TempRange(low=lo, high=hi)

    # "above X°F" / "over X" / "X or higher" / "at least X"
    above_pats = [
        r"(?:above|over|at\s+least|higher\s+than|greater\s+than)\s+(-?\d+(?:\.\d+)?)\s*°?f?",
        r"(-?\d+(?:\.\d+)?)\s*°?f?\s+or\s+(?:above|higher|more|over)",
    ]
    for pat in above_pats:
        m = re.search(pat, tl)
        if m:
            return TempRange(low=float(m.group(1)), high=None, is_above=True)

    # "below X°F" / "under X" / "X or lower" / "at most X"
    below_pats = [
        r"(?:below|under|at\s+most|lower\s+than|less\s+than)\s+(-?\d+(?:\.\d+)?)\s*°?f?",
        r"(-?\d+(?:\.\d+)?)\s*°?f?\s+or\s+(?:below|lower|less|under)",
    ]
    for pat in below_pats:
        m = re.search(pat, tl)
        if m:
            return TempRange(low=None, high=float(m.group(1)), is_below=True)

    return None


def _parse_tokens(
    market_data: dict,
) -> tuple[float, float, str, str]:
    """Return (yes_price, no_price, yes_token_id, no_token_id)."""
    yes_price = 0.5
    no_price = 0.5
    yes_tid = ""
    no_tid = ""

    for token in market_data.get("tokens", []):
        outcome = token.get("outcome", "").upper()
        price = float(token.get("price", 0.5) or 0.5)
        tid = str(token.get("token_id", "") or "")
        if outcome == "YES":
            yes_price, yes_tid = price, tid
        elif outcome == "NO":
            no_price, no_tid = price, tid

    return yes_price, no_price, yes_tid, no_tid


# ── Public API ────────────────────────────────────────────────────────────────

def fetch_temperature_markets() -> list[PolymarketMarket]:
    """
    Scan up to GAMMA_MAX_PAGES of the Gamma API for active temperature markets.
    Filters to markets resolving within MAX_HOURS_TO_RESOLUTION hours.
    """
    now = datetime.now(timezone.utc)
    cutoff_far = now + timedelta(hours=MAX_HOURS_TO_RESOLUTION)
    markets: list[PolymarketMarket] = []

    for page in range(GAMMA_MAX_PAGES):
        offset = page * GAMMA_PAGE_SIZE
        try:
            resp = requests.get(
                f"{GAMMA_API_URL}/markets",
                params={
                    "limit": GAMMA_PAGE_SIZE,
                    "offset": offset,
                    "active": "true",
                    "closed": "false",
                },
                timeout=30,
            )
            resp.raise_for_status()
            page_data: list[dict] = resp.json()
        except requests.HTTPError as exc:
            logger.error("Gamma API HTTP error on page %d: %s", page, exc)
            break
        except Exception as exc:
            logger.error("Gamma API error on page %d: %s", page, exc)
            break

        if not page_data:
            logger.debug("Gamma API: empty page at offset %d — stopping", offset)
            break

        for raw in page_data:
            question: str = (
                raw.get("question")
                or raw.get("title")
                or raw.get("description")
                or ""
            )

            # Must mention temperature / °F
            if not re.search(
                r"\b(?:temperature|temp(?:erature)?|high|°[fF]|\bF\b)",
                question,
                re.IGNORECASE,
            ):
                continue

            # ── End-date filter ──────────────────────────────────────────────
            end_str: str = raw.get("endDate") or raw.get("end_date") or ""
            if not end_str:
                continue
            try:
                end_dt = datetime.fromisoformat(end_str.replace("Z", "+00:00"))
            except ValueError:
                continue
            if end_dt <= now or end_dt > cutoff_far:
                continue

            # ── Parse fields ─────────────────────────────────────────────────
            city_key = _parse_city(question)
            if city_key is None:
                continue

            target_date = _parse_date(question)
            if target_date is None:
                continue

            temp_range = _parse_temp_range(question)
            if temp_range is None:
                continue

            yes_price, no_price, yes_tid, no_tid = _parse_tokens(raw)

            # Skip degenerate prices (market essentially resolved)
            if yes_price < 0.02 or yes_price > 0.98:
                continue

            markets.append(
                PolymarketMarket(
                    market_id=str(raw.get("id", "")),
                    condition_id=str(raw.get("conditionId", "")),
                    question=question,
                    city_key=city_key,
                    target_date=target_date,
                    temp_range=temp_range,
                    yes_price=yes_price,
                    no_price=no_price,
                    token_id_yes=yes_tid,
                    token_id_no=no_tid,
                    end_date_iso=end_str,
                    volume_usd=float(raw.get("volume", 0) or 0),
                )
            )

    logger.info(
        "Gamma scan complete: %d temperature markets across %d pages",
        len(markets),
        page + 1,
    )
    return markets
