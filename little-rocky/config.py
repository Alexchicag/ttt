from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class CityConfig:
    name: str
    lat: float
    lon: float
    rmse: float  # Historical GFS high-temp RMSE in °F
    aliases: tuple[str, ...]


CITIES: dict[str, CityConfig] = {
    "NYC": CityConfig(
        name="New York City",
        lat=40.7128,
        lon=-74.0060,
        rmse=3.5,
        aliases=("new york city", "new york", "nyc", "ny"),
    ),
    "CHICAGO": CityConfig(
        name="Chicago",
        lat=41.8781,
        lon=-87.6298,
        rmse=3.8,
        aliases=("chicago", "chi"),
    ),
    "DALLAS": CityConfig(
        name="Dallas",
        lat=32.7800,
        lon=-96.8000,
        rmse=4.0,
        aliases=("dallas", "dfw", "dallas-fort worth"),
    ),
    "ATLANTA": CityConfig(
        name="Atlanta",
        lat=33.7490,
        lon=-84.3880,
        rmse=3.6,
        aliases=("atlanta", "atl"),
    ),
    "MIAMI": CityConfig(
        name="Miami",
        lat=25.7617,
        lon=-80.1918,
        rmse=3.2,
        aliases=("miami", "mia"),
    ),
}

# ── Trading parameters ────────────────────────────────────────────────────────
EDGE_THRESHOLD: float = 0.08        # 8 % minimum edge before we consider a trade
KELLY_FRACTION: float = 0.15        # Fractional Kelly multiplier
MAX_BANKROLL_FRACTION: float = 0.05 # Hard cap: 5 % of bankroll per trade
MAX_TRADE_USD: float = 2.00         # Hard cap per single trade
MAX_MARKET_USD: float = 4.00        # Hard cap total exposure per market
MAX_TOTAL_EXPOSURE: float = 50.00   # Hard cap total open exposure
MIN_BET_USD: float = 0.10           # Ignore bets smaller than this

# ── Timing ────────────────────────────────────────────────────────────────────
SCAN_INTERVAL_SECONDS: int = 300    # 5 minutes between cycles
MAX_HOURS_TO_RESOLUTION: int = 48   # Only trade markets resolving within 48 h

# ── Order execution ───────────────────────────────────────────────────────────
SLIPPAGE_TOLERANCE: float = 0.05    # 5 % slippage on FOK limit price
GTC_SLIPPAGE: float = 0.02          # 2 % slippage on GTC fallback price

# ── Risk / circuit-breaker ────────────────────────────────────────────────────
CIRCUIT_BREAKER_LOSSES: int = 12    # Trip if this many of the last N trades lost
CIRCUIT_BREAKER_WINDOW: int = 20    # Rolling window size
DAILY_LOSS_LIMIT: float = 0.10      # Trip if daily loss > 10 % of bankroll

# ── API endpoints ─────────────────────────────────────────────────────────────
GAMMA_API_URL: str = "https://gamma-api.polymarket.com"
CLOB_API_URL: str = "https://clob.polymarket.com"
OPEN_METEO_ENSEMBLE_URL: str = "https://ensemble-api.open-meteo.com/v1/ensemble"
OPEN_METEO_FORECAST_URL: str = "https://api.open-meteo.com/v1/forecast"

GAMMA_PAGE_SIZE: int = 100          # Markets per Gamma API page
GAMMA_MAX_PAGES: int = 30           # Maximum pages to scan

# ── Storage ───────────────────────────────────────────────────────────────────
DB_PATH: str = "little_rocky.db"
LOG_FILE: str = "little_rocky.log"
