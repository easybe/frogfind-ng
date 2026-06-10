"""
Wikipedia service.

Endpoints used (no API key required):
  Search  : https://en.wikipedia.org/w/api.php?action=query&list=search&...
  Summary : https://en.wikipedia.org/api/rest_v1/page/summary/{title}
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import httpx

from app.config import get_settings

_SEARCH_URL  = "https://en.wikipedia.org/w/api.php"
_SUMMARY_URL = "https://en.wikipedia.org/api/rest_v1/page/summary"

_HEADERS = {
    "User-Agent": "FrogFindNG/1.0 (retro-search-engine; contact via GitHub)",
    "Accept": "application/json",
}

_TAG_RE = re.compile(r"<[^>]+>")


def _strip_tags(text: str) -> str:
    return _TAG_RE.sub("", text or "").strip()


async def search_wikipedia(query: str, limit: int = 8) -> List[Dict[str, str]]:
    """Return list of search results: title + snippet."""
    settings = get_settings()
    async with httpx.AsyncClient(timeout=settings.request_timeout, headers=_HEADERS) as c:
        resp = await c.get(_SEARCH_URL, params={
            "action": "query",
            "list": "search",
            "srsearch": query,
            "srlimit": limit,
            "format": "json",
            "origin": "*",
        })
        resp.raise_for_status()
        data = resp.json()

    results = []
    for item in data.get("query", {}).get("search", []):
        results.append({
            "title":   item.get("title", ""),
            "snippet": _strip_tags(item.get("snippet", "")),
            "pageid":  str(item.get("pageid", "")),
        })
    return results


async def get_summary(title: str) -> Optional[Dict[str, Any]]:
    """Return page summary dict or None."""
    settings = get_settings()
    encoded = quote(title.replace(" ", "_"), safe="")
    async with httpx.AsyncClient(
        timeout=settings.request_timeout,
        headers=_HEADERS,
        follow_redirects=True,
    ) as c:
        resp = await c.get(f"{_SUMMARY_URL}/{encoded}")
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        data = resp.json()

    thumb = data.get("thumbnail")
    thumb_url = thumb.get("source") if thumb else None

    return {
        "title":      data.get("title", title),
        "extract":    data.get("extract", ""),
        "thumb_url":  thumb_url,
        "page_url":   data.get("content_urls", {}).get("desktop", {}).get("page", ""),
        "lang":       data.get("lang", "en"),
        "description": data.get("description", ""),
    }


async def fetch_wiki_page(query: str) -> Dict[str, Any]:
    """
    Combined: search for query, fetch summary of top result.
    Returns dict with keys: summary, results, query.
    """
    results = await search_wikipedia(query, limit=8)
    summary = None
    if results:
        summary = await get_summary(results[0]["title"])
    return {
        "query":   query,
        "summary": summary,
        "results": results[1:],   # rest shown as "Other results"
    }
