from typing import List, Dict
from urllib.parse import parse_qs, urlparse

import httpx
from bs4 import BeautifulSoup

from app.config import get_settings

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xhtml+xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate",
    "DNT": "1",
}

_UNICODE_MAP = {
    "“": '"', "”": '"',
    "‘": "'", "’": "'",
    "–": "-", "—": "-",
    "…": "...",
    " ": " ",
    "•": "*",
    "·": "*",
}


def normalize_text(text: str) -> str:
    for k, v in _UNICODE_MAP.items():
        text = text.replace(k, v)
    return text.strip()


def _extract_real_url(href: str) -> str:
    """Unwrap DuckDuckGo redirect URLs to retrieve the actual destination."""
    if not href:
        return ""
    if href.startswith("//"):
        href = "https:" + href
    try:
        parsed = urlparse(href)
        if "duckduckgo.com" in (parsed.netloc or ""):
            params = parse_qs(parsed.query)
            if "uddg" in params:
                return params["uddg"][0]
        return href
    except Exception:
        return href


async def search(query: str) -> List[Dict[str, str]]:
    settings = get_settings()

    async with httpx.AsyncClient(
        timeout=settings.request_timeout,
        follow_redirects=True,
        headers=_HEADERS,
    ) as client:
        resp = await client.get(settings.ddg_url, params={"q": query, "kl": "us-en"})
        resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "lxml")
    results: List[Dict[str, str]] = []

    for div in soup.find_all("div", class_="result"):
        classes = " ".join(div.get("class", []))
        if "badge--ad" in classes:
            continue
        if div.find(class_="badge--ad"):
            continue

        title_el = div.find("a", class_="result__a")
        if not title_el:
            continue

        url_el = div.find("a", class_="result__url")
        snippet_el = div.find(class_="result__snippet")

        title = normalize_text(title_el.get_text())
        actual_url = _extract_real_url(title_el.get("href", ""))

        if not actual_url or not actual_url.startswith("http"):
            continue

        display_url = normalize_text(url_el.get_text()) if url_el else actual_url
        snippet = normalize_text(snippet_el.get_text()) if snippet_el else ""

        results.append(
            {
                "title": title,
                "url": actual_url,
                "display_url": display_url,
                "snippet": snippet,
            }
        )

    return results
