from typing import Optional

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, Response, StreamingResponse
from fastapi.templating import Jinja2Templates
from app.config import get_settings
from app.limiter import limiter
from app.security.ssrf import validate_url
from app.services.cache import get_cached, incr_stat, set_cached
from app.services.readability_service import fetch_and_extract, fetch_binary
from app.services.wayback import get_snapshot_url, wayback_reader_url

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/read", response_class=HTMLResponse)
@limiter.limit(get_settings().rate_limit_read)
async def read(
    request: Request,
    a: Optional[str] = Query(default=None, max_length=2048),
) -> Response:
    if not a:
        return templates.TemplateResponse(
            "error.html",
            {"request": request, "message": "No URL provided. Use ?a=https://example.com"},
            status_code=400,
        )

    a = a.strip()

    err = validate_url(a)
    if err:
        return templates.TemplateResponse(
            "error.html",
            {"request": request, "message": f"Invalid URL: {err}"},
            status_code=400,
        )

    cached = await get_cached("article", a)
    if cached:
        await incr_stat("stat:cache_hits")
        return HTMLResponse(content=cached)

    await incr_stat("stat:cache_misses")
    await incr_stat("stat:reads_today", ttl=86400)

    try:
        title, content, content_type, content_length = await fetch_and_extract(a)
    except Exception as exc:
        # Check Wayback Machine for an archived copy
        snapshot = await get_snapshot_url(a)
        wb_link = (
            f' &mdash; <a href="/read?a={snapshot}">[Try Wayback Machine archive]</a>'
            if snapshot else
            f' &mdash; <a href="{wayback_reader_url(a)}">[Search Wayback Machine]</a>'
        )
        return templates.TemplateResponse(
            "error.html",
            {"request": request, "message": f"Could not load page. {exc}{wb_link}"},
            status_code=502,
        )

    settings = get_settings()

    # Non-HTML content: proxy download if within size limit
    if title is None:
        if content_length and content_length > settings.max_download_size:
            from html import escape as _esc
            safe_url = _esc(a)
            return templates.TemplateResponse(
                "error.html",
                {
                    "request": request,
                    "message": (
                        f"File too large to proxy ({content_length // 1024 // 1024} MB). "
                        f'<a href="{safe_url}">Download directly</a>'
                    ),
                },
                status_code=413,
            )
        try:
            data, ct = await fetch_binary(a)
        except Exception as exc:
            return templates.TemplateResponse(
                "error.html",
                {"request": request, "message": f"Download failed: {exc}"},
                status_code=502,
            )
        filename = a.split("/")[-1] or "file"
        return Response(
            content=data,
            media_type=ct,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    # Render article
    response = templates.TemplateResponse(
        "read.html",
        {
            "request":      request,
            "title":        title,
            "content":      content,
            "original_url": a,
            "wayback_url":  wayback_reader_url(a),
        },
    )
    html = response.body.decode("utf-8", errors="replace")
    await set_cached("article", a, html, settings.cache_ttl_article)
    return response
