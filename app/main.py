import os
import secrets
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.config import get_settings
from app.limiter import limiter
from app.routes import about, admin, image, news, reader, reddit, search, weather, wiki
from app.security.middleware import SecurityMiddleware
from app.services.cache import close_redis, get_blocked_ips, get_redis

templates = Jinja2Templates(directory="app/templates")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()

    # Resolve admin path — generate one if not set in .env
    if not settings.admin_path:
        generated = "admin-" + secrets.token_hex(8)
        print(f"\n{'='*60}")
        print(f"  WARNING: ADMIN_PATH not set in .env")
        print(f"  Using generated path: /{generated}/")
        print(f"  Add ADMIN_PATH={generated} to .env to persist it")
        print(f"{'='*60}\n", flush=True)
        app.state.admin_path = generated
    else:
        app.state.admin_path = settings.admin_path
        print(f"  Admin panel: /{app.state.admin_path}/dashboard", flush=True)

    # Warm Redis connection
    await get_redis()
    yield
    await close_redis()


def create_app() -> FastAPI:
    app = FastAPI(
        title="FrogFind NG",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )

    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    # Middleware (order matters: outermost first)
    app.add_middleware(SlowAPIMiddleware)
    app.add_middleware(SecurityMiddleware)

    # ── IP blocklist middleware ────────────────────────────────────────────────
    @app.middleware("http")
    async def ip_block_middleware(request: Request, call_next):
        client_ip = request.client.host if request.client else ""
        blocked = await get_blocked_ips()
        if client_ip in blocked:
            return HTMLResponse("Forbidden", status_code=403)

        # Maintenance mode check (skip admin paths)
        from app.services.cache import get_admin_settings
        if not request.url.path.startswith(f"/{request.app.state.admin_path}"):
            dyn = await get_admin_settings()
            if dyn.get("maintenance_mode") == "1":
                return templates.TemplateResponse(
                    "error.html",
                    {"request": request, "message": "FrogFind NG is under maintenance. Check back soon."},
                    status_code=503,
                )

        return await call_next(request)

    # ── Logo static route ─────────────────────────────────────────────────────
    _LOGO_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logo.jpg")

    @app.get("/logo.jpg", include_in_schema=False)
    async def serve_logo():
        if os.path.exists(_LOGO_PATH):
            return FileResponse(_LOGO_PATH, media_type="image/jpeg",
                                headers={"Cache-Control": "public, max-age=86400"})
        return HTMLResponse("Not found", status_code=404)

    # ── Routes ────────────────────────────────────────────────────────────────
    app.include_router(search.router)
    app.include_router(wiki.router)
    app.include_router(reddit.router)
    app.include_router(news.router)
    app.include_router(reader.router)
    app.include_router(image.router)
    app.include_router(weather.router)
    app.include_router(about.router)

    # Admin router is registered after lifespan sets app.state.admin_path,
    # but FastAPI requires routes at startup — so we read the env var directly.
    raw_settings = get_settings()
    admin_prefix = raw_settings.admin_path or "admin-startup"
    app.include_router(admin.router, prefix=f"/{admin_prefix}")

    return app


app = create_app()
