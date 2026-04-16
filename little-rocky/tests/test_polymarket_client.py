from __future__ import annotations

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import date
import pytest
from polymarket_client import (
    TempRange,
    _parse_city,
    _parse_date,
    _parse_temp_range,
    _parse_tokens,
)


# ── _parse_city ───────────────────────────────────────────────────────────────

class TestParseCity:

    def test_nyc_full_name(self):
        assert _parse_city("Will New York City high temp exceed 70°F?") == "NYC"

    def test_nyc_abbreviation(self):
        assert _parse_city("NYC high temperature April 15") == "NYC"

    def test_chicago(self):
        assert _parse_city("Chicago high temp on May 3rd") == "CHICAGO"

    def test_chicago_alias_chi(self):
        assert _parse_city("CHI daily high April 20") == "CHICAGO"

    def test_dallas(self):
        assert _parse_city("Dallas high temperature tomorrow") == "DALLAS"

    def test_dfw_alias(self):
        assert _parse_city("DFW high temp June 1st") == "DALLAS"

    def test_atlanta(self):
        assert _parse_city("Atlanta high temperature April 15") == "ATLANTA"

    def test_miami(self):
        assert _parse_city("Miami daily high above 85°F?") == "MIAMI"

    def test_unknown_city_returns_none(self):
        assert _parse_city("London high temperature today") is None

    def test_case_insensitive(self):
        assert _parse_city("new york city temperature") == "NYC"


# ── _parse_date ───────────────────────────────────────────────────────────────

class TestParseDate:

    def test_month_day_full(self):
        d = _parse_date("NYC high temp on April 15, 2025")
        assert d == date(2025, 4, 15)

    def test_month_day_abbreviated(self):
        d = _parse_date("Chicago temp Apr 20, 2025")
        assert d is not None
        assert d.month == 4
        assert d.day == 20

    def test_ordinal_suffix(self):
        d = _parse_date("Miami high on June 3rd, 2025")
        assert d == date(2025, 6, 3)

    def test_day_month_format(self):
        d = _parse_date("15th April 2025 Dallas high")
        assert d is not None
        assert d.day == 15
        assert d.month == 4

    def test_slash_format(self):
        d = _parse_date("Will NYC reach 75°F on 4/15/2025?")
        assert d == date(2025, 4, 15)

    def test_slash_format_without_year(self):
        d = _parse_date("Will NYC reach 75°F on 4/15?")
        assert d is not None
        assert d.month == 4
        assert d.day == 15

    def test_no_date_returns_none(self):
        d = _parse_date("Will Miami be hot?")
        assert d is None


# ── _parse_temp_range ─────────────────────────────────────────────────────────

class TestParseTempRange:

    def test_between_and(self):
        tr = _parse_temp_range("Will the high be between 70 and 80°F?")
        assert tr is not None
        assert tr.low == 70.0
        assert tr.high == 80.0
        assert not tr.is_above
        assert not tr.is_below

    def test_dash_range(self):
        tr = _parse_temp_range("NYC high 65-75°F on April 15")
        assert tr is not None
        assert tr.low == 65.0
        assert tr.high == 75.0

    def test_to_range(self):
        tr = _parse_temp_range("temperature 60 to 70°F")
        assert tr is not None
        assert tr.low == 60.0
        assert tr.high == 70.0

    def test_above(self):
        tr = _parse_temp_range("Will the high be above 80°F?")
        assert tr is not None
        assert tr.is_above
        assert tr.low == 80.0
        assert tr.high is None

    def test_over(self):
        tr = _parse_temp_range("NYC temp over 75°F")
        assert tr is not None
        assert tr.is_above

    def test_or_higher(self):
        tr = _parse_temp_range("Will it reach 90°F or higher?")
        assert tr is not None
        assert tr.is_above
        assert tr.low == 90.0

    def test_below(self):
        tr = _parse_temp_range("Will the high be below 40°F?")
        assert tr is not None
        assert tr.is_below
        assert tr.high == 40.0
        assert tr.low is None

    def test_under(self):
        tr = _parse_temp_range("temperature under 50°F")
        assert tr is not None
        assert tr.is_below

    def test_or_lower(self):
        tr = _parse_temp_range("Will it stay 35°F or lower?")
        assert tr is not None
        assert tr.is_below
        assert tr.high == 35.0

    def test_low_high_swapped_corrected(self):
        # Parser should normalise lo/hi even if written as "80-65"
        tr = _parse_temp_range("NYC high 80-65°F")
        assert tr is not None
        assert tr.low == 65.0
        assert tr.high == 80.0

    def test_no_temp_returns_none(self):
        tr = _parse_temp_range("Will it rain tomorrow?")
        assert tr is None

    def test_label_range(self):
        tr = TempRange(low=60.0, high=70.0)
        assert tr.label() == "60–70°F"

    def test_label_above(self):
        tr = TempRange(low=80.0, high=None, is_above=True)
        assert tr.label() == ">80°F"

    def test_label_below(self):
        tr = TempRange(low=None, high=40.0, is_below=True)
        assert tr.label() == "<40°F"


# ── _parse_tokens ─────────────────────────────────────────────────────────────

class TestParseTokens:

    def test_standard_yes_no(self):
        data = {
            "tokens": [
                {"outcome": "YES", "price": "0.65", "token_id": "abc123"},
                {"outcome": "NO",  "price": "0.35", "token_id": "def456"},
            ]
        }
        yes_p, no_p, yes_tid, no_tid = _parse_tokens(data)
        assert yes_p == pytest.approx(0.65)
        assert no_p  == pytest.approx(0.35)
        assert yes_tid == "abc123"
        assert no_tid  == "def456"

    def test_empty_tokens_returns_defaults(self):
        yes_p, no_p, yes_tid, no_tid = _parse_tokens({})
        assert yes_p == 0.5
        assert no_p  == 0.5
        assert yes_tid == ""
        assert no_tid  == ""

    def test_none_price_defaults_to_half(self):
        data = {
            "tokens": [
                {"outcome": "YES", "price": None, "token_id": "x"},
                {"outcome": "NO",  "price": None, "token_id": "y"},
            ]
        }
        yes_p, no_p, _, _ = _parse_tokens(data)
        assert yes_p == 0.5
        assert no_p  == 0.5
