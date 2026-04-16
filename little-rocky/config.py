from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

SETTINGS_FILE = Path(__file__).parent / "settings.json"


@dataclass(frozen=True)
class CityConfig:
    name: str
    lat: float
    lon: float
    rmse: float  # Historical GFS high-temp RMSE in °F
    aliases: tuple[str, ...]


_DEFAULT_CITIES_DATA: dict = {
    "NYC": {
        "name": "New York City", "lat": 40.7128, "lon": -74.0060, "rmse": 3.5,
        "aliases": ["new york city", "new york", "nyc", "ny"], "enabled": True,
    },
    "CHICAGO": {
        "name": "Chicago", "lat": 41.8781, "lon": -87.6298, "rmse": 3.8,
        "aliases": ["chicago", "chi"], "enabled": True,
    },
    "DALLAS": {
        "name": "Dallas", "lat": 32.7800, "lon": -96.8000, "rmse": 4.0,
        "aliases": ["dallas", "dfw", "dallas-fort worth"], "enabled": True,
    },
    "ATLANTA": {
        "name": "Atlanta", "lat": 33.7490, "lon": -84.3880, "rmse": 3.6,
        "aliases": ["atlanta", "atl"], "enabled": True,
    },
    "MIAMI": {
        "name": "Miami", "lat": 25.7617, "lon": -80.1918, "rmse": 3.2,
        "aliases": ["miami", "mia"], "enabled": True,
    },
}

# ── Load user overrides from settings.json ────────────────────────────────────

def _load_settings() -> dict:
    if SETTINGS_FILE.exists():
        try:
            return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


_s: dict = _load_settings()


def _get(key: str, default):
    return _s.get(key, default)


def _build_cities() -> dict[str, CityConfig]:
    cities_data = _s.get("cities", _DEFAULT_CITIES_DATA)
    result: dict[str, CityConfig] = {}
    for key, data in cities_data.items():
        if not data.get("enabled", True):
            continue
        result[key] = CityConfig(
            name=data["name"],
            lat=float(data["lat"]),
            lon=float(data["lon"]),
            rmse=float(data["rmse"]),
            aliases=tuple(a.lower() for a in data.get("aliases", [key.lower()])),
        )
    return result


CITIES: dict[str, CityConfig] = _build_cities()

# ── Trading parameters ────────────────────────────────────────────────────────
EDGE_THRESHOLD: float        = _get("EDGE_THRESHOLD",        0.08)
KELLY_FRACTION: float        = _get("KELLY_FRACTION",        0.15)
MAX_BANKROLL_FRACTION: float = _get("MAX_BANKROLL_FRACTION", 0.05)
MAX_TRADE_USD: float         = _get("MAX_TRADE_USD",         2.00)
MAX_MARKET_USD: float        = _get("MAX_MARKET_USD",        4.00)
MAX_TOTAL_EXPOSURE: float    = _get("MAX_TOTAL_EXPOSURE",    50.00)
MIN_BET_USD: float           = _get("MIN_BET_USD",           0.10)

# ── Timing ────────────────────────────────────────────────────────────────────
SCAN_INTERVAL_SECONDS: int   = int(_get("SCAN_INTERVAL_SECONDS",    300))
MAX_HOURS_TO_RESOLUTION: int = int(_get("MAX_HOURS_TO_RESOLUTION",  48))

# ── Order execution ───────────────────────────────────────────────────────────
SLIPPAGE_TOLERANCE: float    = _get("SLIPPAGE_TOLERANCE", 0.05)
GTC_SLIPPAGE: float          = _get("GTC_SLIPPAGE",       0.02)

# ── Risk / circuit-breaker ────────────────────────────────────────────────────
CIRCUIT_BREAKER_LOSSES: int  = int(_get("CIRCUIT_BREAKER_LOSSES", 12))
CIRCUIT_BREAKER_WINDOW: int  = int(_get("CIRCUIT_BREAKER_WINDOW", 20))
DAILY_LOSS_LIMIT: float      = _get("DAILY_LOSS_LIMIT",           0.10)

# ── API endpoints ─────────────────────────────────────────────────────────────
GAMMA_API_URL: str           = "https://gamma-api.polymarket.com"
CLOB_API_URL: str            = "https://clob.polymarket.com"
OPEN_METEO_ENSEMBLE_URL: str = "https://ensemble-api.open-meteo.com/v1/ensemble"
OPEN_METEO_FORECAST_URL: str = "https://api.open-meteo.com/v1/forecast"

GAMMA_PAGE_SIZE: int = 100
GAMMA_MAX_PAGES: int = 30

# ── Storage ───────────────────────────────────────────────────────────────────
DB_PATH: str  = "little_rocky.db"
LOG_FILE: str = "little_rocky.log"
