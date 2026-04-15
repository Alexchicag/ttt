from __future__ import annotations

import logging
import statistics
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Optional

import requests

from config import (
    CITIES,
    CityConfig,
    OPEN_METEO_ENSEMBLE_URL,
    OPEN_METEO_FORECAST_URL,
)

logger = logging.getLogger(__name__)

# GFS ensemble has 31 members (member01 … member31 on Open-Meteo)
GFS_MEMBER_COUNT = 31
GFS_MODEL = "gfs_seamless"
FORECAST_DAYS = 3


@dataclass
class WeatherForecast:
    """Daily high-temperature forecast for one city on one date."""

    city_key: str
    date: date
    temp_mean_f: float   # Mean of ensemble member daily highs
    temp_std_f: float    # Spread (std-dev) of ensemble member daily highs
    source: str          # "ensemble" or "standard"
    member_count: int    # How many members contributed


# ── Ensemble (primary) ────────────────────────────────────────────────────────

def _fetch_ensemble(city_key: str, city: CityConfig) -> dict[date, WeatherForecast] | None:
    """
    Fetch GFS ensemble forecast from Open-Meteo (31 members, hourly temp_2m).
    Returns a mapping of date → WeatherForecast, or None on failure / quota.
    One API call covers all forecast days for this city.
    """
    params: dict = {
        "latitude": city.lat,
        "longitude": city.lon,
        "hourly": "temperature_2m",
        "models": GFS_MODEL,
        "temperature_unit": "fahrenheit",
        "timeformat": "unixtime",
        "timezone": "UTC",
        "forecast_days": FORECAST_DAYS,
    }

    try:
        resp = requests.get(OPEN_METEO_ENSEMBLE_URL, params=params, timeout=30)

        if resp.status_code == 429:
            logger.warning("[%s] Ensemble quota exhausted (429)", city_key)
            return None
        resp.raise_for_status()

        data: dict = resp.json()
        hourly: dict = data.get("hourly", {})
        times: list[int] = hourly.get("time", [])

        # Collect all member keys (temperature_2m_member01 … temperature_2m_member31)
        member_keys = sorted(
            k for k in hourly if k.startswith("temperature_2m_member")
        )

        if not member_keys:
            logger.warning("[%s] No ensemble member keys in response", city_key)
            return None

        # Build per-date, per-member hour lists
        # Structure: daily_hours[date][member_index] = [temp, temp, …]
        daily_hours: dict[date, list[list[float]]] = {}

        for idx, ts in enumerate(times):
            dt = datetime.fromtimestamp(ts, tz=timezone.utc).date()
            if dt not in daily_hours:
                daily_hours[dt] = [[] for _ in member_keys]
            for j, mk in enumerate(member_keys):
                val = hourly[mk][idx]
                if val is not None:
                    daily_hours[dt][j].append(float(val))

        forecasts: dict[date, WeatherForecast] = {}
        for d, member_hours in daily_hours.items():
            # Daily high per member
            member_highs = [max(hrs) for hrs in member_hours if hrs]
            if not member_highs:
                continue

            mean_f = statistics.mean(member_highs)
            std_f = statistics.pstdev(member_highs) if len(member_highs) > 1 else 0.0

            forecasts[d] = WeatherForecast(
                city_key=city_key,
                date=d,
                temp_mean_f=mean_f,
                temp_std_f=std_f,
                source="ensemble",
                member_count=len(member_highs),
            )

        logger.info(
            "[%s] Ensemble: %d days, %d members, mean_today=%.1f°F",
            city_key,
            len(forecasts),
            len(member_keys),
            next(iter(forecasts.values())).temp_mean_f if forecasts else 0,
        )
        return forecasts

    except requests.HTTPError as exc:
        logger.error("[%s] Ensemble HTTP error: %s", city_key, exc)
        return None
    except Exception as exc:
        logger.error("[%s] Ensemble fetch error: %s", city_key, exc)
        return None


# ── Standard forecast (fallback) ─────────────────────────────────────────────

def _fetch_standard(city_key: str, city: CityConfig) -> dict[date, WeatherForecast] | None:
    """
    Fallback: fetch deterministic daily-high forecast from Open-Meteo.
    std_f will be 0; the RMSE from config acts as the sole uncertainty term.
    """
    params: dict = {
        "latitude": city.lat,
        "longitude": city.lon,
        "daily": "temperature_2m_max",
        "temperature_unit": "fahrenheit",
        "timezone": "UTC",
        "forecast_days": FORECAST_DAYS,
    }

    try:
        resp = requests.get(OPEN_METEO_FORECAST_URL, params=params, timeout=30)
        resp.raise_for_status()
        data: dict = resp.json()

        daily: dict = data.get("daily", {})
        date_strs: list[str] = daily.get("time", [])
        highs: list[Optional[float]] = daily.get("temperature_2m_max", [])

        forecasts: dict[date, WeatherForecast] = {}
        for d_str, high in zip(date_strs, highs):
            if high is None:
                continue
            d = date.fromisoformat(d_str)
            forecasts[d] = WeatherForecast(
                city_key=city_key,
                date=d,
                temp_mean_f=float(high),
                temp_std_f=0.0,
                source="standard",
                member_count=1,
            )

        logger.info("[%s] Standard fallback: %d days", city_key, len(forecasts))
        return forecasts

    except Exception as exc:
        logger.error("[%s] Standard forecast error: %s", city_key, exc)
        return None


# ── Public entry point ────────────────────────────────────────────────────────

def fetch_all_forecasts() -> dict[str, dict[date, WeatherForecast]]:
    """
    Fetch forecasts for all 5 cities.  One API call per city (ensemble),
    with automatic fallback to the standard forecast API on quota/error.

    Returns: { city_key: { date: WeatherForecast } }
    """
    all_forecasts: dict[str, dict[date, WeatherForecast]] = {}

    for city_key, city in CITIES.items():
        forecasts = _fetch_ensemble(city_key, city)

        if forecasts is None:
            logger.info("[%s] Falling back to standard forecast", city_key)
            forecasts = _fetch_standard(city_key, city)

        if forecasts:
            all_forecasts[city_key] = forecasts
        else:
            logger.error("[%s] All forecast sources failed", city_key)

    return all_forecasts
