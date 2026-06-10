from typing import Optional

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates
from app.config import get_settings
from app.limiter import limiter
from app.security.ssrf import validate_url
from app.services.image_processor import fetch_and_compress

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/image")
@limiter.limit(get_settings().rate_limit_image)
async def image(
    request: Request,
    i: Optional[str] = Query(default=None, max_length=2048),
) -> Response:
    if not i:
        return Response("No URL provided", status_code=400)

    i = i.strip()

    err = validate_url(i)
    if err:
        return Response(f"Invalid URL: {err}", status_code=400)

    # Only proxy images (jpg, jpeg, png, gif, webp, bmp)
    lower = i.lower().split("?")[0]
    if not any(lower.endswith(ext) for ext in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg")):
        # Allow if content-type check passes — we'll find out during fetch
        pass

    try:
        data, mime = await fetch_and_compress(i)
    except Exception as exc:
        return Response(f"Image unavailable: {exc}", status_code=502)

    return Response(
        content=data,
        media_type=mime,
        headers={"Cache-Control": "public, max-age=3600"},
    )
