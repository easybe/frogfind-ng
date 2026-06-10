import re
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

_BOT_RE = re.compile(
    r"(bot|crawler|spider|scraper|wget|curl/|python-requests|go-http-client"
    r"|java/|libwww|scrapy|masscan|nikto|sqlmap|nmap|zgrab|headlesschrome"
    r"|phantomjs|slurp|baiduspider|yandexbot|semrushbot|ahrefsbot|dotbot"
    r"|mj12bot|blexbot|petalbot|bytespider|gptbot|claudebot|ccbot|dataforseobot)",
    re.IGNORECASE,
)

# Paths that lure scanners — any hit → 403
_HONEYPOT_PATHS = frozenset({
    "/wp-admin", "/wp-login.php", "/.env", "/admin.php",
    "/phpmyadmin", "/xmlrpc.php", "/.git/config",
})

_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "X-XSS-Protection": "1; mode=block",
    "Referrer-Policy": "no-referrer",
    "Server": "Apache/2.4",          # obscure real stack
}

# Routes that set their own Cache-Control — middleware must not override
_CACHE_PASSTHROUGH = {"/logo.jpg", "/image"}


class SecurityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        ua = request.headers.get("user-agent", "")

        if not ua or _BOT_RE.search(ua):
            return Response("Forbidden", status_code=403)

        path = request.url.path.rstrip("/") or "/"
        if path in _HONEYPOT_PATHS:
            return Response("Not Found", status_code=404)

        response = await call_next(request)

        for k, v in _SECURITY_HEADERS.items():
            response.headers[k] = v

        # Only set no-store on non-cacheable routes
        if path not in _CACHE_PASSTHROUGH:
            response.headers["Cache-Control"] = "no-store"

        return response
