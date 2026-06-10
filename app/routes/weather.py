"""
Weather route — GET /weather?q=CityName
"""
from __future__ import annotations

import json
import logging
from html import escape as _esc

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.limiter import limiter
from app.services.cache import get_redis
from app.services.weather import fetch_weather_for_city

log = logging.getLogger(__name__)
router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

_CACHE_TTL = 600  # 10 minutes — weather changes slowly enough


@router.get("/weather", include_in_schema=False)
@limiter.limit("20/minute")
async def weather(request: Request, q: str = ""):
    q = q.strip()[:100]

    # No query → show search form
    if not q:
        return templates.TemplateResponse("weather.html", {
            "request":  request,
            "query":    "",
            "location": None,
            "weather":  None,
            "error":    None,
        })

    # Try cache first
    redis = await get_redis()
    cache_key = f"weather:{q.lower()}"
    cached = await redis.get(cache_key)
    if cached:
        try:
            payload = json.loads(cached)
            return templates.TemplateResponse("weather.html", {
                "request":  request,
                "query":    _esc(q),
                "location": payload["location"],
                "weather":  payload["weather"],
                "error":    None,
            })
        except Exception:
            pass  # fall through to live fetch

    # Live fetch
    try:
        location, weather_data = await fetch_weather_for_city(q)
    except Exception as exc:
        log.warning("Weather fetch error for %r: %s", q, exc)
        return templates.TemplateResponse("weather.html", {
            "request":  request,
            "query":    _esc(q),
            "location": None,
            "weather":  None,
            "error":    "Weather data unavailable. Please try again later.",
        }, status_code=503)

    if not location:
        return templates.TemplateResponse("weather.html", {
            "request":  request,
            "query":    _esc(q),
            "location": None,
            "weather":  None,
            "error":    f'City not found: "{_esc(q)}". Please check the spelling.',
        }, status_code=404)

    # Cache result
    try:
        payload = json.dumps({"location": location, "weather": weather_data})
        await redis.setex(cache_key, _CACHE_TTL, payload)
    except Exception:
        pass

    return templates.TemplateResponse("weather.html", {
        "request":  request,
        "query":    _esc(q),
        "location": location,
        "weather":  weather_data,
        "error":    None,
    })
