import json
from typing import Optional

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from app.config import get_settings
from app.limiter import limiter
from app.services.cache import (
    get_cached, incr_stat, lpush_capped, set_cached,
)
from app.services.ddg import search

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/", response_class=HTMLResponse)
@limiter.limit(get_settings().rate_limit_search)
async def index(
    request: Request,
    q: Optional[str] = Query(default=None, max_length=200),
) -> HTMLResponse:
    if not q or not q.strip():
        return templates.TemplateResponse("index.html", {"request": request, "query": "", "results": None})

    q = q.strip()

    cached = await get_cached("search", q)
    if cached:
        await incr_stat("stat:cache_hits")
        results = json.loads(cached)
    else:
        await incr_stat("stat:cache_misses")
        await incr_stat("stat:searches_today", ttl=86400)
        await lpush_capped("stat:recent_searches", q, cap=20)

        try:
            results = await search(q)
        except Exception:
            return templates.TemplateResponse(
                "error.html",
                {"request": request, "message": "Search is temporarily unavailable. Please try again."},
                status_code=503,
            )

        if results:
            settings = get_settings()
            await set_cached("search", q, json.dumps(results), settings.cache_ttl_search)

    return templates.TemplateResponse("index.html", {"request": request, "query": q, "results": results})
