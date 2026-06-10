"""
Weather service using Open-Meteo (weather data) + Nominatim/OSM (geocoding).
Both APIs are free and require no API key.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional, Tuple

import httpx

from app.config import get_settings

_NOM_URL    = "https://nominatim.openstreetmap.org/search"
_METEO_URL  = "https://api.open-meteo.com/v1/forecast"

_HEADERS = {
    "User-Agent": "FrogFindNG/1.0 (https://github.com; retro-search-engine)",
    "Accept": "application/json",
}

# ── WMO weather code → (description, ASCII art lines) ────────────────────────
_WMO: Dict[int, Tuple[str, List[str]]] = {
    0:  ("Clear Sky",          [r"   \  |  /   ", r"    --O--    ", r"   /  |  \   ", r"             "]),
    1:  ("Mainly Clear",       [r"   \  |  /   ", r"    --O--    ", r"   /  |  \   ", r"             "]),
    2:  ("Partly Cloudy",      [r"   \  /      ", r"  .--(  )    ", r" (  ___)     ", r"  `------'   "]),
    3:  ("Overcast",           [r"    .----.   ", r"  (        ) ", r" (  ------  )", r"  `--------' "]),
    45: ("Foggy",              [r" ============", r" ============", r" ============", r" ============"]),
    48: ("Rime Fog",           [r" ============", r" ============", r" ============", r" ============"]),
    51: ("Light Drizzle",      [r"    .----.   ", r"  (  ----  ) ", r"   ,  ,  ,   ", r"             "]),
    53: ("Drizzle",            [r"    .----.   ", r"  (  ----  ) ", r"  ,,  ,,  ,, ", r"             "]),
    55: ("Heavy Drizzle",      [r"    .----.   ", r"  (  ----  ) ", r" ,,,  ,,,  ,,", r"             "]),
    56: ("Freezing Drizzle",   [r"    .----.   ", r"  (  ----  ) ", r"  *,  *,  *, ", r"             "]),
    57: ("Freezing Drizzle",   [r"    .----.   ", r"  (  ----  ) ", r" *,,  *,,  * ", r"             "]),
    61: ("Light Rain",         [r"    .----.   ", r"  (  ----  ) ", r"   /  /  /   ", r"             "]),
    63: ("Rain",               [r"    .----.   ", r"  (  ----  ) ", r"  //  //  // ", r"             "]),
    65: ("Heavy Rain",         [r"    .----.   ", r"  (  ----  ) ", r" /// /// /// ", r"             "]),
    66: ("Freezing Rain",      [r"    .----.   ", r"  (  ----  ) ", r"  */ */ */   ", r"             "]),
    67: ("Freezing Rain",      [r"    .----.   ", r"  (  ----  ) ", r" *// *// *// ", r"             "]),
    71: ("Light Snow",         [r"    .----.   ", r"  (  ----  ) ", r"   *  .  *   ", r"             "]),
    73: ("Snow",               [r"    .----.   ", r"  (  ----  ) ", r"  * . * . *  ", r"             "]),
    75: ("Heavy Snow",         [r"    .----.   ", r"  (  ----  ) ", r" ** .* .* ** ", r"             "]),
    77: ("Snow Grains",        [r"    .----.   ", r"  (  ----  ) ", r"  . . . . .  ", r"             "]),
    80: ("Light Showers",      [r"    .----.   ", r"  (  ----  ) ", r"    / /      ", r"             "]),
    81: ("Showers",            [r"    .----.   ", r"  (  ----  ) ", r"   // //     ", r"             "]),
    82: ("Heavy Showers",      [r"    .----.   ", r"  (  ----  ) ", r"  /// ///    ", r"             "]),
    85: ("Snow Showers",       [r"    .----.   ", r"  (  ----  ) ", r"   * / *     ", r"             "]),
    86: ("Heavy Snow Showers", [r"    .----.   ", r"  (  ----  ) ", r"  ** // **   ", r"             "]),
    95: ("Thunderstorm",       [r"    .----.   ", r"  ( ##### ) ", r"    /\  /\   ", r"   /  \/  \  "]),
    96: ("Thunderstorm+Hail",  [r"    .----.   ", r"  ( ##### ) ", r"   /\ * /\   ", r"  /  \*/  \  "]),
    99: ("Thunderstorm+Hail",  [r"    .----.   ", r"  ( ##### ) ", r"  /\ ** /\   ", r" /  \**/  \  "]),
}

_FALLBACK_ART = [r"    .----.   ", r"  (  ????  ) ", r"   --------  ", r"             "]


def _wmo(code: int) -> Tuple[str, List[str]]:
    # Search exact, then nearest lower code
    if code in _WMO:
        return _WMO[code]
    for c in sorted(_WMO.keys(), reverse=True):
        if c <= code:
            return _WMO[c]
    return "Unknown", _FALLBACK_ART


def _c_to_f(c: float) -> int:
    return round(c * 9 / 5 + 32)


def _compass(deg: float) -> str:
    dirs = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    return dirs[round(deg / 45) % 8]


def _weekday(date_str: str) -> str:
    d = date.fromisoformat(date_str)
    return d.strftime("%a %d %b")


# ── Geocoding ─────────────────────────────────────────────────────────────────

async def geocode(city: str) -> Optional[Dict[str, Any]]:
    settings = get_settings()
    async with httpx.AsyncClient(timeout=settings.request_timeout, headers=_HEADERS) as client:
        resp = await client.get(_NOM_URL, params={
            "q": city, "format": "json", "limit": 1,
            "addressdetails": 1,
        })
        resp.raise_for_status()
        results = resp.json()

    if not results:
        return None
    r = results[0]
    addr = r.get("address", {})
    display = (
        addr.get("city") or addr.get("town") or addr.get("village") or r.get("name", city)
    )
    country = addr.get("country_code", "").upper()
    return {
        "lat":     float(r["lat"]),
        "lon":     float(r["lon"]),
        "city":    display,
        "country": country,
        "full":    f"{display}, {country}" if country else display,
    }


# ── Weather fetch ─────────────────────────────────────────────────────────────

async def get_weather(lat: float, lon: float) -> Dict[str, Any]:
    settings = get_settings()
    params = {
        "latitude":  lat,
        "longitude": lon,
        "current": ",".join([
            "temperature_2m", "apparent_temperature",
            "relative_humidity_2m", "weather_code",
            "wind_speed_10m", "wind_direction_10m",
            "precipitation", "uv_index", "is_day",
        ]),
        "daily": ",".join([
            "weather_code",
            "temperature_2m_max", "temperature_2m_min",
        ]),
        "timezone":      "auto",
        "forecast_days": 7,
        "wind_speed_unit": "kmh",
    }
    async with httpx.AsyncClient(timeout=settings.request_timeout, headers=_HEADERS) as client:
        resp = await client.get(_METEO_URL, params=params)
        resp.raise_for_status()
        data = resp.json()

    cur = data["current"]
    daily = data["daily"]

    code     = int(cur.get("weather_code", 0))
    desc, art = _wmo(code)
    temp_c   = round(cur["temperature_2m"], 1)
    feels_c  = round(cur["apparent_temperature"], 1)
    wind_kmh = round(cur["wind_speed_10m"])
    wind_dir = _compass(cur.get("wind_direction_10m", 0))
    humidity = int(cur.get("relative_humidity_2m", 0))
    uv       = round(cur.get("uv_index", 0), 1)
    precip   = round(cur.get("precipitation", 0), 1)

    # UV label
    if uv < 3:      uv_label = "Low"
    elif uv < 6:    uv_label = "Moderate"
    elif uv < 8:    uv_label = "High"
    elif uv < 11:   uv_label = "Very High"
    else:           uv_label = "Extreme"

    # 7-day forecast
    forecast = []
    for i in range(min(7, len(daily["time"]))):
        fc_code = int(daily["weather_code"][i])
        fc_desc, fc_art = _wmo(fc_code)
        forecast.append({
            "day":   _weekday(daily["time"][i]),
            "code":  fc_code,
            "desc":  fc_desc,
            "art":   fc_art,
            "max_c": round(daily["temperature_2m_max"][i], 1),
            "min_c": round(daily["temperature_2m_min"][i], 1),
            "max_f": _c_to_f(daily["temperature_2m_max"][i]),
            "min_f": _c_to_f(daily["temperature_2m_min"][i]),
        })

    return {
        "code":      code,
        "desc":      desc,
        "art":       art,
        "temp_c":    temp_c,
        "temp_f":    _c_to_f(temp_c),
        "feels_c":   feels_c,
        "feels_f":   _c_to_f(feels_c),
        "humidity":  humidity,
        "wind_kmh":  wind_kmh,
        "wind_mph":  round(wind_kmh * 0.621),
        "wind_dir":  wind_dir,
        "uv":        uv,
        "uv_label":  uv_label,
        "precip_mm": precip,
        "is_day":    bool(cur.get("is_day", 1)),
        "forecast":  forecast,
        "timezone":  data.get("timezone", ""),
    }


# ── Combined entry point ──────────────────────────────────────────────────────

async def fetch_weather_for_city(city: str) -> Tuple[Optional[Dict], Optional[Dict]]:
    """Returns (location_dict, weather_dict) or (None, None) on failure."""
    location = await geocode(city)
    if not location:
        return None, None
    weather = await get_weather(location["lat"], location["lon"])
    return location, weather
