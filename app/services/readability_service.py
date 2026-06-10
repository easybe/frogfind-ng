import asyncio
from typing import Optional, Tuple
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup
from readability import Document

from app.config import get_settings
from app.services.ddg import normalize_text

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

_REMOVE_TAGS = {"script", "style", "iframe", "noscript", "svg", "form", "button", "input"}


def _convert_to_retro(html: str, base_url: str) -> str:
    """Convert modern HTML to retro-compatible markup and proxy all links/images."""
    soup = BeautifulSoup(html, "lxml")

    # Semantic → legacy tag conversion
    for tag in soup.find_all("strong"):
        tag.name = "b"
    for tag in soup.find_all("em"):
        tag.name = "i"

    # Remove non-retro elements
    for tag in soup.find_all(_REMOVE_TAGS):
        tag.decompose()

    # Proxy all anchor hrefs
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        # Block dangerous schemes
        if href.lower().startswith(("javascript:", "data:", "vbscript:", "file:")):
            a.decompose()
            continue
        if href.startswith("#") or href.startswith("mailto:"):
            continue
        if href.startswith("//"):
            href = "https:" + href
        elif not href.startswith("http"):
            try:
                href = urljoin(base_url, href)
            except Exception:
                a.decompose()
                continue
        if href.startswith("http"):
            a["href"] = f"/read?a={href}"

    # Proxy all images
    for img in soup.find_all("img"):
        src = img.get("src", "").strip()
        if src.startswith("//"):
            src = "https:" + src
        elif not src.startswith("http"):
            try:
                src = urljoin(base_url, src)
            except Exception:
                img.decompose()
                continue
        if src.startswith("http"):
            img.attrs = {"src": f"/image?i={src}", "border": "0"}
        else:
            img.decompose()

    # Normalize unicode to ASCII
    result = normalize_text(str(soup))
    return result


def _run_readability(html: str, url: str) -> Tuple[str, str]:
    doc = Document(html)
    title = doc.title() or "Article"
    content = doc.summary(html_partial=True)
    retro = _convert_to_retro(content, url)
    return title, retro


async def fetch_and_extract(
    url: str,
) -> Tuple[Optional[str], Optional[str], str, int]:
    """
    Fetch a URL and extract article content via Readability.

    Returns: (title, retro_html, content_type, content_length)
    Non-HTML content returns (None, None, content_type, content_length).
    """
    settings = get_settings()

    async with httpx.AsyncClient(
        timeout=settings.request_timeout,
        follow_redirects=True,
        headers=_HEADERS,
    ) as client:
        try:
            head = await client.head(url)
            ct = head.headers.get("content-type", "").lower()
            cl_str = head.headers.get("content-length", "0")
            content_length = int(cl_str) if cl_str.isdigit() else 0
        except Exception:
            ct = "text/html"
            content_length = 0

        is_html = not ct or "text/html" in ct or "text/plain" in ct or "xml" in ct

        if not is_html:
            return None, None, ct, content_length

        resp = await client.get(url)
        resp.raise_for_status()
        raw_html = resp.text

    loop = asyncio.get_event_loop()
    title, retro_html = await loop.run_in_executor(None, _run_readability, raw_html, url)
    return title, retro_html, "text/html", 0


async def fetch_binary(url: str) -> Tuple[bytes, str]:
    """Stream a non-HTML file and return its raw bytes + content-type."""
    settings = get_settings()
    async with httpx.AsyncClient(
        timeout=settings.request_timeout,
        follow_redirects=True,
    ) as client:
        resp = await client.get(url, headers=_HEADERS)
        resp.raise_for_status()
        return resp.content, resp.headers.get("content-type", "application/octet-stream")
