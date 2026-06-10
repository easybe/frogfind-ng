"""
Reddit Reader
  GET /reddit                      → Directory
  GET /reddit?r=linux              → Subreddit listing
  GET /reddit?r=linux&sort=new     → Sorted listing
  GET /reddit?r=linux&post=abc123  → Post + comments (OAuth only)
  GET /reddit?q=vintage computing  → Reddit-wide search
"""
from __future__ import annotations

import json
import logging
from html import escape as _esc

from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

from app.limiter import limiter
from app.services.cache import get_redis
from app.services.reddit import DEFAULT_SUBS, _has_oauth, get_post, get_subreddit, search_reddit

log = logging.getLogger(__name__)
router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

_CACHE_SUB  = 300   # 5 min — subreddit feeds
_CACHE_POST = 600   # 10 min — individual posts


def _err(request, msg, code=400):
    return templates.TemplateResponse(
        "error.html", {"request": request, "message": msg}, status_code=code
    )


@router.get("/reddit", include_in_schema=False)
@limiter.limit("20/minute")
async def reddit(
    request: Request,
    r:    str = "",
    sort: str = "hot",
    post: str = "",
    q:    str = "",
):
    r    = r.strip()[:50]
    sort = sort.strip()[:10]
    post = post.strip()[:20]
    q    = q.strip()[:200]
    redis = await get_redis()

    # ── Directory ─────────────────────────────────────────────────────────────
    if not r and not q:
        return templates.TemplateResponse("reddit.html", {
            "request":      request,
            "sub_info":     None,
            "posts":        None,
            "default_subs": DEFAULT_SUBS,
            "has_oauth":    _has_oauth(),
            "query":        "",
            "error":        None,
        })

    # ── Reddit-wide search ────────────────────────────────────────────────────
    if q and not r:
        cache_key = f"reddit_search:{q.lower()}"
        cached = await redis.get(cache_key)
        if cached:
            payload = json.loads(cached)
        else:
            try:
                info, posts = await search_reddit(q)
                payload = {"info": info, "posts": posts}
                await redis.setex(cache_key, _CACHE_SUB, json.dumps(payload))
            except ValueError as exc:
                return _err(request, _esc(str(exc)), 404)
            except Exception as exc:
                log.warning("Reddit search error: %s", exc)
                return _err(request, f"Reddit search failed: {_esc(str(exc))}", 502)

        return templates.TemplateResponse("reddit.html", {
            "request":      request,
            "sub_info":     payload["info"],
            "posts":        payload["posts"],
            "default_subs": DEFAULT_SUBS,
            "has_oauth":    _has_oauth(),
            "query":        _esc(q),
            "error":        None,
        })

    # ── Post + comments (OAuth required) ─────────────────────────────────────
    if r and post:
        if not _has_oauth():
            return _err(
                request,
                "Post detail view requires Reddit API credentials. "
                "Set <tt>REDDIT_CLIENT_ID</tt> and <tt>REDDIT_CLIENT_SECRET</tt> in <tt>.env</tt>.",
                403,
            )

        cache_key = f"reddit_post:{r.lower()}:{post}"
        cached = await redis.get(cache_key)
        if cached:
            payload = json.loads(cached)
        else:
            try:
                post_data, comments = await get_post(r, post)
                payload = {"post": post_data, "comments": comments}
                await redis.setex(cache_key, _CACHE_POST, json.dumps(payload))
            except ValueError as exc:
                return _err(request, _esc(str(exc)), 404)
            except Exception as exc:
                log.warning("Reddit post error r/%s/%s: %s", r, post, exc)
                return _err(request, f"Could not load post: {_esc(str(exc))}", 502)

        return templates.TemplateResponse("reddit_post.html", {
            "request":  request,
            "sub":      _esc(r),
            "post":     payload["post"],
            "comments": payload["comments"],
        })

    # ── Subreddit listing ─────────────────────────────────────────────────────
    cache_key = f"reddit_sub:{r.lower()}:{sort}"
    cached = await redis.get(cache_key)
    if cached:
        payload = json.loads(cached)
    else:
        try:
            info, posts = await get_subreddit(r, sort=sort)
            payload = {"info": info, "posts": posts}
            await redis.setex(cache_key, _CACHE_SUB, json.dumps(payload))
        except ValueError as exc:
            return _err(request, _esc(str(exc)), 404)
        except Exception as exc:
            log.warning("Reddit sub error r/%s: %s", r, exc)
            return _err(request, f"Could not load r/{_esc(r)}: {_esc(str(exc))}", 502)

    return templates.TemplateResponse("reddit.html", {
        "request":      request,
        "sub_info":     payload["info"],
        "posts":        payload["posts"],
        "default_subs": DEFAULT_SUBS,
        "has_oauth":    _has_oauth(),
        "query":        "",
        "error":        None,
    })
