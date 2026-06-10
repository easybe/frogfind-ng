"""
Wayback Machine / Internet Archive integration.

Availability API: https://archive.org/wayback/available?url=URL
No API key required.
"""
from __future__ import annotations

from typing import Optional
from urllib.parse import quote

import httpx

from app.config import get_settings

_AVAIL_URL = "https://archive.org/wayback/available"

_HEADERS = {
    "User-Agent": "FrogFindNG/1.0 (retro-search-engine)",
    "Accept": "application/json",
}


async def get_snapshot_url(url: str) -> Optional[str]:
    """
    Check if a URL has a Wayback Machine snapshot.
    Returns the snapshot URL (https://web.archive.org/web/TIMESTAMP/URL)
    or None if no snapshot is available.
    """
    settings = get_settings()
    try:
        async with httpx.AsyncClient(
            timeout=min(settings.request_timeout, 8.0),
            headers=_HEADERS,
        ) as c:
            resp = await c.get(_AVAIL_URL, params={"url": url})
            resp.raise_for_status()
            data = resp.json()

        snapshot = data.get("archived_snapshots", {}).get("closest", {})
        if snapshot.get("available") and snapshot.get("status", "").startswith("2"):
            return snapshot["url"]
    except Exception:
        pass
    return None


def wayback_reader_url(original_url: str) -> str:
    """
    Build a /read URL that loads the Wayback Machine copy of original_url.
    Does NOT call the API — Wayback Machine handles "find closest" automatically.
    Suitable for always-on navigation links.
    """
    wb = f"https://web.archive.org/web/{original_url}"
    return f"/read?a={quote(wb, safe='')}"
