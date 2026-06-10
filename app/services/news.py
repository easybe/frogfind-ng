"""
Google News RSS parser.

Endpoints used:
  Top headlines : https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en
  Search        : https://news.google.com/rss/search?q=QUERY&hl=en-US&gl=US&ceid=US:en
  Category      : https://news.google.com/rss/headlines/section/topic/TOPIC?...
"""

from __future__ import annotations

import re
from email.utils import parsedate_to_datetime
from html import unescape as html_unescape
from typing import Dict, List, Optional
from xml.etree import ElementTree as ET

import httpx

from app.config import get_settings
from app.services.ddg import normalize_text

_BASE = "https://news.google.com/rss"

# Google News RSS category slugs
CATEGORIES: Dict[str, str] = {
    "world":         "WORLD",
    "nation":        "NATION",
    "business":      "BUSINESS",
    "technology":    "TECHNOLOGY",
    "entertainment": "ENTERTAINMENT",
    "sports":        "SPORTS",
    "science":       "SCIENCE",
    "health":        "HEALTH",
}

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
    "Accept-Language": "en-US,en;q=0.9",
}

_LOCALE = "hl=en-US&gl=US&ceid=US:en"

# Strip HTML tags from descriptions
_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(text: str) -> str:
    # First unescape HTML entities (&amp; &nbsp; etc.), then strip tags
    text = html_unescape(text or "")
    text = _TAG_RE.sub(" ", text)
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return normalize_text(text)


def _fmt_date(date_str: str) -> str:
    """Parse RFC-2822 pubDate → human readable, falls back to raw string."""
    try:
        dt = parsedate_to_datetime(date_str)
        return dt.strftime("%d %b %Y %H:%M UTC")
    except Exception:
        return date_str or ""


def _parse_feed(xml_text: str) -> List[Dict[str, str]]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    channel = root.find("channel")
    if channel is None:
        return []

    items = []
    for item in channel.findall("item"):
        title_el  = item.find("title")
        link_el   = item.find("link")
        date_el   = item.find("pubDate")
        desc_el   = item.find("description")
        source_el = item.find("source")

        title  = normalize_text(title_el.text  or "") if title_el  is not None else ""
        link   = (link_el.text or "").strip()         if link_el   is not None else ""
        date   = _fmt_date(date_el.text or "")        if date_el   is not None else ""
        desc   = _strip_html(desc_el.text or "")      if desc_el   is not None else ""
        source = normalize_text(source_el.text or "") if source_el is not None else ""

        if not title or not link:
            continue

        items.append({
            "title":  title,
            "url":    link,
            "date":   date,
            "source": source,
            "desc":   desc,
        })

    return items


async def fetch_news(
    query: Optional[str] = None,
    category: Optional[str] = None,
) -> List[Dict[str, str]]:
    settings = get_settings()

    if query:
        import urllib.parse
        url = f"{_BASE}/search?q={urllib.parse.quote(query)}&{_LOCALE}"
    elif category and category.lower() in CATEGORIES:
        slug = CATEGORIES[category.lower()]
        url = f"{_BASE}/headlines/section/topic/{slug}?{_LOCALE}"
    else:
        url = f"{_BASE}?{_LOCALE}"

    async with httpx.AsyncClient(
        timeout=settings.request_timeout,
        follow_redirects=True,
        headers=_HEADERS,
    ) as client:
        resp = await client.get(url)
        resp.raise_for_status()

    return _parse_feed(resp.text)
