"""
Reddit reader service.

Two backends, selected automatically:
  OAuth2  — when REDDIT_CLIENT_ID + REDDIT_CLIENT_SECRET are set in .env
            Full JSON API: subreddit listings, post detail, comments, search.
  RSS     — fallback when no credentials are set.
            Subreddit listings + search via public Atom feeds only.

OAuth2 registration (free, no approval needed):
  https://www.reddit.com/prefs/apps  → "create another app" → type: script
"""
from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from html import escape as _esc
from html import unescape as _unescape
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote
from xml.etree import ElementTree as ET

import httpx

from app.config import get_settings

# ── Constants ─────────────────────────────────────────────────────────────────

_WWW   = "https://www.reddit.com"
_OAUTH = "https://oauth.reddit.com"
_TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
_ATOM_NS   = "{http://www.w3.org/2005/Atom}"

_RSS_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/rss+xml, application/atom+xml, */*",
}

# Reddit requires: platform:appid:version (by /u/username) for OAuth
_OAUTH_UA = "FrogFindNG:frogfind-ng:1.0 (server; retro search engine)"

# In-process token cache (also written to Redis for multi-worker)
_token_cache: Dict[str, Any] = {}


# ── Helpers ────────────────────────────────────────────────────────────────────

def _has_oauth() -> bool:
    s = get_settings()
    return bool(s.reddit_client_id and s.reddit_client_secret)


def _fmt_score(n) -> str:
    try:
        n = int(n)
    except (TypeError, ValueError):
        return "0"
    return f"{n / 1000:.1f}k" if n >= 1000 else str(n)


def _fmt_ts(ts) -> str:
    try:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc).strftime("%d %b %Y %H:%M")
    except Exception:
        return ""


# ── Markdown → retro HTML ──────────────────────────────────────────────────────

def _md_to_html(text: str) -> str:
    """Convert Reddit markdown to safe retro HTML (HTML-escape first)."""
    if not text or text in ("[deleted]", "[removed]"):
        return ""
    text = _esc(text)
    # Fenced code blocks
    text = re.sub(
        r"```(?:\w+)?\n?(.*?)```",
        lambda m: f"<pre>{m.group(1)}</pre>",
        text, flags=re.DOTALL,
    )
    text = re.sub(r"`([^`\n]+)`", r"<tt>\1</tt>", text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"__(.+?)__",     r"<b>\1</b>", text)
    text = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<i>\1</i>", text)
    text = re.sub(r"~~(.+?)~~", r"<s>\1</s>", text)
    # Markdown links [label](url)
    text = re.sub(r"\[([^\]]+)\]\((https?://[^\)]+)\)", r'<a href="\2">\1</a>', text)
    # Bare URLs
    text = re.sub(
        r'(?<![=">])https?://[^\s<>"]+',
        lambda m: f'<a href="{m.group()}">{m.group()}</a>',
        text,
    )
    text = re.sub(r"^#{1,3} (.+)$", r"<b>\1</b>", text, flags=re.MULTILINE)
    text = re.sub(r"^---+$", "<hr>", text, flags=re.MULTILINE)
    paragraphs = re.split(r"\n{2,}", text)
    return "".join(f"<p>{p.replace(chr(10), '<br>')}</p>" for p in paragraphs if p.strip())


# ── OAuth2 token management ────────────────────────────────────────────────────

async def _get_oauth_token() -> str:
    """
    Return a valid Bearer token. Fetches a new one if expired or missing.
    Uses Redis for cross-worker sharing (in-process dict as first-level cache).
    """
    # 1. In-process cache
    now = time.time()
    if _token_cache.get("token") and _token_cache.get("expires_at", 0) > now + 60:
        return _token_cache["token"]

    # 2. Redis cache
    from app.services.cache import get_redis
    redis = await get_redis()
    cached = await redis.get("reddit:oauth_token")
    if cached:
        _token_cache["token"]      = cached
        _token_cache["expires_at"] = now + 3500   # conservative estimate
        return cached

    # 3. Fetch new token
    settings = get_settings()
    async with httpx.AsyncClient(timeout=10.0) as c:
        resp = await c.post(
            _TOKEN_URL,
            auth=(settings.reddit_client_id, settings.reddit_client_secret),
            data={"grant_type": "client_credentials"},
            headers={"User-Agent": _OAUTH_UA},
        )
        resp.raise_for_status()
        data = resp.json()

    token      = data["access_token"]
    expires_in = int(data.get("expires_in", 3600))

    # Cache in Redis (expire slightly early)
    await redis.setex("reddit:oauth_token", expires_in - 120, token)

    _token_cache["token"]      = token
    _token_cache["expires_at"] = now + expires_in - 120
    return token


async def _oauth_get(path: str, params: dict | None = None) -> dict:
    """Authenticated GET to oauth.reddit.com."""
    settings = get_settings()
    token = await _get_oauth_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "User-Agent": _OAUTH_UA,
        "Accept": "application/json",
    }
    async with httpx.AsyncClient(
        timeout=settings.request_timeout,
        follow_redirects=True,
        headers=headers,
    ) as c:
        resp = await c.get(f"{_OAUTH}{path}", params=params or {})
        if resp.status_code == 401:
            # Token may have been revoked — clear cache and retry once
            _token_cache.clear()
            from app.services.cache import get_redis
            redis = await get_redis()
            await redis.delete("reddit:oauth_token")
            token = await _get_oauth_token()
            headers["Authorization"] = f"Bearer {token}"
            resp = await c.get(f"{_OAUTH}{path}", params=params or {})
        resp.raise_for_status()
        return resp.json()


# ── OAuth post/comment cleaning ────────────────────────────────────────────────

def _clean_post_oauth(raw: dict) -> Optional[Dict[str, Any]]:
    d = raw.get("data", {})
    if d.get("removed_by_category") or d.get("author") in ("[deleted]", None):
        return None
    permalink = d.get("permalink", "")
    return {
        "id":           d.get("id", ""),
        "title":        d.get("title", "(no title)"),
        "author":       d.get("author", "unknown"),
        "subreddit":    d.get("subreddit", ""),
        "score":        _fmt_score(d.get("score", 0)),
        "num_comments": d.get("num_comments", 0),
        "url":          d.get("url", ""),
        "permalink":    f"https://old.reddit.com{permalink}",
        "is_self":      bool(d.get("is_self")),
        "selftext":     _md_to_html(d.get("selftext", "")),
        "domain":       d.get("domain", ""),
        "flair":        d.get("link_flair_text") or "",
        "date":         _fmt_ts(d.get("created_utc", 0)),
        "nsfw":         bool(d.get("over_18")),
    }


def _clean_comment(raw: dict, depth: int = 0) -> Optional[Dict[str, Any]]:
    if raw.get("kind") == "more":
        return None
    d = raw.get("data", {})
    body = d.get("body", "")
    if not body or body in ("[deleted]", "[removed]") or d.get("author") in (None, "[deleted]"):
        return None

    replies_raw = d.get("replies", "")
    replies: List[Dict] = []
    if depth < 2 and isinstance(replies_raw, dict):
        for child in replies_raw.get("data", {}).get("children", []):
            c = _clean_comment(child, depth + 1)
            if c:
                replies.append(c)

    return {
        "author":  d.get("author", "unknown"),
        "score":   _fmt_score(d.get("score", 0)),
        "body":    _md_to_html(body),
        "date":    _fmt_ts(d.get("created_utc", 0)),
        "replies": replies[:5],
    }


# ── OAuth backend ─────────────────────────────────────────────────────────────

async def _oauth_subreddit(sub: str, sort: str = "hot") -> Tuple[Dict, List[Dict]]:
    sort = sort if sort in ("hot", "new", "top", "rising") else "hot"
    data = await _oauth_get(f"/r/{sub}/{sort}", {"limit": 25, "raw_json": 1})
    children = data.get("data", {}).get("children", [])
    posts = [p for raw in children if (p := _clean_post_oauth(raw)) is not None]
    return {"name": sub, "title": f"r/{sub}", "sort": sort, "mode": "oauth"}, posts


async def _oauth_post(sub: str, post_id: str) -> Tuple[Optional[Dict], List[Dict]]:
    data = await _oauth_get(
        f"/r/{sub}/comments/{post_id}",
        {"limit": 100, "depth": 3, "raw_json": 1},
    )
    if not isinstance(data, list) or len(data) < 2:
        raise ValueError("Unexpected Reddit response.")

    post_children = data[0].get("data", {}).get("children", [])
    post = _clean_post_oauth(post_children[0]) if post_children else None

    comment_children = data[1].get("data", {}).get("children", [])
    comments = [c for raw in comment_children if (c := _clean_comment(raw)) is not None]
    return post, comments


async def _oauth_search(query: str) -> Tuple[Dict, List[Dict]]:
    data = await _oauth_get("/search", {"q": query, "sort": "relevance", "limit": 25, "raw_json": 1})
    children = data.get("data", {}).get("children", [])
    posts = [p for raw in children if (p := _clean_post_oauth(raw)) is not None]
    return {"name": "Search", "title": f"Reddit: {query}", "sort": "relevance", "mode": "oauth"}, posts


# ── RSS backend ───────────────────────────────────────────────────────────────

def _parse_rss_content(raw: str) -> Tuple[Optional[str], Optional[str]]:
    text = _unescape(raw or "")
    link_m    = re.search(r'href="([^"]+)"[^>]*>\s*\[link\]', text)
    comment_m = re.search(r'href="([^"]+)"[^>]*>\s*\[comments\]', text)
    return (
        link_m.group(1)    if link_m    else None,
        comment_m.group(1) if comment_m else None,
    )


def _fmt_rss_date(iso: str) -> str:
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.strftime("%d %b %Y %H:%M")
    except Exception:
        return iso or ""


def _parse_rss_feed(xml_text: str) -> Tuple[str, List[Dict]]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return "Reddit", []

    title_el = root.find(f"{_ATOM_NS}title")
    feed_title = (title_el.text or "Reddit") if title_el is not None else "Reddit"

    posts = []
    for entry in root.findall(f"{_ATOM_NS}entry"):
        def _t(tag: str) -> str:
            el = entry.find(f"{_ATOM_NS}{tag}")
            return (el.text or "").strip() if el is not None else ""

        raw_id    = _t("id")
        title     = _t("title")
        updated   = _fmt_rss_date(_t("updated") or _t("published"))
        author_el = entry.find(f"{_ATOM_NS}author/{_ATOM_NS}name")
        author    = (author_el.text or "").strip().lstrip("/u/") if author_el is not None else "unknown"

        link_el   = entry.find(f"{_ATOM_NS}link")
        raw_link  = link_el.get("href", "") if link_el is not None else ""
        permalink = raw_link.replace("https://www.reddit.com", "https://old.reddit.com", 1)

        cat_el    = entry.find(f"{_ATOM_NS}category")
        subreddit = cat_el.get("term", "") if cat_el is not None else ""

        content_el  = entry.find(f"{_ATOM_NS}content")
        content_raw = (content_el.text or "") if content_el is not None else ""
        ext_url, _  = _parse_rss_content(content_raw)

        is_self = ext_url is None
        m       = re.search(r"https?://([^/]+)", ext_url) if ext_url and not is_self else None

        if not title:
            continue

        posts.append({
            "id":           raw_id.removeprefix("t3_"),
            "title":        title,
            "author":       author,
            "subreddit":    subreddit,
            "score":        "—",
            "num_comments": None,
            "url":          ext_url or permalink,
            "permalink":    permalink,
            "is_self":      is_self,
            "selftext":     "",
            "domain":       m.group(1) if m else "",
            "flair":        "",
            "date":         updated,
            "nsfw":         False,
        })
    return feed_title, posts


async def _rss_fetch(url: str) -> Tuple[str, List[Dict]]:
    settings = get_settings()
    async with httpx.AsyncClient(
        timeout=settings.request_timeout, headers=_RSS_HEADERS, follow_redirects=True,
    ) as c:
        resp = await c.get(url)
        if resp.status_code == 403:
            raise ValueError("Reddit RSS access denied.")
        if resp.status_code == 404:
            raise ValueError("Subreddit not found or private.")
        resp.raise_for_status()
    return _parse_rss_feed(resp.text)


async def _rss_subreddit(sub: str, sort: str = "hot") -> Tuple[Dict, List[Dict]]:
    sort = sort if sort in ("hot", "new", "top", "rising") else "hot"
    url  = f"{_WWW}/r/{sub}.rss" if sort == "hot" else f"{_WWW}/r/{sub}/{sort}.rss"
    feed_title, posts = await _rss_fetch(f"{url}?limit=25")
    return {"name": sub, "title": feed_title, "sort": sort, "mode": "rss"}, posts


async def _rss_search(query: str) -> Tuple[Dict, List[Dict]]:
    url = f"{_WWW}/search.rss?q={quote(query)}&sort=relevance&limit=25"
    _, posts = await _rss_fetch(url)
    return {"name": "Search", "title": f"Reddit: {query}", "sort": "relevance", "mode": "rss"}, posts


# ── Public API — auto-selects backend ────────────────────────────────────────

async def get_subreddit(sub: str, sort: str = "hot") -> Tuple[Dict, List[Dict]]:
    if _has_oauth():
        return await _oauth_subreddit(sub, sort)
    return await _rss_subreddit(sub, sort)


async def get_post(sub: str, post_id: str) -> Tuple[Optional[Dict], List[Dict]]:
    """Only available with OAuth credentials."""
    if not _has_oauth():
        raise ValueError(
            "Post detail view requires Reddit API credentials. "
            "See .env for REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET."
        )
    return await _oauth_post(sub, post_id)


async def search_reddit(query: str) -> Tuple[Dict, List[Dict]]:
    if _has_oauth():
        return await _oauth_search(query)
    return await _rss_search(query)


# ── Default subreddit directory ───────────────────────────────────────────────

DEFAULT_SUBS = [
    ("retrobattlestations", "Retro Computers & Setup"),
    ("vintagecomputing",    "Vintage Computing"),
    ("c64",                 "Commodore 64"),
    ("amiga",               "Amiga"),
    ("apple2",              "Apple II"),
    ("linux",               "Linux"),
    ("programming",         "Programming"),
    ("todayilearned",       "Today I Learned"),
    ("worldnews",           "World News"),
    ("askscience",          "Ask Science"),
    ("explainlikeimfive",   "Explain Like I'm Five"),
    ("history",             "History"),
]
