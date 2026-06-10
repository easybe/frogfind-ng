"""
Wikipedia Quick Lookup — GET /wiki?q=Commodore+64
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
from app.services.wikipedia import fetch_wiki_page

log = logging.getLogger(__name__)
router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

_CACHE_TTL = 3600   # Wikipedia content is stable — 1 hour


@router.get("/wiki", include_in_schema=False)
@limiter.limit("30/minute")
async def wiki(request: Request, q: str = ""):
    q = q.strip()[:200]

    if not q:
        return templates.TemplateResponse("wiki.html", {
            "request": request,
            "query":   "",
            "data":    None,
            "error":   None,
        })

    redis = await get_redis()
    cache_key = f"wiki:{q.lower()}"
    cached = await redis.get(cache_key)
    if cached:
        try:
            data = json.loads(cached)
            return templates.TemplateResponse("wiki.html", {
                "request": request,
                "query":   _esc(q),
                "data":    data,
                "error":   None,
            })
        except Exception:
            pass

    try:
        data = await fetch_wiki_page(q)
    except Exception as exc:
        log.warning("Wikipedia fetch error for %r: %s", q, exc)
        return templates.TemplateResponse("wiki.html", {
            "request": request,
            "query":   _esc(q),
            "data":    None,
            "error":   "Wikipedia is currently unavailable. Please try again later.",
        }, status_code=503)

    if not data["results"] and not data["summary"]:
        return templates.TemplateResponse("wiki.html", {
            "request": request,
            "query":   _esc(q),
            "data":    None,
            "error":   f'No Wikipedia articles found for "{_esc(q)}".',
        }, status_code=404)

    try:
        await redis.setex(cache_key, _CACHE_TTL, json.dumps(data))
    except Exception:
        pass

    return templates.TemplateResponse("wiki.html", {
        "request": request,
        "query":   _esc(q),
        "data":    data,
        "error":   None,
    })
