import ipaddress
import re
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.config import get_settings
from app.limiter import limiter
from app.security.auth import create_token, hash_password, require_admin, verify_password
from app.services.cache import (
    add_blocked_ip, get_admin_settings, get_blocked_ips,
    get_stat, lrange, remove_blocked_ip, set_admin_setting,
)

_RATE_LIMIT_RE = re.compile(r"^\d+/(second|minute|hour|day)$")

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


# ── Login ──────────────────────────────────────────────────────────────────────

@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("admin/login.html", {"request": request, "error": None})


@router.post("/login", response_model=None)
@limiter.limit("10/minute")
async def login_submit(
    request: Request,
    password: Annotated[str, Form()],
):
    settings = get_settings()

    if not settings.admin_password_hash:
        return templates.TemplateResponse(
            "admin/login.html",
            {"request": request, "error": "Admin password not configured. Set ADMIN_PASSWORD_HASH in .env"},
            status_code=500,
        )

    if not verify_password(password, settings.admin_password_hash):
        return templates.TemplateResponse(
            "admin/login.html",
            {"request": request, "error": "Invalid password"},
            status_code=401,
        )

    token = create_token({"role": "admin"})
    response = RedirectResponse(url="dashboard", status_code=303)
    response.set_cookie(
        key="admin_token",
        value=token,
        httponly=True,
        samesite="strict",
        secure=not settings.debug,
        max_age=28800,
    )
    return response


@router.get("/logout")
async def logout() -> RedirectResponse:
    response = RedirectResponse(url="login", status_code=303)
    response.delete_cookie("admin_token")
    return response


# ── Dashboard ─────────────────────────────────────────────────────────────────

@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    _: dict = Depends(require_admin),
) -> HTMLResponse:
    settings = get_settings()
    dyn = await get_admin_settings()

    stats = {
        "searches_today": await get_stat("stat:searches_today"),
        "reads_today": await get_stat("stat:reads_today"),
        "cache_hits": await get_stat("stat:cache_hits"),
        "cache_misses": await get_stat("stat:cache_misses"),
        "recent_searches": await lrange("stat:recent_searches", 0, 19),
        "blocked_ips": sorted(await get_blocked_ips()),
    }

    # Merge static defaults with dynamic overrides
    current_settings = {
        "maintenance_mode": dyn.get("maintenance_mode", "0"),
        "rate_limit_search": dyn.get("rate_limit_search", settings.rate_limit_search),
        "rate_limit_read": dyn.get("rate_limit_read", settings.rate_limit_read),
        "rate_limit_image": dyn.get("rate_limit_image", settings.rate_limit_image),
        "cache_ttl_search": dyn.get("cache_ttl_search", str(settings.cache_ttl_search)),
        "cache_ttl_article": dyn.get("cache_ttl_article", str(settings.cache_ttl_article)),
        "max_download_size": dyn.get("max_download_size", str(settings.max_download_size)),
        "request_timeout": dyn.get("request_timeout", str(settings.request_timeout)),
    }

    return templates.TemplateResponse(
        "admin/dashboard.html",
        {"request": request, "stats": stats, "settings": current_settings},
    )


# ── Settings update ───────────────────────────────────────────────────────────

@router.post("/settings")
async def update_settings(
    request: Request,
    _: dict = Depends(require_admin),
    maintenance_mode: Annotated[Optional[str], Form()] = None,
    rate_limit_search: Annotated[Optional[str], Form()] = None,
    rate_limit_read: Annotated[Optional[str], Form()] = None,
    rate_limit_image: Annotated[Optional[str], Form()] = None,
    cache_ttl_search: Annotated[Optional[str], Form()] = None,
    cache_ttl_article: Annotated[Optional[str], Form()] = None,
    max_download_size: Annotated[Optional[str], Form()] = None,
    request_timeout: Annotated[Optional[str], Form()] = None,
) -> RedirectResponse:
    def _safe_rate(val: Optional[str], default: str) -> str:
        v = (val or "").strip()
        return v if _RATE_LIMIT_RE.match(v) else default

    def _safe_int(val: Optional[str], default: str, min_val: int = 0) -> str:
        try:
            n = int(val or default)
            return str(max(n, min_val))
        except ValueError:
            return default

    def _safe_float(val: Optional[str], default: str) -> str:
        try:
            return str(max(float(val or default), 1.0))
        except ValueError:
            return default

    updates = {
        "maintenance_mode": "1" if maintenance_mode else "0",
        "rate_limit_search": _safe_rate(rate_limit_search, "30/minute"),
        "rate_limit_read":   _safe_rate(rate_limit_read,   "60/minute"),
        "rate_limit_image":  _safe_rate(rate_limit_image,  "120/minute"),
        "cache_ttl_search":  _safe_int(cache_ttl_search,  "600",     60),
        "cache_ttl_article": _safe_int(cache_ttl_article, "1800",    60),
        "max_download_size": _safe_int(max_download_size, "8388608", 65536),
        "request_timeout":   _safe_float(request_timeout, "15.0"),
    }
    for field, value in updates.items():
        await set_admin_setting(field, value)

    return RedirectResponse(url="dashboard?saved=1", status_code=303)


# ── IP block management ───────────────────────────────────────────────────────

@router.post("/block-ip")
async def block_ip(
    _: dict = Depends(require_admin),
    ip: Annotated[str, Form()] = "",
) -> RedirectResponse:
    ip = ip.strip()
    if ip:
        try:
            ipaddress.ip_address(ip)   # validates format
            await add_blocked_ip(ip)
        except ValueError:
            pass  # silently ignore invalid IPs
    return RedirectResponse(url="dashboard", status_code=303)


@router.post("/unblock-ip")
async def unblock_ip(
    _: dict = Depends(require_admin),
    ip: Annotated[str, Form()] = "",
) -> RedirectResponse:
    if ip.strip():
        await remove_blocked_ip(ip.strip())
    return RedirectResponse(url="dashboard", status_code=303)
