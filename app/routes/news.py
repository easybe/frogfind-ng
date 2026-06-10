import json
from typing import Optional

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.config import get_settings
from app.limiter import limiter
from app.services.cache import get_cached, incr_stat, set_cached
from app.services.news import CATEGORIES, fetch_news

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/news", response_class=HTMLResponse)
@limiter.limit(get_settings().rate_limit_search)
async def news(
    request: Request,
    q:   Optional[str] = Query(default=None, max_length=200),
    cat: Optional[str] = Query(default=None, max_length=50),
) -> HTMLResponse:
    q   = q.strip()   if q   else None
    cat = cat.strip().lower() if cat else None

    if cat and cat not in CATEGORIES:
        cat = None

    # Build cache key
    cache_key = f"news|q={q or ''}|cat={cat or ''}"
    cached = await get_cached("news", cache_key)
    if cached:
        await incr_stat("stat:cache_hits")
        items = json.loads(cached)
    else:
        await incr_stat("stat:cache_misses")
        try:
            items = await fetch_news(query=q, category=cat)
        except Exception as exc:
            return templates.TemplateResponse(
                "error.html",
                {"request": request,
                 "message": f"News feed temporarily unavailable. {exc}"},
                status_code=503,
            )
        if items:
            await set_cached("news", cache_key, json.dumps(items), 300)  # 5 min TTL

    return templates.TemplateResponse("news.html", {
        "request":    request,
        "items":      items,
        "query":      q,
        "category":   cat,
        "categories": CATEGORIES,
    })
